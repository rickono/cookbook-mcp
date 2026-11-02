import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_original.js', import.meta.url), 'utf8');
function fixture({complete=false, width=0}={}) {
  const handlers={}, status={}, attrs={};
  let deadline, cleared=false, comparing=false;
  const image={complete,naturalWidth:width,addEventListener(k,f){handlers[k]=f;},removeAttribute(k){attrs.removed=k;}};
  const button={addEventListener(k,f){handlers.compare=f;},setAttribute(k,v){attrs[k]=v;}};
  const layout={classList:{toggle(){comparing=!comparing;return comparing;}}};
  const document={querySelector(q){return {'[data-original-image]':image,'#original-status':status,'[data-compare]':button,'.original-layout':layout}[q];}};
  vm.runInNewContext(script,{document,setTimeout(f,ms){assert.equal(ms,30000);deadline=f;return 1;},clearTimeout(){cleared=true;}});
  return {image,status,attrs,handlers,button,timeout:()=>deadline(),get cleared(){return cleared;}};
}
test('only image load with decoded dimensions announces displayed; comparison performs no new request',()=>{
 const f=fixture();
 assert.match(f.status.textContent,/Loading/);
 f.image.naturalWidth=1600;f.handlers.load();
 assert.match(f.status.textContent,/displayed/);assert.equal(f.cleared,true);
 f.handlers.compare({currentTarget:f.button});assert.equal(f.attrs['aria-pressed'],'true');
 f.handlers.compare({currentTarget:f.button});assert.equal(f.attrs['aria-pressed'],'false');
});
test('timeout terminates loading and late image delivery cannot claim success or trigger a retry',()=>{
 const f=fixture();f.timeout();
 assert.equal(f.attrs.removed,'src');assert.match(f.status.textContent,/Retry explicitly/);
 f.image.naturalWidth=1600;f.handlers.load();assert.doesNotMatch(f.status.textContent,/displayed/);
});
test('failed and cached images settle truthfully',()=>{
 const failed=fixture();failed.handlers.error();assert.match(failed.status.textContent,/unavailable/);
 const cached=fixture({complete:true,width:800});assert.match(cached.status.textContent,/displayed/);
 const empty=fixture({complete:true});assert.match(empty.status.textContent,/unavailable/);
});
