import assert from 'node:assert/strict';
import test from 'node:test';
import {rangeBatcher, rangeHeader, spanBytes, CHUNK, OPENING, BURST, MAX_RANGES} from '../src/cookbook/reader_pdf.mjs';

// Run a batcher over an invented file, recording each fetch and delivery.
async function batch(total, requests) {
  const fetched = [], delivered = [], failures = [];
  const done = new Promise(resolve => {
    let pending = requests.length;
    const request = rangeBatcher({
      total,
      fetchSpans: async spans => { fetched.push(spans.map(({begin, end}) => ({begin, end}))); return spans.map(span => new Uint8Array(span.end - span.begin).map((_, i) => (span.begin + i) % 251)); },
      deliver: (begin, bytes) => { delivered.push({begin, bytes}); if (--pending === 0) resolve(); },
      fail: error => { failures.push(error); resolve(); },
    });
    for (const [begin, end] of requests) request(begin, end);
  });
  await done;
  return {fetched, delivered, failures};
}

test('a burst of scattered requests becomes a few small multi-range requests', async () => {
  // pdf.js asks for every page dictionary of a flat page tree at once.
  const total = 300 * 65536 + 1234, requests = Array.from({length: 300}, (_, i) => [i * 65536, i * 65536 + CHUNK]).reverse();
  const {fetched, delivered, failures} = await batch(total, requests);
  assert.deepEqual(failures, []);
  assert.equal(fetched.length, Math.ceil(300 / MAX_RANGES));
  assert.ok(fetched.every(spans => spans.length <= MAX_RANGES));
  const bytes = fetched.flat().reduce((sum, span) => sum + span.end - span.begin, 0);
  assert.ok(bytes <= BURST, `burst read ${bytes} bytes`);
  // Each delivery starts at a requested begin, covers it, and ends on a chunk.
  assert.equal(delivered.length, 300);
  for (const {begin, bytes} of delivered) {
    const request = requests.find(([b]) => b === begin);
    assert.ok(request && begin + bytes.length >= request[1]);
    assert.ok((begin + bytes.length) % CHUNK === 0 || begin + bytes.length === total);
    assert.equal(bytes[0], begin % 251);
  }
});

test('a lone request reads ahead like the opening ranges', async () => {
  const {fetched, delivered} = await batch(10 * OPENING, [[3 * CHUNK, 4 * CHUNK]]);
  assert.deepEqual(fetched, [[{begin: 3 * CHUNK, end: 3 * CHUNK + OPENING}]]);
  assert.equal(delivered[0].bytes.length, OPENING);
  // Near the end the read stops at the file.
  const near = await batch(OPENING + 100, [[OPENING - CHUNK, OPENING]]);
  assert.deepEqual(near.fetched, [[{begin: OPENING - CHUNK, end: OPENING + 100}]]);
});

test('adjacent requests share one span and are each delivered once', async () => {
  const requests = [[0, CHUNK], [CHUNK, 2 * CHUNK], [2 * CHUNK, 3 * CHUNK]];
  const {fetched, delivered} = await batch(4 * OPENING, requests);
  assert.deepEqual(fetched, [[{begin: 0, end: 2 * CHUNK + OPENING}]]);
  assert.deepEqual(delivered.map(({begin, bytes}) => [begin, bytes.length]), [[0, CHUNK], [CHUNK, CHUNK], [2 * CHUNK, OPENING]]);
});

test('a failed fetch fails the requests it carried', async () => {
  const failures = [];
  await new Promise(resolve => {
    const request = rangeBatcher({total: OPENING, fetchSpans: async () => { throw Error('unavailable'); }, deliver: () => {}, fail: error => { failures.push(error.message); resolve(); }});
    request(0, CHUNK);
  });
  assert.deepEqual(failures, ['unavailable']);
});

// A response shaped like /reader/source's multipart/byteranges.
function multipart(total, spans, {boundary = 'b0a1', range = span => `${span.begin}-${span.end - 1}/${total}`, closing = true} = {}) {
  const pieces = spans.flatMap(span => [`\r\n--${boundary}\r\nContent-Type: application/pdf\r\nContent-Range: bytes ${range(span)}\r\n\r\n`, 'x'.repeat(span.end - span.begin)]);
  if (closing) pieces.push(`\r\n--${boundary}--\r\n`);
  return new Response(pieces.join(''), {status: 206, headers: {'Content-Type': `multipart/byteranges; boundary=${boundary}`}});
}

test('multi-range responses must carry exactly the requested spans', async () => {
  const spans = [{begin: 0, end: 5}, {begin: 4096, end: 4100}];
  assert.equal(rangeHeader(spans), 'bytes=0-4,4096-4099');
  const parts = await spanBytes(multipart(9000, spans), spans, 9000);
  assert.deepEqual(parts.map(part => part.length), [5, 4]);
  for (const response of [
    multipart(9000, spans, {range: span => `${span.begin}-${span.end}/9000`}),
    multipart(9000, spans, {range: span => `${span.begin}-${span.end - 1}/9001`}),
    multipart(9000, spans.slice(0, 1)),
    multipart(9000, spans, {closing: false}),
    new Response(multipart(9000, spans).body, {status: 206, headers: {'Content-Type': 'multipart/byteranges; boundary=other'}}),
    new Response('', {status: 200, headers: {'Content-Type': 'multipart/byteranges; boundary=b0a1'}}),
  ]) await assert.rejects(spanBytes(response, spans, 9000), /unavailable/);
});

test('one span is read from a plain 206 response', async () => {
  const span = {begin: 10, end: 20};
  const reply = (range, body = 'y'.repeat(10)) => new Response(body, {status: 206, headers: {'Content-Range': range}});
  assert.equal((await spanBytes(reply('bytes 10-19/100'), [span], 100))[0].length, 10);
  await assert.rejects(spanBytes(reply('bytes 10-20/100'), [span], 100), /unavailable/);
  await assert.rejects(spanBytes(reply('bytes 10-19/100', 'short'), [span], 100), /unavailable/);
});
