import assert from 'node:assert/strict';
import test from 'node:test';
import {spineItemForDocument, displayEpubDestination} from '../src/cookbook/reader_epub.mjs';
const origin='https://reader.example';
test('root-level EPUB chapters cannot collide with an earlier nested filename',()=>{
 const nested={index:0,href:'part1/intro.xhtml',url:'/part1/intro.xhtml'};
 const root={index:1,href:'intro.xhtml',url:'/intro.xhtml'};
 assert.equal(spineItemForDocument([nested,root],'intro.xhtml',origin),root);
});
test('encoded manifest paths match decoded archive-root paths including the OPF directory',()=>{
 const item={index:0,href:'Text/Part%201.xhtml',url:'/OEBPS/Text/Part%201.xhtml'};
 assert.equal(spineItemForDocument([item],'OEBPS/Text/Part 1.xhtml',origin),item);
 assert.throws(()=>spineItemForDocument([item],'Text/Part 1.xhtml',origin));
});
test('literal percent escapes in an archive filename are not decoded a second time',()=>{
 const item={index:0,url:'/100%2520coverage.xhtml'};
 assert.equal(spineItemForDocument([item],'100%20coverage.xhtml',origin),item);
 assert.throws(()=>spineItemForDocument([item],'100 coverage.xhtml',origin));
});
test('repeated documents require an explicitly retained occurrence',()=>{
 const a={index:0,url:'/same.xhtml'},b={index:1,url:'/same.xhtml'};
 assert.throws(()=>spineItemForDocument([a,b],'same.xhtml',origin));
 assert.equal(spineItemForDocument([a,b],'same.xhtml',origin,1),b);
 assert.throws(()=>spineItemForDocument([a,b],'other.xhtml',origin,1));
});
test('remote or invalid spine paths never become source-document matches',()=>{
 assert.throws(()=>spineItemForDocument([{url:'https://external.example/intro.xhtml'}],'intro.xhtml',origin));
 assert.throws(()=>spineItemForDocument([{href:'intro.xhtml'}],'intro.xhtml',origin));
});
test('display preserves occurrence zero rather than resolving an aliased href',async()=>{
 const first={index:0,href:'same.xhtml',url:'/same.xhtml'};
 const last={index:2,href:'same.xhtml',url:'/same.xhtml'};
 const book={spine:{spineItems:[first,last]}};
 let rendered;
 const rendition={
   display:async target=>{rendered=typeof target==='number'?target:2;return {index:rendered};},
   getContents:()=>[{sectionIndex:rendered}]
 };
 await displayEpubDestination(book,rendition,{epub_document:'same.xhtml',epub_occurrence:0},origin);
 assert.equal(rendered,0);
});
test('display refuses an engine result from a different occurrence',async()=>{
 const book={spine:{spineItems:[{index:0,url:'/same.xhtml'}]}};
 const rendition={display:async()=>({index:2}),getContents:()=>[{sectionIndex:2}]};
 await assert.rejects(displayEpubDestination(book,rendition,{epub_document:'same.xhtml',epub_occurrence:0},origin),/occurrence unavailable/);
});
test('duplicate source IDs refuse native and legacy anchor destinations before rendering',async()=>{
 const sourceDocument={querySelectorAll:()=>[{getAttribute:()=> 'recipe'},{getAttribute:()=> 'recipe'}]};
 const item={index:0,url:'/dup.xhtml',load:async()=>({ownerDocument:sourceDocument})};
 const book={spine:{spineItems:[item]},load(){}};
 let displayed=false;
 const rendition={display:async()=>{displayed=true;}};
 for(const xpath of ['/*/*[2]/*[122]','']){
   await assert.rejects(displayEpubDestination(book,rendition,{epub_document:'dup.xhtml',epub_anchor:'recipe',epub_xpath:xpath},origin),/anchor unavailable or ambiguous/);
 }
 assert.equal(displayed,false);
});

// ---- Range-backed archive -------------------------------------------------
import {crc32 as crc, readZipIndex, RangeArchive, ZIP_LIMITS, openingMembers} from '../src/cookbook/reader_epub.mjs';
import {crc32 as zlibCrc, deflateRawSync} from 'node:zlib';
import {randomBytes} from 'node:crypto';

