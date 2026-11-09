import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const script = fs.readFileSync('src/cookbook/reader_personal.js', 'utf8');
function harness(hidden=false) {
  const nodes = {};
  function node(id) {return nodes[id] = {dataset:{}, textContent:'', hidden:false, isConnected:true, elements:{name:{value:'Dinner'}}, handlers:{}, addEventListener(k,f){this.handlers[k]=f;}, append(){}, replaceChildren(){}, querySelectorAll(){return [];}};}
  const root=node('root'); root.dataset.at='reference';
  node('#personal-status'); node('#bookmark-save'); node('#remember-location'); node('#personal-retry');
  root.querySelector = s => nodes[s];
  const listeners={}, calls=[];
  const context={document:{visibilityState:hidden?'hidden':'visible',querySelector:()=>root,addEventListener:(k,f)=>{listeners[k]=f;},createElement:()=>node('new')}, crypto:{randomUUID:()=> '12345678-1234-1234-1234-123456789abc'}, AbortSignal, JSON, URLSearchParams, Event, location:{replace(){}}, performance:{getEntriesByType:()=>[]}, fetch:async(url,options)=>{calls.push([url,options]);return {ok:true,status:200,json:async()=>({csrf:'csrf',status:'saved',bookmarks:[]})};}};
  vm.createContext(context); vm.runInContext(script,context);
  return {context, calls, root, nodes, listeners};
}
const settle = () => new Promise(r=>setTimeout(r,10));
test('mounted reading initializes once and never saves on stale-tab focus',async()=>{
  const h=harness(true); await settle();
  assert.equal(h.calls.length,0);
  vm.runInContext(script,h.context); await settle();
  assert.equal(h.calls.length,0);
  await h.nodes['#remember-location'].handlers.click(); await settle();
  assert.equal(h.calls.filter(c=>c[1]?.method==='POST').length,1);
  assert.equal(h.nodes['#personal-status'].textContent,'Saved durably.');
});
test('expiry clears personal values and prevents late acknowledgement',async()=>{
  const h=harness(true);
  h.nodes['#bookmark-save'].elements.name.value='Private name';
  h.listeners['reader-expired']();
  assert.equal(h.nodes['#bookmark-save'].elements.name.value,'');
  assert.equal(h.root.dataset.at,'');
  await h.nodes['#remember-location'].handlers.click();
  assert.equal(h.calls.length,0);
});

test('ambiguous persistence retries frozen payload and id before durable acknowledgement',async()=>{
  const h=harness(true); let attempts=[];
  h.context.fetch=async(url,options)=>{
    if (options?.method==='POST') {attempts.push(JSON.parse(options.body)); return {ok:attempts.length>1,status:attempts.length>1?200:503,json:async()=>attempts.length>1?{status:'saved'}:{error:'persistence_unconfirmed'}};}
    return {ok:true,status:200,json:async()=>({csrf:'csrf'})};
  };
  h.nodes['#bookmark-save'].handlers.submit({preventDefault(){}}); await settle();
  assert.match(h.nodes['#personal-status'].textContent,/unconfirmed/);
  h.nodes['#bookmark-save'].elements.name.value='Changed after timeout';
  await h.nodes['#personal-retry'].handlers.click(); await settle();
  assert.deepEqual(attempts[1],attempts[0]);
  assert.equal(attempts[0].name,'Dinner');
  assert.equal(h.nodes['#personal-status'].textContent,'Saved durably.');
});

test('visible stable navigation writes once; another mounted document initializes independently',async()=>{
  const h=harness(true); // Mark a new root as the next dynamically mounted reading document.
  h.root.dataset.initialized=''; h.root.dataset.stable='true';
  h.context.document.visibilityState='visible';
  vm.runInContext(script,h.context); await settle();
  assert.equal(h.calls.filter(c=>c[1]?.method==='POST').length,1);
  vm.runInContext(script,h.context); await settle();
  assert.equal(h.calls.filter(c=>c[1]?.method==='POST').length,1);
});

test('accepted original navigation keeps the newest resume while another write is in flight',async()=>{
 const h=harness(); let release; const attempts=[];let serial=0;
 h.context.crypto.randomUUID=()=>String(++serial).padStart(32,'0');
 h.context.fetch=async(url,options)=>{
   if(options?.method==='POST'){
     attempts.push(JSON.parse(options.body));
     if(attempts.length===1)return await new Promise(resolve=>release=()=>resolve({ok:true,status:200,json:async()=>({status:'saved'})}));
     return {ok:true,status:200,json:async()=>({status:'saved'})};
   }
   return {ok:true,status:200,json:async()=>({csrf:'csrf'})};
 };
 h.root.dataset.stable='true';h.root.dataset.at='first';h.root.handlers['reader-location']();await settle();
 h.root.dataset.at='second';h.root.handlers['reader-location']();
 h.root.dataset.at='newest';h.root.handlers['reader-location']();
 release();await settle();
 assert.deepEqual(attempts.map(a=>a.at),['first','newest']);
 assert.notEqual(attempts[0].operation_id,attempts[1].operation_id);
});

test('new original navigation waits for an ambiguous write to be retried with its frozen identity',async()=>{
 const h=harness();const attempts=[];let serial=0;
 h.context.crypto.randomUUID=()=>String(++serial).padStart(32,'0');
 h.context.fetch=async(url,options)=>{
   if(options?.method==='POST'){
     attempts.push(JSON.parse(options.body));const refused=attempts.length===1;
     return {ok:!refused,status:refused?503:200,json:async()=>refused?{error:'unconfirmed'}:{status:'saved'}};
   }
   return {ok:true,status:200,json:async()=>({csrf:'csrf'})};
 };
 h.root.dataset.stable='true';h.root.dataset.at='first';h.root.handlers['reader-location']();await settle();
 h.root.dataset.at='newest';h.root.handlers['reader-location']();await settle();
 assert.equal(attempts.length,1);
 await h.nodes['#personal-retry'].handlers.click();await settle();
 assert.deepEqual(attempts[0],attempts[1]);
 assert.equal(attempts[2].at,'newest');
 assert.notEqual(attempts[2].operation_id,attempts[1].operation_id);
});

test('a source-navigation resume acknowledgement preserves the bookmark name being drafted',async()=>{
 const h=harness();h.root.dataset.stable='true';h.root.dataset.at='section';
 h.nodes['#bookmark-save'].elements.name.value='A name in progress';
 h.root.handlers['reader-location']();await settle();
 assert.equal(h.nodes['#bookmark-save'].elements.name.value,'A name in progress');
});
