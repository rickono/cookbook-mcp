import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const scripts=['reader_session.js','reader_updates.js'].map(name=>readFileSync(new URL('../src/cookbook/'+name,import.meta.url),'utf8'));
function fixture(response) {
  let now=0, denied=false;
  const events={}, timers=[], calls=[];
  const on=(name,callback)=>{(events[name]??=[]).push(callback);};
  const notice={dataset:{},isConnected:true,children:[],append(node){this.children.push(node);},replaceChildren(){this.children=[];},setAttribute(){}};
  const main={privateContent:true,replaceChildren(){this.privateContent=false;}};
  const at=Buffer.from(JSON.stringify({publication_id:'old'})).toString('base64url');
  const location={href:'https://reader.example/reader/read?at='+at,replace(url){this.replaced=url;}};
  const document={hidden:false,addEventListener:on,dispatchEvent(event){for(const callback of events[event.type]??[])callback(event);},querySelector(selector){return {'#publication-update':notice,main}[selector]??null;},createElement(){return {};}};
  class Clock extends Date {static now(){return now;}}
  const context=vm.createContext({document,location,Date:Clock,URL,URLSearchParams,Event,AbortSignal,atob,addEventListener:on,setInterval(callback){timers.push(callback);},fetch:async url=>{
    calls.push(url.split('?')[0]);
    if(response)return await response(url);
    return {status:denied?401:200,ok:!denied,json:async()=>({current_publication_id:'old',pinned_state:'available'})};
  }});
  for(const script of scripts)vm.runInContext(script,context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  return {calls,document,main,location,advance(ms){now+=ms;},deny(){denied=true;},async fire(name){for(const callback of events[name]??[])await callback(new Event(name));await flush();},async tick(){for(const callback of timers)await callback();await flush();}};
}

test('unattended visible reader stops session and publication queries',async()=>{
  const f=fixture();
  await f.fire('pageshow');
  assert.deepEqual(f.calls.sort(),['/reader/session','/reader/updates']);
  f.advance(6*60*1000);
  await f.tick();
  assert.equal(f.calls.length,2);
});

test('overlapping return events serialize checks and retain a fresh follow-up',async()=>{
  let release, checks=0, running=0, maximum=0;
  const f=fixture(async url=>{
    if(url.startsWith('/reader/updates'))return {ok:true,status:200,json:async()=>({current_publication_id:'old'})};
    checks++;running++;maximum=Math.max(maximum,running);
    if(checks===1)await new Promise(resolve=>release=resolve);
    running--;
    return {status:checks===1?200:401};
  });
  const first=f.fire('pageshow');
  await f.fire('focus');
  assert.equal(checks,1);
  release();await first;
  assert.equal(checks,2);
  assert.equal(maximum,1);
  assert.equal(f.main.privateContent,false);
});

test('ordinary interaction keeps polling active without a request for each input',async()=>{
  const f=fixture();await f.fire('pageshow');
  f.advance(4*60*1000);
  for(let i=0;i<10;i++)await f.fire('pointerdown');
  assert.equal(f.calls.length,2);
  f.advance(2*60*1000);await f.tick();
  assert.equal(f.calls.length,4);
});

test('hidden reader does no background session or publication queries',async()=>{
  const f=fixture();f.document.hidden=true;
  await f.tick();
  assert.deepEqual(f.calls,[]);
});

for(const event of ['focus','visibilitychange','pointerdown','keydown','scroll'])test(`returning via ${event} freshly checks authorization after idle`,async()=>{
  const f=fixture();await f.fire('pageshow');
  f.advance(6*60*1000);f.deny();
  await f.fire(event);
  assert.equal(f.calls.filter(path=>path==='/reader/session').length,2);
  assert.equal(f.main.privateContent,false);
  assert.match(f.location.replaced,/^\/reader\/login\?return=/);
});
