import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/owner_reports.js', import.meta.url),'utf8');
function fixture(responses) {
 const events={}, sent=[], status={}, main={replaceChildren(){this.cleared=true;}}, fields={reference:'server-reference',csrf:'csrf',description:'Amount seems incomplete',proposal:'',region:''};
 const form={addEventListener(name,fn){events[name]=fn;},reset(){fields.description='';fields.proposal='';fields.region='';}};
 const location={href:'https://reader.example/reader/read?at=source',replace(url){this.redirect=url;}};
 vm.runInNewContext(script,{document:{querySelector:q=>({'#owner-report':form,'#report-status':status,main}[q]),addEventListener:(name,fn)=>{events[name]=fn;}},location,URL,URLSearchParams,AbortSignal,crypto:{randomUUID:()=> 'a'.repeat(32)},FormData:class {constructor(){return Object.entries(fields);}},fetch:async(url,options)=>{sent.push(JSON.parse(options.body));const response=responses.shift();if(response instanceof Error) throw response; return response;}});
 return {fields,status,main,location,sent,submit:()=>events.submit({preventDefault(){}}),expire:()=>events['reader-expired']()};
}
const response=(status,data)=>({ok:status===200,status,json:async()=>data});
test('ambiguous response retains draft and retries exactly the same submission before receipt',async()=>{
 const f=fixture([new Error('timeout'),response(200,{status:'received',receipt_id:'receipt'})]);
 await f.submit(); assert.match(f.status.textContent,/unconfirmed/); assert.equal(f.fields.description,'Amount seems incomplete');
 await f.submit(); assert.deepEqual(f.sent[0],f.sent[1]); assert.match(f.status.textContent,/Received, not verified/); assert.equal(f.fields.description,'');
});
test('rate limit and unavailable preserve live draft; changed payload is never silently resent',async()=>{
 const f=fixture([response(429,{error:'rate_limited'}),response(503,{error:'reporting_unavailable'})]);
 await f.submit(); assert.match(f.status.textContent,/Rate limit/);
 await f.submit(); assert.match(f.status.textContent,/unavailable/); assert.equal(f.fields.description,'Amount seems incomplete');
 f.fields.description='changed'; await f.submit(); assert.equal(f.sent.length,2); assert.match(f.status.textContent,/original fields/);
});
test('expiry clears protected draft and returns to sign in without resubmission',async()=>{
 const f=fixture([response(401,{})]); await f.submit();
 assert.equal(f.fields.description,''); assert.equal(f.main.cleared,true); assert.equal(f.sent.length,1); assert.equal(f.location.redirect,'/reader/login?return=source');
});
test('passive session expiry clears the draft held by the report form',async()=>{
 const f=fixture([new Error('timeout')]); await f.submit(); f.expire(); assert.equal(f.fields.description,'');
});
