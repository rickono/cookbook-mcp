import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_session.js', import.meta.url), 'utf8');
function fixture(response) {
  const events = {}, calls = [], buttons = [{disabled:false},{disabled:false}];
  const main = {privateContent:true,replaceChildren(){this.privateContent=false;}};
  const form = {fields:{csrf:'bound-csrf'},addEventListener(name,fn){events[name]=fn;},querySelectorAll(){return buttons;},append(node){this.status=node;}};
  const location = {href:'https://reader.example/reader/read?at=opaque',replace(url){this.replaced=url;}};
  const document = {querySelector(selector){return selector==='main'?main:form;},createElement(){return {setAttribute(){}};},dispatchEvent(event){events.expired=event.type;},addEventListener(){}};
  class FormData {constructor(target){this.fields=target.fields;}get(name){return this.fields[name];}}
  vm.runInNewContext(script,{document,location,URL,URLSearchParams,FormData,AbortSignal,Event,setInterval(fn){events.poll=fn;},addEventListener(){},fetch:async(url,options)=>{calls.push({url,options});const result=await response();if(result.ok&&!result.json)result.json=async()=>({status:'signed_out',scope:JSON.parse(options.body).scope});return result;}});
  return {calls,buttons,main,form,location,events,submit:async scope=>{assert.equal(typeof events.submit,'function','logout must intercept native no-referrer form submission');await events.submit({preventDefault(){events.prevented=true;},submitter:{value:scope}});}};
}
for (const scope of ['device','all']) test(`logout submits bound ${scope} scope privately and clears only after confirmation`,async()=>{
  const f=fixture(()=>({ok:true,status:200}));await f.submit(scope);
  assert.equal(f.events.prevented,true);assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].url,'/reader/logout');assert.equal(f.calls[0].options.method,'POST');
  const body=JSON.parse(f.calls[0].options.body);assert.equal(body.csrf,'bound-csrf');assert.equal(body.scope,scope);assert.equal(f.calls[0].options.headers['Content-Type'],'application/json');
  assert.equal(f.main.privateContent,false);assert.equal(f.events.expired,'reader-expired');assert.equal(f.location.replaced,'/reader/signed-out');
});
for (const response of [()=>({ok:false,status:403}),()=>{throw Error('offline');}]) test('unconfirmed logout retains the page and offers explicit retry without replay',async()=>{
  const f=fixture(response);await f.submit('device');assert.equal(f.calls.length,1);assert.equal(f.location.replaced,undefined);assert.equal(f.main.privateContent,true);assert.ok(f.buttons.every(b=>!b.disabled));assert.match(f.form.status.textContent,/not confirmed/);
});
test('a second submit cannot duplicate an in-flight logout',async()=>{
  let settle;const f=fixture(()=>new Promise(resolve=>settle=resolve));const first=f.submit('device');await f.submit('all');await f.events.poll();assert.equal(f.calls.length,1);settle({ok:true,status:200});await first;
});
test('session polling still clears expired source text and preserves an opaque destination',async()=>{
  const f=fixture(()=>({status:401}));await f.events.poll();assert.equal(f.main.privateContent,false);assert.equal(f.location.replaced,'/reader/login?return=opaque');
});

test('logout with an expired session clears private content without claiming confirmation',async()=>{
  const f=fixture(()=>({ok:false,status:401}));await f.submit('device');assert.equal(f.main.privateContent,false);assert.equal(f.location.replaced,'/reader');assert.equal(f.calls.length,1);
});

test('a mismatched acknowledgement cannot confirm sign-out',async()=>{
  const f=fixture(()=>({ok:true,status:200,json:async()=>({status:'signed_out',scope:'all'})}));await f.submit('device');assert.equal(f.main.privateContent,true);assert.equal(f.location.replaced,undefined);assert.match(f.form.status.textContent,/not confirmed/);
});
