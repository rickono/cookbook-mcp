import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_content.js', import.meta.url), 'utf8');
function fixture(responses, observe = false) {
  const observers = [];
  class Observer {
    constructor(callback, options) { this.callback=callback; this.options=options; this.targets=new Set(); observers.push(this); }
    observe(target) { this.disconnected=false; this.targets.add(target); }
    unobserve(target) { this.targets.delete(target); }
    disconnect() { this.disconnected=true; this.targets.clear(); }
  }
  const callbacks = {}, chunks = [], attrs = {};
  let mounted = true; const mount = {get isConnected(){return mounted;},replaceChildren(){chunks.length=0;}};
  const continuation = {href:'https://reader.example/reader/read?at=next', setAttribute(k,v){attrs[k]=v;},getAttribute(k){return attrs[k];},removeAttribute(k){delete attrs[k];}, addEventListener(k,v){callbacks[k]=v;},remove(){this.removed=true;}};
  const status = {}, text = {append(chunk){chunks.push(chunk);},replaceChildren(){chunks.length=0;}};
  const reference = {href:'https://reader.example/reader/read?at=target&back=start'};
  const original = {href:'https://reader.example/reader/original?at=start'};
  const location = {href:'https://reader.example/reader/read?at=start',replace(url){this.replaced=url;}};
  const document = {addEventListener(k,fn){callbacks[k]=fn;},querySelector(q){if(q==='main')return mount;return {'[data-next-text]':continuation,'[role="status"]':{},'[data-reading-status]':status,'#text':text,'main':text}[q];},querySelectorAll(q){if(q==='[data-reference-id]')return []; const links=[]; const walk=n=>{if(n.tag==='a')links.push(n);for(const c of n.children||[])walk(c);};chunks.forEach(walk); return [reference,original,...links];},createElement(tag){return {tag,children:[],attrs:{},closest(){return this.attrs['data-reference-id']?this:null;},append(child){this.children.push(child);},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;}};}};
  vm.runInNewContext(script,{...(observe ? {IntersectionObserver:Observer} : {}),document,location,URL,URLSearchParams,AbortSignal,history:{replaceState(a,b,url){location.href=String(url);}},fetch:async()=>{const response=await responses.shift();if(response instanceof Error)throw response;return response;}});
  return {chunks,status,continuation,reference,original,location,observers,nearEnd:()=>observers[1].callback([{isIntersecting:true,target:continuation}]),enterChunk:n=>observers[0].callback([{isIntersecting:true,target:chunks[n]}]),withhold:()=>callbacks['reader-withheld']?.(),unmount:()=>{mounted=false;callbacks['reader-unmounted']?.();},expire:()=>callbacks['reader-expired']?.(),click:()=>callbacks.click({preventDefault(){}})};
}
const ok = data => ({ok:true,status:200,json:async()=>data});
test('native continuation preserves whitespace at delivery boundaries',async()=>{
 const source='\n \n\t\nChapter text\n\nIngredients';
 const f=fixture([ok({text:source,text_offset:0,next_text:null,text_blocks:[{kind:'text',text:source},{kind:'table',text:'\n  cell'}]})]);
 await f.click();
 const prose=f.chunks[0].children[0];
 assert.equal(prose.textContent,source);
 const table=f.chunks[0].children.find(c=>c.attrs.role==='region');
 assert.equal(table.children[0].textContent,'\n  cell');
});
test('interrupted continuation preserves text and explicit retry appends exactly once and restores the new origin',async()=>{
 const f=fixture([new Error('offline'),ok({state:'partial_text',text:'<script>source text</script>',text_offset:4000,next_text:'later'})]);
 await f.click();
 assert.match(f.status.textContent,/interrupted/);
 assert.equal(f.chunks.length,0);
 assert.match(f.continuation.href,/at=next/);
 await f.click();
 assert.equal(f.chunks.length,1);
 assert.equal(f.chunks[0].textContent,'<script>source text</script>');
 assert.equal(f.chunks[0].focused,true);
 assert.match(f.continuation.href,/at=later/);
 assert.match(f.location.href,/at=next#chunk-4000/);
 assert.equal(new URL(f.reference.href).searchParams.get('back'),'next');
 assert.equal(new URL(f.original.href).searchParams.get('at'),'next');
});
test('expiry clears protected content and preserves an opaque login destination',async()=>{
 const f=fixture([{status:401}]);
 f.chunks.push({textContent:'previous private text'});
 await f.click();
 assert.equal(f.chunks.length,0);
 assert.equal(f.location.replaced,'/reader/login?return=next');
});
test('current withdrawal removes already loaded chunks without advancing',async()=>{
 const f=fixture([ok({state:'withheld',text:'',next_text:null})]);
 f.chunks.push({textContent:'previous text'});
 await f.click();
 assert.equal(f.chunks.length,0);
 assert.equal(f.continuation.removed,true);
 assert.match(f.status.textContent,/withheld/);
});
test('table continuation exposes a labelled focusable region without parsing source markup',async()=>{
 const f=fixture([ok({state:'partial_text',text:'prose<svg>cell',text_offset:4000,next_text:'later',text_blocks:[{kind:'text',text:'prose'},{kind:'table',text:'<svg>cell'}],structure_notes:['Cell spans 2 rows.']})]);
 await f.click();
 assert.equal(f.chunks[0].focused,true);
 const region=f.chunks[0].children.find(c=>c.attrs.role==='region');
 assert.ok(region);
 assert.equal(region.tabIndex,0);
 assert.match(region.attrs['aria-label'],/Table/);
 assert.equal(region.children[0].textContent,'<svg>cell');
 assert.equal(f.chunks[0].children.at(-1).textContent,'Cell spans 2 rows.');
});

for (const departure of ['unmount','expire']) test(`late continuation cannot repopulate text after ${departure}`,async()=>{
 let settle;const f=fixture([new Promise(resolve=>settle=resolve)]);
 const loading=f.click();f[departure]();
 settle(ok({state:'complete_text',text:'old view text',text_offset:4000,next_text:null}));await loading;
 assert.equal(f.chunks.length,0);assert.equal(f.location.href,'https://reader.example/reader/read?at=start');
});

test('later chunks append safe authored references once, preserving source order and origin', async()=>{
 const refs=[{id:'a',label:'<img> authored',at:'target'},{id:'b',label:'Source reference: unresolved',at:null}];
 const f=fixture([ok({text:'second',text_offset:4,next_text:'later',references:refs}),ok({text:'third',text_offset:9,next_text:null,references:[...refs,{id:'c',label:'Other',at:'other'}]})]);
 await f.click();
 f.continuation.href=new URL(f.continuation.href,f.location.href).href;
 await f.click();
 const first=f.chunks[0].children.find(c=>c.attrs['aria-label']==='Authored references');
 assert.ok(first); assert.equal(first.children.length,2);
 assert.equal(first.children[0].textContent,'<img> authored');
 assert.equal(new URL(first.children[0].href).searchParams.get('back'),'next');
 assert.match(first.children[0].href,/#text$/);
 assert.equal(first.children[1].textContent,'Source reference: unresolved — target unavailable');
 const second=f.chunks[1].children.find(c=>c.attrs['aria-label']==='Authored references');
 assert.equal(second.children.length,1);
 assert.equal(new URL(second.children[0].href).searchParams.get('back'),'later');
});

test('reading preferences default to reading view and retain display preferences', () => {
  const handlers = {}, stored = new Map(), view = {dataset:{}, classList:{toggle(name,value){this[name]=value;}}};
  const control = () => ({attrs:{},addEventListener(k,fn){this[k]=fn;},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},focus(){this.focused=true;}});
  const focus=control(), smaller=control(), larger=control(), size={};
  const preferences={hidden:true,closest(){return view;},querySelector(q){return {'[data-reading-focus]':focus,'[data-text-smaller]':smaller,'[data-text-larger]':larger,'[data-text-size]':size}[q];}};
  const mount={isConnected:true};
  const document={querySelector(q){return {'main':mount,'.reading-preferences':preferences}[q];},querySelectorAll(){return [];},addEventListener(k,fn){handlers[k]=fn;}};
  vm.runInNewContext(script,{document,sessionStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)}});
  assert.equal(preferences.hidden,false);
  assert.equal(size.textContent,'100%');
  larger.click(); assert.equal(view.dataset.textSize,'115');
  assert.deepEqual([...stored], [['reader-focus-view','true'],['reader-text-size','115']]);
  for(let i=0;i<10;i++)larger.click();
  assert.equal(size.textContent,'150%'); assert.equal(larger.disabled,true);
  for(let i=0;i<10;i++)smaller.click();
  assert.equal(size.textContent,'90%'); assert.equal(smaller.disabled,true);
  assert.equal(view.classList['reading-focused'],true);
  focus.click(); assert.equal(view.classList['reading-focused'],false);
  assert.equal(focus.attrs['aria-expanded'],'true');
});


