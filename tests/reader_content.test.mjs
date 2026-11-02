import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_content.js', import.meta.url), 'utf8');
function fixture(responses) {
  const callbacks = {}, chunks = [], attrs = {};
  let mounted = true; const mount = {get isConnected(){return mounted;},replaceChildren(){chunks.length=0;}};
  const continuation = {href:'https://reader.example/reader/read?at=next', setAttribute(k,v){attrs[k]=v;},getAttribute(k){return attrs[k];},removeAttribute(k){delete attrs[k];}, addEventListener(k,v){callbacks[k]=v;},remove(){this.removed=true;}};
  const status = {}, text = {append(chunk){chunks.push(chunk);},replaceChildren(){chunks.length=0;}};
  const reference = {href:'https://reader.example/reader/read?at=target&back=start'};
  const original = {href:'https://reader.example/reader/original?at=start'};
  const location = {href:'https://reader.example/reader/read?at=start',replace(url){this.replaced=url;}};
  const document = {addEventListener(k,fn){callbacks[k]=fn;},querySelector(q){if(q==='main')return mount;return {'[data-next-text]':continuation,'[role="status"]':{},'[data-reading-status]':status,'#text':text,'main':text}[q];},querySelectorAll(q){if(q==='[data-reference-id]')return []; const links=[]; const walk=n=>{if(n.tag==='a')links.push(n);for(const c of n.children||[])walk(c);};chunks.forEach(walk); return [reference,original,...links];},createElement(tag){return {tag,children:[],attrs:{},closest(){return this.attrs['data-reference-id']?this:null;},append(child){this.children.push(child);},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;}};}};
  vm.runInNewContext(script,{document,location,URL,URLSearchParams,AbortSignal,history:{replaceState(a,b,url){location.href=String(url);}},fetch:async()=>{const response=await responses.shift();if(response instanceof Error)throw response;return response;}});
  return {chunks,status,continuation,reference,original,location,unmount:()=>{mounted=false;callbacks['reader-unmounted']?.();},expire:()=>callbacks['reader-expired']?.(),click:()=>callbacks.click({preventDefault(){}})};
}
const ok = data => ({ok:true,status:200,json:async()=>data});
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
