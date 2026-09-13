// Synthetic host-bridge regression tests; no browser sessions or source books.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../src/cookbook/image_viewer.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function fixture() {
  const elements = Object.fromEntries(['image','status','caption','title','description','document-id','publication-id','source-id','image-id','photo-button','photo-action','context-label','source-note'].map(id => [id, {
    hidden: true, textContent: '', removeAttribute(name) { delete this[name]; },
    setAttribute(name,value) { this[name] = value; }, focus() {}, classList: {toggle() {}}
  }]));
  const listeners = {};
  const sent = [];
  const parent = {postMessage: message => sent.push(message)};
  const window = {parent, addEventListener: (name, callback) => { listeners[name] = callback; }};
  vm.runInNewContext(script, {window, document: {
    getElementById: id => elements[id], documentElement: {scrollHeight: 500}, body: {getBoundingClientRect: () => ({height:500})}
  }, ResizeObserver: class {observe() {}}});
  const send = (data, source=parent) => listeners.message({source, data});
  return {elements, sent, window, listeners, send};
}
const metadata = {citation:{title:'Synthetic cookbook'}, caption:'<img src=x onerror=alert(1)>', image_id:'sample'};
const image = {data:'/9j/AA==', mimeType:'image/jpeg', metadata};

test('standard bridge initializes and displays only after successful image load', () => {
  const f = fixture();
  assert.equal(f.sent[0].method, 'ui/initialize');
  f.send({jsonrpc:'2.0', id:'cookbook-init', result:{}});
  assert.equal(f.sent[1].method, 'ui/notifications/initialized');
  f.send({jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{_meta:{cookbookImage:image}}});
  assert.equal(f.elements.image.src, 'data:image/jpeg;base64,/9j/AA==');
  assert.equal(f.elements.image.hidden, true);
  f.elements.image.onload();
  assert.equal(f.elements.image.hidden, false);
  assert.equal(f.elements.title.textContent, metadata.caption);
  assert.equal(f.elements.description.textContent, 'Synthetic cookbook');
});

test('ChatGPT metadata-only compatibility delivery preserves the citation', () => {
  const f = fixture();
  f.window.openai = {toolResponseMetadata:{cookbookImage:image}};
  f.listeners['openai:set_globals']();
  assert.equal(f.elements.title.textContent, metadata.caption);
});

test('ignores non-parent messages and rejects external or invalid image sources', () => {
  const f = fixture();
  const message = {jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{_meta:{cookbookImage:image}}};
  f.send(message, {});
  assert.equal(f.elements.image.src, undefined);
  for (const invalid of [{...image,data:'https://example.com/private.jpg'}, {...image,mimeType:'image/svg+xml'}]) {
    f.send({...message,params:{_meta:{cookbookImage:invalid}}});
    assert.equal(f.elements.image.src, undefined);
    assert.equal(f.elements.status.hidden, false);
  }
});


test('photo expands on activation and Escape returns to the compact preview', () => {
  const f = fixture();
  const button = f.elements['photo-button'];
  button.onclick();
  assert.equal(button['aria-expanded'], 'true');
  assert.equal(button.title, 'Show smaller preview');
  f.listeners.keydown({key:'Escape'});
  assert.equal(button['aria-expanded'], 'false');
  assert.equal(button.title, 'View full photo');
});


test('uses nearby recipe context without claiming it describes the photo', () => {
  const f = fixture();
  const payload = {...image, metadata:{citation:metadata.citation, caption:'', recipe_context:{title:'Bean stew'}}};
  f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{_meta:{cookbookImage:payload}}});
  assert.equal(f.elements.title.textContent, 'Bean stew');
  assert.equal(f.elements['context-label'].textContent, 'Nearby recipe');
  assert.match(f.elements['source-note'].textContent, /not a verified description/);
  assert.equal(f.elements.image.alt, 'Photo from Synthetic cookbook');
  // Metadata may change while the image bytes stay the same.
  f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{_meta:{cookbookImage:{...payload,metadata:{citation:metadata.citation}}}}});
  assert.equal(f.elements.title.textContent, 'Cookbook photo');
  assert.equal(f.elements['context-label'].textContent, '');
});
