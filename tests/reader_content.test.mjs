import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_content.js', import.meta.url), 'utf8');
function fixture(responses) {
  const callbacks = {}, chunks = [], attrs = {};
  const continuation = {href:'https://reader.example/reader/read?at=next', setAttribute(k,v){attrs[k]=v;},getAttribute(k){return attrs[k];},removeAttribute(k){delete attrs[k];}, addEventListener(k,v){callbacks[k]=v;},remove(){this.removed=true;}};
  const status = {}, text = {append(chunk){chunks.push(chunk);},replaceChildren(){chunks.length=0;}};
  const reference = {href:'https://reader.example/reader/read?at=target&back=start'};
  const location = {href:'https://reader.example/reader/read?at=start',replace(url){this.replaced=url;}};
  const document = {querySelector(q){return {'[data-next-text]':continuation,'[role="status"]':status,'#text':text,'main':text}[q];},querySelectorAll(){return [reference];},createElement(){return {focus(){this.focused=true;}};}};
  vm.runInNewContext(script,{document,location,URL,URLSearchParams,AbortSignal,history:{replaceState(a,b,url){location.href=String(url);}},fetch:async()=>{const response=responses.shift();if(response instanceof Error)throw response;return response;}});
  return {chunks,status,continuation,reference,location,click:()=>callbacks.click({preventDefault(){}})};
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