// Build a synthetic ZIP; overrides let a test corrupt one central/local field.
function zip(members, {comment = Buffer.alloc(0)} = {}) {
  const locals = [], central = [];
  let offset = 0;
  for (const m of members) {
    const name = Buffer.from(m.name), data = Buffer.from(m.data);
    const method = m.method ?? 8, body = method === 8 ? deflateRawSync(data) : data;
    const crcValue = m.crc ?? zlibCrc(data), size = m.size ?? data.length, csize = m.csize ?? body.length;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(m.localFlags ?? m.flags ?? 0, 6);
    local.writeUInt16LE(m.localMethod ?? method, 8); local.writeUInt32LE(crcValue, 14); local.writeUInt32LE(csize, 18);
    local.writeUInt32LE(size, 22); local.writeUInt16LE(name.length, 26);
    const localName = m.localName ? Buffer.from(m.localName) : name;
    const record = Buffer.alloc(46);
    record.writeUInt32LE(0x02014b50, 0); record.writeUInt16LE(20, 4); record.writeUInt16LE(20, 6);
    record.writeUInt16LE(m.flags ?? 0, 8); record.writeUInt16LE(method, 10); record.writeUInt32LE(crcValue, 16);
    record.writeUInt32LE(csize, 20); record.writeUInt32LE(size, 24); record.writeUInt16LE(name.length, 28);
    record.writeUInt32LE(m.offset ?? offset, 42);
    locals.push(local, localName, body);
    central.push(record, name);
    offset += 30 + localName.length + body.length;
  }
  const cd = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(members.length, 8); end.writeUInt16LE(members.length, 10);
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16); end.writeUInt16LE(comment.length, 20);
  return Buffer.concat([...locals, cd, end, comment]);
}

// Serve exact byte ranges like /reader/source; `tamper` can misreport one answer.
function ranges(file, tamper = result => result) {
  const calls = [];
  const fetchRange = async header => {
    calls.push(header);
    const [, a, b] = /^bytes=(\d*)-(\d*)$/.exec(header);
    const start = a ? Number(a) : Math.max(0, file.length - Number(b));
    const end = a ? Math.min(Number(b), file.length - 1) : file.length - 1;
    return tamper({bytes: new Uint8Array(file.subarray(start, end + 1)), start, end, total: file.length}, header);
  };
  return {fetchRange, calls};
}

const utils = {isXml: type => ['xml', 'opf', 'ncx'].includes(type), parse: (text, type) => ({parsed: text, type})};
const book = () => [
  {name: 'mimetype', data: 'application/epub+zip', method: 0},
  {name: 'META-INF/container.xml', data: '<container/>'},
  {name: 'OEBPS/content.opf', data: '<package/>'},
  {name: 'OEBPS/Text/Part 1.xhtml', data: '<html>' + 'chapter '.repeat(500) + '</html>'},
  {name: 'OEBPS/Images/cover.jpg', data: randomBytes(1000), method: 0},
];

test('the central directory and members come from exact, CRC-checked ranges', async () => {
  const {fetchRange, calls} = ranges(zip(book()));
  const archive = new RangeArchive(await readZipIndex(fetchRange));
  archive.utils = utils;
  assert.deepEqual(calls, ['bytes=-262144']);
  assert.equal(await archive.getText('/OEBPS/Text/Part%201.xhtml'), '<html>' + 'chapter '.repeat(500) + '</html>');
  assert.deepEqual(await archive.request('/OEBPS/content.opf'), {parsed: '<package/>', type: 'text/xml'});
  assert.equal((await archive.getBlob('/OEBPS/Images/cover.jpg')).type, 'image/jpeg');
  // A small book is entirely inside the directory tail: no further requests.
  assert.equal(calls.length, 1);
  await assert.rejects(archive.request('/missing.xhtml'), {message: 'File not found in the epub: /missing.xhtml'});
  assert.equal(crc(Buffer.from('123456789')), 0xcbf43926);
});

test('wanted members far from the tail are coalesced into few ranges', async () => {
  const members = [
    {name: 'a.xhtml', data: 'a'.repeat(100)},
    {name: 'pad1.bin', data: randomBytes(512 * 1024), method: 0},
    {name: 'b.xhtml', data: 'b'.repeat(100)},
    {name: 'pad2.bin', data: randomBytes(2 * 1024 * 1024), method: 0},
    {name: 'c.xhtml', data: 'c'.repeat(100)},
    {name: 'pad3.bin', data: randomBytes(600 * 1024), method: 0},
  ];
  const {fetchRange, calls} = ranges(zip(members));
  const archive = new RangeArchive(await readZipIndex(fetchRange));
  archive.prefetch(['a.xhtml', 'b.xhtml', 'c.xhtml']);
  assert.deepEqual(await Promise.all(['/a.xhtml', '/b.xhtml', '/c.xhtml'].map(url => archive.getText(url))),
    ['a'.repeat(100), 'b'.repeat(100), 'c'.repeat(100)]);
  assert.equal(calls.length, 3, calls.join(', '));
  assert.ok(calls.slice(1).every(header => /^bytes=\d+-\d+$/.test(header)));
  // Cached members, and members converted to blob URLs, are not fetched again.
  await archive.createUrl('/a.xhtml');
  archive.prefetch(['a.xhtml', 'b.xhtml']);
  assert.equal(calls.length, 3);
  archive.destroy();
});

