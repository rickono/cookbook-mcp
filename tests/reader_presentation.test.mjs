import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_presentation.js', import.meta.url), 'utf8');
function fixture({stored = null, blocked = false} = {}) {
  const writes = [], attrs = {}, status = {}, text = {focus(){this.focused=true;}};
  let click;
  const button = {hidden:true,setAttribute(k,v){attrs[k]=v;},getAttribute(k){return attrs[k];},addEventListener(k,fn){click=fn;}};
  const classes = new Set();
  vm.runInNewContext(script, {
    document:{body:{classList:{toggle(k,on){on?classes.add(k):classes.delete(k);}}},querySelector(q){return {'[data-kitchen]':button,'[data-appearance-status]':status,'#text':text}[q];}},
    location:{hash:'#text'},
    localStorage:{getItem(){if(blocked)throw Error();return stored;},setItem(k,v){if(blocked)throw Error();writes.push([k,v]);}}
  });
  return {button,attrs,status,text,classes,writes,click:()=>click()};
}
test('kitchen is explicit, reversible, and stores only a visual boolean',()=>{
  const f=fixture();
  assert.equal(f.button.hidden,false);
  assert.equal(f.attrs['aria-pressed'],'false');
  f.click();
  assert.equal(f.attrs['aria-pressed'],'true');
  assert.ok(f.classes.has('kitchen'));
  assert.equal(f.status.textContent,'Kitchen mode on.');
  f.click();
  assert.equal(f.attrs['aria-pressed'],'false');
  assert.deepEqual(f.writes,[['reader-kitchen','true'],['reader-kitchen','false']]);
  assert.equal(f.text.focused,true);
});
test('visual preference survives navigation; denied storage does not disable controls',()=>{
  assert.equal(fixture({stored:'true'}).attrs['aria-pressed'],'true');
  const f=fixture({blocked:true});
  f.click();
  assert.equal(f.attrs['aria-pressed'],'true');
});
