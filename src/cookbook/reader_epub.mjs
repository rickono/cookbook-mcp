/* Match the archive-root path retained by ingestion, never a filename suffix. */
export function spineItemForDocument(items, document, origin, occurrence) {
  const matches = items.filter(item => {
    if (typeof item.url !== 'string') return false;
    try {
      const url = new URL(item.url, origin + '/');
      if (url.origin !== origin) return false;
      const path = decodeURIComponent(url.pathname.replace(/%(?![0-9a-f]{2})/gi, '%25')).replace(/^\//, '');
      return path === document && (occurrence === undefined || item.index === occurrence);
    } catch { return false; }
  });
  if (matches.length !== 1) throw Error('Exact source document unavailable or ambiguous');
  return matches[0];
}

// Layout changes attributes on the body, but must not change its source tree
// before a positional XPath can identify the same node in both documents.
function unchangedBody(source, rendered) {
  if (!source || !rendered) return false;
  const pairs = [[source, rendered]];
  const children = node => Array.from(node.childNodes).filter(child => [1, 3, 4].includes(child.nodeType));
  while (pairs.length) {
    const [a, b] = pairs.pop();
    if (a.nodeType === 1 && b.nodeType === 1) {
      if (a.localName !== b.localName || a.namespaceURI !== b.namespaceURI) return false;
      const ac = children(a), bc = children(b);
      if (ac.length !== bc.length) return false;
      for (let index = 0; index < ac.length; index++) pairs.push([ac[index], bc[index]]);
    } else if (a.nodeType === 1 || b.nodeType === 1 || a.textContent !== b.textContent) return false;
  }
  return true;
}

function uniqueAnchor(document, anchor) {
  const matches = Array.from(document.querySelectorAll('[id]')).filter(node => node.getAttribute('id') === anchor);
  if (matches.length !== 1) throw Error('Exact source anchor unavailable or ambiguous');
  return matches[0];
}

const nodeAtXPath = (document, xpath) => document.evaluate(xpath, document, prefix => document.documentElement.lookupNamespaceURI(prefix), 9, null).singleNodeValue;

export async function displayEpubDestination(book, rendition, destination, origin) {
  let item, sourceDocument;
  if (destination.epub_document) {
    item = spineItemForDocument(book.spine.spineItems, destination.epub_document, origin, destination.epub_occurrence);
    if (destination.epub_anchor || destination.epub_xpath) {
      const element = await item.load(book.load.bind(book));
      sourceDocument = element.ownerDocument || element;
      if (destination.epub_anchor) {
        const anchor = uniqueAnchor(sourceDocument, destination.epub_anchor);
        if (destination.epub_xpath && nodeAtXPath(sourceDocument, destination.epub_xpath) !== anchor) throw Error('Source anchor does not identify the retained node');
      }
    }
  }
  // Href lookup aliases repeated documents and percent/space filenames.
  // Numeric indices preserve the already-validated occurrence, including zero.
  const displayed = await rendition.display(item?.index);
  if (!item) return;
  const content = rendition.getContents().find(content => content.sectionIndex === item.index);
  if (displayed.index !== item.index || !content) throw Error('Exact source occurrence unavailable');
  const document = content.document;
  let node;
  if (destination.epub_anchor) {
    node = uniqueAnchor(document, destination.epub_anchor);
  } else if (destination.epub_xpath) {
    if (!unchangedBody(sourceDocument.querySelector('body'), document.body)) throw Error('Source structure changed during rendering');
    const sourceNode = nodeAtXPath(sourceDocument, destination.epub_xpath);
    node = nodeAtXPath(document, destination.epub_xpath);
    if (!sourceNode || !sourceDocument.querySelector('body').contains(sourceNode) || !document.body.contains(node)) throw Error('Exact source node unavailable');
  }
  if (destination.epub_anchor || destination.epub_xpath) {
    if (!node) throw Error('Exact source node unavailable');
    const positioned = await rendition.display(content.cfiFromNode(node));
    if (positioned.index !== item.index || !rendition.getContents().some(content => content.sectionIndex === item.index)) throw Error('Exact source occurrence unavailable');
  }
}

/* Range-backed EPUB archive. The browser fetches the ZIP central directory and
   only the members a rendered section needs, instead of the whole original.
   Each member is bounded, inflated to its declared size and CRC-checked. Any
   failure before the book is ready lets the caller use the full-download path. */
const TAIL = 262144, GAP = 1 << 20;
export const ZIP_LIMITS = Object.freeze({entries: 50000, total: 256 * 1024 ** 2, member: 32 * 1024 ** 2, directory: 16 * 1024 ** 2});
const MEDIA = {jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', webp: 'image/webp', avif: 'image/avif', svg: 'image/svg+xml', css: 'text/css', otf: 'font/otf', ttf: 'font/ttf', woff: 'font/woff', woff2: 'font/woff2'};
const unavailable = () => Error('EPUB archive unavailable');
const extension = path => {
  const name = path.slice(path.lastIndexOf('/') + 1), dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1) : '';
};

let table;
export function crc32(bytes) {
  if (!table) {
    table = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c;
    }
  }
  let crc = -1;
  for (let i = 0; i < bytes.length; i++) crc = table[(crc ^ bytes[i]) & 255] ^ (crc >>> 8);
  return (crc ^ -1) >>> 0;
}