test('unsupported or over-budget archives refuse before any member is read', async () => {
  const cases = {
    encrypted: [{name: 'x', data: 'x', flags: 1}],
    method: [{name: 'x', data: 'x', method: 12}],
    zip64: [{name: 'x', data: 'x', size: 0xffffffff}],
    member: [{name: 'x', data: 'x', size: ZIP_LIMITS.member + 1}],
    duplicate: [{name: 'x', data: 'x'}, {name: 'x', data: 'y'}],
    overlap: [{name: 'x', data: 'x'.repeat(50)}, {name: 'y', data: 'y', offset: 10}],
    unflaggedUtf8: [{name: 'é.xhtml', data: 'x'}],
  };
  for (const [label, members] of Object.entries(cases)) {
    const {fetchRange, calls} = ranges(zip(members));
    await assert.rejects(readZipIndex(fetchRange), /EPUB archive unavailable/, label);
    assert.equal(calls.length, 1, label);
  }
  const total = Array.from({length: 9}, (_, i) => ({name: 'm' + i, data: 'x', size: 30 * 1024 ** 2}));
  await assert.rejects(readZipIndex(ranges(zip(total)).fetchRange), /EPUB archive unavailable/);
  assert.ok(await readZipIndex(ranges(zip([{name: 'é.xhtml', data: 'x', flags: 0x800}])).fetchRange));
});

test('a damaged member rejects the archive instead of returning altered bytes', async () => {
  const cases = {
    crc: {name: 'x.xhtml', data: 'hello', crc: 1},
    larger: {name: 'x.xhtml', data: 'hello world', size: 5},
    smaller: {name: 'x.xhtml', data: 'hi', size: 5},
    localName: {name: 'x.xhtml', data: 'hello', localName: 'y.xhtml'},
    localMethod: {name: 'x.xhtml', data: 'hello', localMethod: 0},
    localEncrypted: {name: 'x.xhtml', data: 'hello', localFlags: 1},
  };
  for (const [label, member] of Object.entries(cases)) {
    const archive = new RangeArchive(await readZipIndex(ranges(zip([member])).fetchRange));
    await assert.rejects(archive.getText('/x.xhtml'), /EPUB archive unavailable/, label);
    await assert.rejects(archive.failed, /EPUB archive unavailable/, label);
  }
});

test('a range answer for a different span or file is never used', async () => {
  const file = zip([{name: 'x.xhtml', data: 'x'}, {name: 'pad', data: randomBytes(400 * 1024), method: 0}]);
  const shifted = ranges(file, (result, header) => header.startsWith('bytes=-') ? result : {...result, start: result.start + 1});
  const archive = new RangeArchive(await readZipIndex(shifted.fetchRange));
  await assert.rejects(archive.getText('/x.xhtml'), /EPUB archive unavailable/);
  const resized = ranges(file, (result, header) => header.startsWith('bytes=-') ? result : {...result, total: result.total + 1});
  await assert.rejects(new RangeArchive(await readZipIndex(resized.fetchRange)).getText('/x.xhtml'), /EPUB archive unavailable/);
  const short = ranges(file, result => ({...result, bytes: result.bytes.subarray(1)}));
  await assert.rejects(readZipIndex(short.fetchRange), /EPUB archive unavailable/);
  await assert.rejects(readZipIndex(ranges(Buffer.from('not a zip')).fetchRange), /EPUB archive unavailable/);
});

test('the opening set covers the package, navigation, styles and the destination only', async () => {
  const index = await readZipIndex(ranges(zip([
    ...book(), {name: 'OEBPS/toc.ncx', data: '<ncx/>'}, {name: 'OEBPS/Text/nav.xhtml', data: '<nav/>'},
    {name: 'OEBPS/Styles/main.css', data: 'p{}'}, {name: 'OEBPS/Text/Part 2.xhtml', data: '<html/>'},
  ])).fetchRange);
  assert.deepEqual(openingMembers(index, 'OEBPS/Text/Part 2.xhtml').sort(), [
    'META-INF/container.xml', 'OEBPS/Styles/main.css', 'OEBPS/Text/Part 2.xhtml', 'OEBPS/Text/nav.xhtml',
    'OEBPS/content.opf', 'OEBPS/toc.ncx',
  ]);
});