test('scrolling loads more text without moving focus or advancing the reading location early', async () => {
 const f=fixture([ok({text:' next words',text_offset:4000,next_text:'later'})],true);
 await f.nearEnd();
 assert.equal(f.chunks.length,1);
 assert.equal(f.chunks[0].textContent,' next words');
 assert.equal(f.chunks[0].focused,undefined);
 assert.equal(f.location.href,'https://reader.example/reader/read?at=start');
 f.enterChunk(0);
 assert.match(f.location.href,/at=next#chunk-4000/);
 assert.equal(new URL(f.original.href).searchParams.get('at'),'next');
 assert.equal(new URL(f.continuation.href,'https://reader.example').searchParams.get('at'),'later');
});

test('automatic failure stops fetching and an explicit retry preserves earlier text', async () => {
 const f=fixture([new Error('offline'),ok({text:'recovered',text_offset:4000,next_text:null})],true);
 await f.nearEnd();
 assert.equal(f.observers[1].disconnected,true);
 assert.match(f.status.textContent,/retry/);
 await f.click();
 assert.equal(f.chunks.length,1);
 assert.equal(f.chunks[0].focused,true);
});

test('withdrawal during an automatic read stops observers and rejects the late response', async () => {
 let settle; const f=fixture([new Promise(resolve=>settle=resolve)],true);
 const loading=f.nearEnd(); f.withhold();
 settle(ok({text:'withdrawn words',text_offset:4000,next_text:null})); await loading;
 assert.equal(f.chunks.length,0);
 assert.equal(f.observers[0].disconnected,true);
 assert.equal(f.observers[1].disconnected,true);
});

test('automatic loads are serialized while a response is pending', async () => {
 let settle; const f=fixture([new Promise(resolve=>settle=resolve)],true);
 const loading=f.nearEnd(); await f.nearEnd();
 settle(ok({text:'one copy',text_offset:4000,next_text:null})); await loading;
 assert.equal(f.chunks.length,1);
});