// fetchRange(header) resolves {bytes, start, end, total}; every answer must be
// exactly the requested span of the same file.
async function exactRange(fetchRange, start, end, total) {
  const result = await fetchRange(start === undefined ? 'bytes=-' + end : `bytes=${start}-${end}`);
  const {bytes, total: size} = result;
  const first = start === undefined ? Math.max(0, size - end) : start;
  const last = start === undefined ? size - 1 : end;
  if (!(bytes instanceof Uint8Array) || !Number.isSafeInteger(size) || (total !== undefined && size !== total) ||
      result.start !== first || result.end !== last || last >= size || bytes.length !== last - first + 1) throw unavailable();
  return result;
}

export async function readZipIndex(fetchRange) {
  const tail = await exactRange(fetchRange, undefined, TAIL);
  const total = tail.total, view = new DataView(tail.bytes.buffer, tail.bytes.byteOffset, tail.bytes.byteLength);
  let eocd = -1;
  for (let p = tail.bytes.length - 22; p >= Math.max(0, tail.bytes.length - 22 - 0xffff); p--) {
    if (view.getUint32(p, true) === 0x06054b50 && p + 22 + view.getUint16(p + 20, true) === tail.bytes.length) { eocd = p; break; }
  }
  if (eocd < 0) throw unavailable();
  const count = view.getUint16(eocd + 10, true), size = view.getUint32(eocd + 12, true), offset = view.getUint32(eocd + 16, true);
  if (view.getUint16(eocd + 4, true) || view.getUint16(eocd + 6, true) || view.getUint16(eocd + 8, true) !== count ||
      count === 0xffff || size === 0xffffffff || offset === 0xffffffff || count > ZIP_LIMITS.entries ||
      size > ZIP_LIMITS.directory || offset + size !== tail.start + eocd ||
      (eocd >= 20 && view.getUint32(eocd - 20, true) === 0x07064b50)) throw unavailable();
  const directory = offset >= tail.start
    ? tail.bytes.subarray(offset - tail.start, eocd)
    : (await exactRange(fetchRange, offset, offset + size - 1, total)).bytes;
  const cd = new DataView(directory.buffer, directory.byteOffset, directory.byteLength);
  const utf8 = new TextDecoder('utf-8', {fatal: true}), entries = new Map();
  let p = 0, expanded = 0;
  for (let i = 0; i < count; i++) {
    if (p + 46 > directory.length || cd.getUint32(p, true) !== 0x02014b50) throw unavailable();
    const flags = cd.getUint16(p + 8, true), method = cd.getUint16(p + 10, true);
    const compressed = cd.getUint32(p + 20, true), length = cd.getUint32(p + 24, true);
    const nameLength = cd.getUint16(p + 28, true), next = p + 46 + nameLength + cd.getUint16(p + 30, true) + cd.getUint16(p + 32, true);
    const local = cd.getUint32(p + 42, true), raw = directory.slice(p + 46, p + 46 + nameLength);
    if (next > directory.length || flags & 0x41 || (method !== 0 && method !== 8) || cd.getUint16(p + 34, true) ||
        compressed === 0xffffffff || length === 0xffffffff || local === 0xffffffff ||
        (method === 0 && compressed !== length) || length > ZIP_LIMITS.member ||
        (!(flags & 0x800) && raw.some(byte => byte > 0x7f))) throw unavailable();
    const name = utf8.decode(raw);
    expanded += length;
    if (entries.has(name) || expanded > ZIP_LIMITS.total) throw unavailable();
    entries.set(name, {name, raw, method, crc: cd.getUint32(p + 16, true), compressed, length, offset: local});
    p = next;
  }
  if (p !== directory.length) throw unavailable();
  // Members may not share or overlap a local region; each ends before the next.
  const ordered = [...entries.values()].sort((a, b) => a.offset - b.offset);
  ordered.forEach((entry, i) => {
    entry.limit = i + 1 < ordered.length ? ordered[i + 1].offset : offset;
    if (entry.offset + 30 + entry.raw.length + entry.compressed > entry.limit) throw unavailable();
  });
  return {total, entries, tail, fetchRange};
}

