import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_updates.js', import.meta.url), 'utf8');
function fixture(response) {
  const callbacks = {}, chunks = ['old text'], status = {};
  const notice = {dataset:{},children:[],append(el){this.children.push(el);},replaceChildren(){this.children=[];},setAttribute(){}};
  const continuation = {remove(){this.removed=true;}};
  const text = {replaceChildren(){chunks.length=0;}};
  const at = Buffer.from(JSON.stringify({publication_id:'old'})).toString('base64url');
  const location = {href:'https://reader.example/reader/read?at='+at,replace(url){this.replaced=url;}};
  const document = {addEventListener(k,v){callbacks[k]=v;},querySelector(q){return {'#publication-update':notice,'#text':text,'main':text,'[role="status"]':{},'[data-reading-status]':status,'[data-next-text]':continuation}[q];},createElement(){return {};}};
  vm.runInNewContext(script,{document,location,URL,URLSearchParams,AbortSignal,atob,addEventListener(k,v){callbacks[k]=v;},setInterval(){},fetch:async()=>response});
  return {notice,chunks,continuation,location,status,check:()=>callbacks['reader-check']()};
}
const ok = data => ({ok:true,status:200,json:async()=>data});
test('update notice preserves old text and explicit navigation without moving focus', async()=>{
 const f=fixture(ok({state:'available',current_publication_id:'new',at:'opaque-new'}));
 await f.check();
 assert.deepEqual(f.chunks,['old text']);
 assert.equal(f.location.replaced,undefined);
 const link=f.notice.children.at(-1);
 assert.equal(link.textContent,'Open current text');
 assert.equal(link.href,'/reader/read?at=opaque-new#text');
 await f.check();
 assert.equal(f.notice.children.at(-1),link);
});
test('withdrawal check clears delivered text and continuation and explains why', async()=>{
 const f=fixture(ok({state:'unavailable',current_publication_id:'old',at:null,pinned_state:'withheld'}));
 await f.check();
 assert.equal(f.chunks.length,0);
 assert.equal(f.continuation.removed,true);
 assert.match(f.status.textContent,/withheld/);
 assert.match(f.notice.children.map(c=>c.textContent).join(' '),/withheld/);
});
test('expired update check clears private view and retains identifier-only login return', async()=>{
 const f=fixture({status:401});
 await f.check();
 assert.equal(f.chunks.length,0);
 assert.match(f.location.replaced,/^\/reader\/login\?return=/);
});

test('update enhancement can execute for successive dynamically mounted reading documents',()=>{
 const context=vm.createContext({document:{querySelector(){return null;}},addEventListener(){},setInterval(){}});
 vm.runInContext(script,context);
 assert.doesNotThrow(()=>vm.runInContext(script,context));
});
