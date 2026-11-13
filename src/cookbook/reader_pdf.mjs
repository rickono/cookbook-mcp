// Source ranges for pdf.js. Opening a PDF whose page dictionaries are spread
// through the file makes pdf.js ask for one range per page at once; sent one by
// one they serialize behind the session check and download most of the book.
// Requests that arrive together are read as one multi-range request instead.

// The first and last ranges, and the most a lone request reads ahead.
export const OPENING = 524288;
// pdf.js range granularity: small, so scattered objects stay small.
export const CHUNK = 4096;
// About how much a burst of scattered requests reads in total.
export const BURST = 2097152;
// Matches the server's MAX_RANGES.
export const MAX_RANGES = 128;

// Collect requests until the queue is quiet, then fetch them as spans.
// Each request is widened forward by a shared width: a lone request reads up to
// OPENING bytes, while many scattered requests share about BURST bytes. pdf.js
// accepts data only at a begin it asked for, so each request is delivered from
// its own begin; widened ends stay chunk multiples or the file end.
export function rangeBatcher({total, fetchSpans, deliver, fail, chunk=CHUNK, ahead=OPENING, burst=BURST, maxRanges=MAX_RANGES, quiet=2, wait=16}) {
  let queued, timer, started;
  const flush = () => {
    const wanted = queued.sort((a, b) => a.begin - b.begin); queued = undefined;
    let distinct = 0, reach = -1;
    for (const request of wanted) { if (request.begin > reach) distinct++; reach = Math.max(reach, request.end); }
    let width = chunk;
    while (width * 2 <= ahead && width * 2 * distinct <= burst) width *= 2;
    const spans = [];
    for (const request of wanted) {
      const end = Math.min(total, Math.max(request.end, request.begin + width)), span = spans.at(-1);
      if (span && request.begin <= span.end) { span.end = Math.max(span.end, end); span.requests.push(request); }
      else spans.push({begin:request.begin, end, requests:[request]});
    }
    for (let i = 0; i < spans.length; i += maxRanges) {
      const group = spans.slice(i, i + maxRanges);
      fetchSpans(group).then(parts => group.forEach((span, j) => span.requests.forEach((request, k) => {
        // Up to the next request's begin, so a long span is not delivered twice.
        const next = span.requests[k + 1]?.begin ?? span.end;
        deliver(request.begin, parts[j].subarray(request.begin - span.begin, Math.max(request.end, next) - span.begin));
      }))).catch(fail);
    }
  };
  return (begin, end) => {
    if (!queued) { queued = []; started = performance.now(); }
    queued.push({begin, end});
    clearTimeout(timer);
    timer = setTimeout(flush, Math.max(0, Math.min(quiet, started + wait - performance.now())));
  };
}

// The Range header for spans with exclusive ends.
export const rangeHeader = spans => 'bytes=' + spans.map(span => `${span.begin}-${span.end - 1}`).join(',');

// The bytes of each span from a 206 response, in order. Anything but exactly
// those spans of a file of `total` bytes is refused.
export async function spanBytes(result, spans, total) {
  const refuse = () => { result.body?.cancel().catch(() => {}); return Error('unavailable'); };
  if (result.status !== 206) throw refuse();
  if (spans.length === 1) {
    const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(result.headers.get('Content-Range') || '');
    if (!match || +match[1] !== spans[0].begin || +match[2] !== spans[0].end - 1 || +match[3] !== total) throw refuse();
    const bytes = new Uint8Array(await result.arrayBuffer());
    if (bytes.length !== spans[0].end - spans[0].begin) throw Error('unavailable');
    return [bytes];
  }
  const type = /^multipart\/byteranges;\s*boundary=([0-9A-Za-z'()+_,./:=?-]{1,70})$/i.exec(result.headers.get('Content-Type') || '');
  if (!type) throw refuse();
  const body = new Uint8Array(await result.arrayBuffer()), parts = [];
  const text = (from, to) => String.fromCharCode(...body.subarray(from, Math.min(to, body.length)));
  let at = 0;
  for (const span of spans) {
    // A part header ends at the first blank line, within a bounded prefix.
    let stop = -1;
    for (let i = at; i + 3 < Math.min(body.length, at + 1024); i++)
      if (body[i] === 13 && body[i + 1] === 10 && body[i + 2] === 13 && body[i + 3] === 10) { stop = i; break; }
    if (stop < 0) throw Error('unavailable');
    const [delimiter, ...fields] = text(at, stop).replace(/^\r\n/, '').split('\r\n');
    const range = fields.map(field => /^content-range:\s*bytes (\d+)-(\d+)\/(\d+)$/i.exec(field)).find(Boolean);
    if (delimiter !== '--' + type[1] || !range || +range[1] !== span.begin || +range[2] !== span.end - 1 || +range[3] !== total) throw Error('unavailable');
    at = stop + 4 + span.end - span.begin;
    if (at > body.length) throw Error('unavailable');
    parts.push(body.subarray(stop + 4, at));
  }
  if (text(at, at + type[1].length + 6) !== '\r\n--' + type[1] + '--') throw Error('unavailable');
  return parts;
}