async function inflate(entry, region) {
  const view = new DataView(region.buffer, region.byteOffset, region.byteLength);
  if (region.length < 30 || view.getUint32(0, true) !== 0x04034b50 || view.getUint16(6, true) & 0x41 ||
      view.getUint16(8, true) !== entry.method || view.getUint16(26, true) !== entry.raw.length) throw unavailable();
  const start = 30 + entry.raw.length + view.getUint16(28, true), end = start + entry.compressed;
  if (end > region.length || entry.raw.some((byte, i) => region[30 + i] !== byte)) throw unavailable();
  let out;
  if (entry.method === 0) out = region.slice(start, end);
  else {
    out = new Uint8Array(entry.length);
    const reader = new Blob([region.subarray(start, end)]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
    let length = 0;
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      if (length + value.length > out.length) { reader.cancel().catch(() => {}); throw unavailable(); }
      out.set(value, length); length += value.length;
    }
    if (length !== out.length) throw unavailable();
  }
  if (crc32(out) !== entry.crc) throw unavailable();
  return out;
}

/* Duck-typed replacement for EPUB.js's JSZip archive: request/getText/getBlob/
   createUrl/revokeUrl/destroy, with the same "File not found" rejection shape. */
export class RangeArchive {
  constructor(index) {
    this.index = index;
    this.members = new Map(); this.converted = new Set(); this.urls = new Map(); this.urlCache = {}; this.blobs = new Set();
    // The first member failure; callers fall back to the full download.
    this.failed = new Promise((_, reject) => { this.fail = error => { this.error ??= error; reject(error); }; });
    this.failed.catch(() => {});
  }
  name(url) {
    try { return decodeURIComponent(String(url).slice(1)); } catch { return undefined; }
  }
  has(url) { return this.index.entries.has(this.name(url)); }
  // Fetch every not-yet-requested member in as few coalesced ranges as possible.
  prefetch(names) {
    const {entries, tail, total} = this.index;
    const wanted = [...new Set(names)].filter(name => entries.has(name) && !this.members.has(name) && !this.converted.has(name))
      .map(name => entries.get(name)).sort((a, b) => a.offset - b.offset);
    const groups = [];
    for (const entry of wanted) {
      const start = entry.offset, end = Math.min(entry.limit, start + 30 + 2 * 0xffff + entry.compressed);
      const last = groups.at(-1);
      if (start >= tail.start) groups.push({start: tail.start, end: total, entries: [entry], held: true});
      else if (last && !last.held && start - last.end <= GAP) { last.end = Math.max(last.end, end); last.entries.push(entry); }
      else groups.push({start, end, entries: [entry]});
    }
    for (const group of groups) {
      const bytes = group.held ? Promise.resolve(tail.bytes)
        : exactRange(this.index.fetchRange, group.start, group.end - 1, total).then(result => result.bytes);
      for (const entry of group.entries) {
        const member = bytes.then(data => inflate(entry, data.subarray(entry.offset - group.start, entry.limit - group.start)));
        member.catch(error => {
          if (this.members.get(entry.name) === member) this.members.delete(entry.name);
          this.fail(error);
        });
        this.members.set(entry.name, member);
      }
    }
  }
  bytes(url) {
    const name = this.name(url);
    if (this.destroyed || !this.index.entries.has(name)) return undefined;
    this.converted.delete(name);
    this.prefetch([name]);
    return this.members.get(name);
  }
  getText(url) {
    return this.bytes(url)?.then(bytes => new TextDecoder().decode(bytes));
  }
  getBlob(url, type) {
    const name = this.name(url);
    return this.bytes(url)?.then(bytes =>
      new Blob([bytes], {type: type || MEDIA[extension(name).toLowerCase()] || 'application/octet-stream'}));
  }
  request(url, type) {
    type ||= extension(String(url));
    const pending = type === 'blob' ? this.getBlob(url) : this.getText(url);
    if (!pending) return Promise.reject({message: 'File not found in the epub: ' + url, stack: Error().stack});
    return pending.then(result => {
      if (type === 'json') return JSON.parse(result);
      if (this.utils.isXml(type)) return this.utils.parse(result, 'text/xml');
      if (type === 'xhtml') return this.utils.parse(result, 'application/xhtml+xml');
      if (type === 'html' || type === 'htm') return this.utils.parse(result, 'text/html');
      return result;
    });
  }
  blobUrl(blob) {
    if (this.destroyed) throw unavailable();
    const url = URL.createObjectURL(blob);
    this.blobs.add(url);
    return url;
  }
  createUrl(url) {
    if (!this.urls.has(url)) {
      const blob = this.getBlob(url);
      if (!blob) return Promise.reject({message: 'File not found in the epub: ' + url, stack: Error().stack});
      const created = blob.then(value => {
        // The blob holds the bytes; keep no second decompressed copy.
        const name = this.name(url);
        this.members.delete(name); this.converted.add(name);
        return (this.urlCache[url] = this.blobUrl(value));
      });
      created.catch(() => { if (this.urls.get(url) === created) this.urls.delete(url); });
      this.urls.set(url, created);
    }
    return this.urls.get(url);
  }
  revokeUrl(url) {
    const value = this.urlCache[url];
    if (value) { URL.revokeObjectURL(value); this.blobs.delete(value); delete this.urlCache[url]; this.urls.delete(url); }
  }
  destroy() {
    this.destroyed = true;
    for (const url of this.blobs) URL.revokeObjectURL(url);
    this.blobs.clear(); this.members.clear(); this.converted.clear(); this.urls.clear(); this.urlCache = {};
  }
}

// EPUB.js's substitute(): replace each relative asset path, skipping missing ones.
function substitute(text, relative, replacements) {
  relative.forEach((url, i) => {
    if (url && replacements[i]) text = text.replace(new RegExp(url.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&'), 'g'), replacements[i]);
  });
  return text;
}

/* Open an EPUB.js Book over the range archive. Replacing every asset up front,
   as EPUB.js does, would fetch all images; this replaces them per section, as
   that section is serialized, with the same relative-path substitution. */
export async function openRangeEpub(ePub, archive, prefetch = []) {
  const book = new ePub.Book({});
  const assets = new Map();
  archive.utils = ePub.utils;
  const assetUrl = i => {
    if (!assets.has(i)) {
      const resources = book.resources, href = resources.urls[i], absolute = resources.settings.resolver(href);
      let pending;
      if (!archive.has(absolute)) pending = Promise.resolve(null);
      else if (resources.assets[i].type !== 'text/css') pending = archive.createUrl(absolute);
      else if (href.startsWith('/')) pending = Promise.resolve(null);
      else pending = archive.getText(absolute).then(async css => {
        // Nested stylesheets keep their raw bytes, as in EPUB.js.
        const relative = resources.relativeTo(absolute), replacements = [];
        await Promise.all(present(css, relative).map(async j => {
          replacements[j] = resources.assets[j].type === 'text/css'
            ? archive.has(resources.settings.resolver(resources.urls[j])) && await archive.createUrl(resources.settings.resolver(resources.urls[j]))
            : await assetUrl(j);
        }));
        return archive.blobUrl(new Blob([substitute(css, relative, replacements)], {type: 'text/css'}));
      });
      pending = pending.then(url => (resources.replacementUrls[i] = url));
      pending.catch(() => { if (assets.get(i) === pending) assets.delete(i); });
      assets.set(i, pending);
    }
    return assets.get(i);
  };
  const present = (text, relative) => {
    const found = relative.flatMap((url, i) => url && text.includes(url) ? [i] : []);
    archive.prefetch(found.filter(i => !assets.has(i)).map(i => archive.name(book.resources.settings.resolver(book.resources.urls[i]))));
    return found;
  };
  book.unarchive = () => { book.archive = archive; return Promise.resolve(); };
  book.replacements = () => {
    book.spine.hooks.serialize.register(async (output, section) => {
      const relative = book.resources.relativeTo(section.url);
      await Promise.all(present(output, relative).map(assetUrl));
      section.output = substitute(output, relative, book.resources.replacementUrls);
    });
    return Promise.resolve();
  };
  archive.prefetch(prefetch);
  try {
    await Promise.race([book.open(new ArrayBuffer(0)), archive.failed]);
    await Promise.race([book.ready, archive.failed]);
  } catch (error) {
    try { book.destroy(); } catch {}
    throw error;
  }
  return book;
}

// Members EPUB.js requests before the first page, plus the destination document.
export function openingMembers(index, document) {
  return [...index.entries.keys()].filter(name =>
    name === 'META-INF/container.xml' || name === 'META-INF/com.apple.ibooks.display-options.xml' ||
    name === document || /\.(?:opf|ncx|css|otf|ttf|woff2?)$/i.test(name) ||
    /(?:^|\/)[^/]*(?:nav|toc)[^/]*\.x?html?$/i.test(name));
}
