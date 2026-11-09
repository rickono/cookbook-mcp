import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const script = readFileSync(new URL('../src/cookbook/reader_search.js',import.meta.url),'utf8');
class Element {
  constructor(tag='div') {this.tag=tag;this.childNodes=[];this.dataset={};this.events={};this.value='';this.hidden=false;}
  append(...items) {for(const item of items){if(item.parent)item.parent.childNodes=item.parent.childNodes.filter(x=>x!==item);item.parent=this;this.childNodes.push(item);}}
  prepend(item){this.childNodes.unshift(item);}
  replaceChildren(...items){this.childNodes=[];for(const item of items){if(item.tag==='fragment')this.append(...item.childNodes);else this.append(item);}}
  addEventListener(k,fn){this.events[k]=fn;}
  focus(){this.focused=true;}
  getAttribute(k){return this[k];}
  hasAttribute(k){return this[k]!==undefined;}
  closest(selector){const prefix=selector.match(/href\^="([^"]+)"/);return prefix && this.href?.replace('https://reader.example','').startsWith(prefix[1]) ? this : null;}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({sessionReplies=[], readingReply}={}) {
  const nodes={},events={},posts=[],requests=[],scroll=[];
  for(const id of ['more-scopes','search-form','search-status','fresh-search','content-results','content-status','content-more','section-results','section-status','section-more'])nodes['#'+id]=new Element();
  const form=nodes['#search-form'];form.dataset.csrf='synthetic';form.elements={query:new Element(),book_id:new Element(),kind:new Element()};form.reset=()=>{for(const e of Object.values(form.elements))e.value='';};
  const submit=new Element('button');form.querySelector=()=>submit;
  const main=new Element('main');main.append(...Object.values(nodes));main.querySelector=()=>new Element();nodes.main=main;
  const documentEvents={};
  const document={addEventListener:(k,fn)=>documentEvents[k]=fn,dispatchEvent:e=>documentEvents[e.type]?.(e),querySelector:q=>nodes[q],createElement:t=>new Element(t),createDocumentFragment:()=>new Element('fragment')};
  const location={href:'https://reader.example/reader/search',replace(url){this.replaced=url;}};
  const results=[];
  const reading=new Element('main');reading.append(new Element('article'), ...['/reader/personal.js','/reader/reports.js','https://external.example/injected.js'].map(src=>Object.assign(new Element('script'),{src,inert:true})));
  class Parser {parseFromString(body){return body==='reading'?{querySelector:()=>reading,querySelectorAll:q=>q==='link[rel="stylesheet"][href]'?[Object.assign(new Element('link'),{href:'/reader/presentation.css'})]:q==='script[src]'?reading.childNodes.filter(n=>n.tag==='script'):[]}:{querySelector:()=>null,querySelectorAll:()=>[]};}}
  const fetch=async(url,options={})=>{
    requests.push([url,options]);
    if(url==='/reader/session'){const reply=sessionReplies.shift();if(reply instanceof Error)throw reply;return reply ?? {ok:true,json:async()=>({authenticated:true,csrf:'renewed'})};}
    if(url==='/reader/catalog')return {ok:true,text:async()=>''};
    if(url.startsWith('/reader/read?'))return readingReply ? {ok:false,status:readingReply.status,text:async()=>readingReply.body} : {ok:true,text:async()=>'reading'};
    posts.push(JSON.parse(options.body)); const data=results.shift();
    if(data instanceof Error)throw data;
    return data?.status?{status:data.status,ok:false,json:async()=>data.body}:{ok:true,json:async()=>data};
  };
  vm.runInNewContext(script,{document,location,fetch,Event,URL,URLSearchParams,AbortSignal,DOMParser:Parser,atob,scrollY:240,scrollTo:(...p)=>scroll.push(p),history:{replaceState(a,b,url){location.href='https://reader.example'+url;}},addEventListener:(k,fn)=>events[k]=fn});
  return {nodes,form,main,posts,requests,results,location,scroll,events,expire:()=>document.dispatchEvent(new Event('reader-expired')),submit:()=>form.events.submit({preventDefault(){}}),click:link=>main.events.click({target:link,preventDefault(){}})};
}
const group=(results=[],next=null)=>({state:'ok',results,next,coverage:'Coverage partial; withheld material is not absent.'});
const hit=(id)=>({href:'/reader/read?at='+id,title:'Same source wording',book:'Synthetic beans',authors:['Fixture'],format:'EPUB',excerpt:'<script>literal text</script>'});
test('independent continuation retains scope, filters, publication and empty-page continuation',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='private bean query';f.form.elements.book_id.value='book-1';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('a')],2),section:group([],20)}});
 f.submit();await flush();
 assert.equal(f.posts[0].book_id,'book-1');
 assert.equal(f.nodes['#section-more'].hidden,false);
 f.results.push({publication_id:'pinned',groups:{section:group([hit('b')],null)}});
 f.nodes['#section-more'].events.click();await flush();
 assert.equal(f.posts[1].section_offset,20);assert.equal(f.posts[1].publication_id,'pinned');assert.equal(f.posts[1].query,'private bean query');
 assert.equal(f.nodes['#content-results'].childNodes.length,1);
 assert.equal(f.nodes['#section-results'].childNodes[0].childNodes[2].textContent,'<script>literal text</script>');
 assert.equal(f.nodes['#section-more'].focused,true);
 assert.equal(f.location.href,'https://reader.example/reader/search');
});
test('opening a source and returning restores the live query, results, focus and scroll without browser storage',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='private query';f.form.elements.kind.value='recipe';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('exact')]),section:{state:'excluded',results:[],next:null,coverage:'Content only'}}});
 f.submit();await flush();
 const link=f.nodes['#content-results'].childNodes[0].childNodes[0];
 f.click(link);await flush();
 assert.equal(f.main.childNodes[0].textContent,'Return to search results');
 assert.equal(f.location.href,'https://reader.example/reader/read?at=exact');
 f.main.childNodes[0].events.click();
 assert.equal(f.form.elements.query.value,'private query');assert.equal(f.form.elements.kind.value,'recipe');
 assert.equal(f.nodes['#content-results'].childNodes.length,1);assert.equal(link.focused,true);
 assert.deepEqual(f.scroll.at(-1),[0,240]);assert.equal(f.location.href,'https://reader.example/reader/search');
 f.events.pagehide();assert.equal(f.main.childNodes.length,0);assert.equal(f.form.elements.query.value,'');
});
test('failed group retries its page without discarding successful groups and expiry clears drafts',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('a')],2),section:group([hit('b')],20)}});
 f.submit();await flush();
 f.results.push({publication_id:'pinned',groups:{content:{state:'failed',coverage:'Retry explicitly'}}});
 f.nodes['#content-more'].events.click();await flush();
 assert.equal(f.nodes['#content-results'].childNodes.length,1);assert.equal(f.nodes['#section-results'].childNodes.length,1);
 assert.match(f.nodes['#content-more'].textContent,/Retry/);
 f.results.push({status:401});f.nodes['#content-more'].events.click();await flush();
 assert.equal(f.posts.at(-1).content_page,2);assert.equal(f.main.childNodes.length,0);assert.equal(f.form.elements.query.value,'');assert.equal(f.location.replaced,'/reader');
});
test('retired pinned publication offers an explicit fresh search without silently retrying',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 f.results.push({publication_id:'old',groups:{content:group([],2),section:group([],20)}});f.submit();await flush();
 f.results.push({status:410});f.nodes['#section-more'].events.click();await flush();
 assert.equal(f.posts.length,2);assert.equal(f.nodes['#fresh-search'].hidden,false);assert.match(f.nodes['#search-status'].textContent,/retired/);
 f.results.push({publication_id:'new',groups:{content:group(),section:group()}});f.nodes['#fresh-search'].events.click();await flush();
 assert.equal(f.posts.at(-1).publication_id,undefined);assert.equal(f.posts.at(-1).query,'salt');
});

test('search within the opened book retains the originating query',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('a')]),section:group()}});f.submit();await flush();
 f.click(f.nodes['#content-results'].childNodes[0].childNodes[0]);await flush();
 const scope=new Element('a');scope.href='https://reader.example/reader/search?at='+Buffer.from(JSON.stringify({book_id:'new-book'})).toString('base64url');
 f.click(scope);await flush();
 assert.equal(f.form.elements.query.value,'salt');assert.equal(f.form.elements.book_id.value,'new-book');
});

test('mounted reading carries its presentation stylesheet into the live document',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('a')]),section:group()}});f.submit();await flush();
 f.click(f.nodes['#content-results'].childNodes[0].childNodes[0]);await flush();
 assert.ok(f.main.childNodes.some(n=>n.href==='/reader/presentation.css'));
});

test('body enhancements initialize after parsed reading nodes move into the live page',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('a')]),section:group()}});f.submit();await flush();
 f.click(f.nodes['#content-results'].childNodes[0].childNodes[0]);await flush();
 const initialized=f.main.childNodes.filter(n=>n.tag==='script'&&!n.inert).map(n=>n.src);
 assert.deepEqual(initialized,['/reader/personal.js','/reader/reports.js']);
});

const ok=()=>({publication_id:'pinned',groups:{content:group([hit('a')],2),section:group([hit('b')],20)}});
const denied=()=>({status:403,body:{error:'csrf_denied'}});
test('initial, repeated, scope, type and both continuations POST directly with the page token',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';
 assert.deepEqual(f.requests.map(([url])=>url),['/reader/catalog']);
 assert.equal(f.form.dataset.csrf,undefined);
 for(const change of [()=>{},()=>{},()=>f.form.elements.book_id.value='book-2',()=>f.form.elements.kind.value='recipe']){
  change();f.results.push(ok());f.submit();await flush();
 }
 f.results.push({publication_id:'pinned',groups:{content:group([hit('c')])}});
 f.nodes['#content-more'].events.click();await flush();
 f.results.push({publication_id:'pinned',groups:{section:group([hit('d')])}});
 f.nodes['#section-more'].events.click();await flush();
 assert.equal(f.posts.length,6);assert.ok(f.posts.every(p=>p.csrf==='synthetic'));
 assert.equal(f.posts[4].content_page,2);assert.equal(f.posts[5].section_offset,20);
 assert.equal(f.posts[4].publication_id,'pinned');assert.equal(f.posts[5].publication_id,'pinned');
 assert.equal(f.posts[2].book_id,'book-2');assert.equal(f.posts[3].kind,'recipe');
 assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,0);
 assert.equal(f.nodes['#content-results'].childNodes.length,2);
 assert.equal(f.nodes['#section-results'].childNodes.length,2);
});
test('stale CSRF recovers once and preserves each continuation request except the token',async()=>{
 for(const name of ['content','section']){
  const f=fixture();await flush();f.form.elements.query.value='private salt';f.results.push(ok());f.submit();await flush();
  const start=f.requests.length;f.results.push(denied(),{publication_id:'pinned',groups:{[name]:group([hit('next')])}});
  f.nodes['#'+name+'-more'].events.click();await flush();
  assert.deepEqual(f.requests.slice(start).map(([u])=>u),['/reader/search/results','/reader/session','/reader/search/results']);
  assert.deepEqual({...f.posts[2],csrf:f.posts[1].csrf},f.posts[1]);assert.equal(f.posts[2].csrf,'renewed');
  assert.equal(f.posts[2].publication_id,'pinned');assert.equal(f.posts[2].group,name);
  f.results.push(ok());f.submit();await flush();assert.equal(f.posts.at(-1).csrf,'renewed');
  assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,1);
 }
});
test('initial stale token recovers, while repeated denial stops at two POSTs',async()=>{
 for(const last of [ok(),denied()]){
  const f=fixture();await flush();f.form.elements.query.value='salt';f.results.push(denied(),last);f.submit();await flush();
  assert.equal(f.posts.length,2);assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,1);
  if(last.status)assert.match(f.nodes['#search-status'].textContent,/interrupted/);
  else assert.equal(f.nodes['#content-results'].childNodes.length,1);
 }
});
test('Origin denial, malformed denial, 503, 410 and failed groups never refresh CSRF',async()=>{
 for(const response of [{status:403,body:{error:'origin_denied'}},{status:403},{status:503}, {status:410}, {publication_id:'pinned',groups:{content:{state:'failed',coverage:'Retry'},section:group()}}]){
  const f=fixture();await flush();f.form.elements.query.value='salt';f.results.push(response);f.submit();await flush();
  assert.equal(f.posts.length,1);assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,0);
 }
});
test('failed or malformed recovery cannot resend a search',async()=>{
 for(const reply of [{ok:false,status:503},new Error('network'),{ok:true,json:async()=>{throw Error();}}, ...[{}, {authenticated:false,csrf:'renewed'}, {authenticated:true,csrf:42},{authenticated:true,csrf:''},{authenticated:true,csrf:'synthetic'},{authenticated:true,csrf:'é'}].map(body=>({ok:true,json:async()=>body}))]){
  const f=fixture({sessionReplies:[reply]});await flush();f.form.elements.query.value='salt';f.results.push(denied());f.submit();await flush();
  assert.equal(f.posts.length,1);assert.match(f.nodes['#search-status'].textContent,/interrupted/);
 }
});
test('401 on either POST or recovery clears private state and never resends',async()=>{
 for(const recovery of [false,true]){
  const f=fixture({sessionReplies:[{ok:false,status:401}]});await flush();f.form.elements.query.value='salt';
  f.results.push(recovery?denied():{status:401});f.submit();await flush();
  assert.equal(f.posts.length,1);assert.equal(f.main.childNodes.length,0);assert.equal(f.form.elements.query.value,'');assert.equal(f.location.replaced,'/reader');
 }
});
test('pagehide or expiry during recovery discards the late token and prevents another POST',async()=>{
 for(const event of ['pagehide','expired']){
  let resolve;const body=new Promise(r=>resolve=r);
  const f=fixture({sessionReplies:[{ok:true,json:()=>body}]});await flush();f.form.elements.query.value='salt';f.results.push(denied());f.submit();await flush();
  if(event==='pagehide')f.events.pagehide();else f.expire();
  resolve({authenticated:true,csrf:'renewed'});await flush();f.submit();await flush();
  assert.equal(f.posts.length,1);assert.equal(f.main.childNodes.length,0);assert.equal(f.form.elements.query.value,'');
 }
});

test('expiry during denial decoding prevents refresh, and during results decoding prevents paint',async()=>{
 for(const denial of [false,true]){
  let resolve;const body=new Promise(r=>resolve=r);const f=fixture();await flush();f.form.elements.query.value='salt';
  f.results.push(denial?{status:403,body}:body);f.submit();await flush();f.expire();resolve(denial?{error:'csrf_denied'}:ok());await flush();
  assert.equal(f.posts.length,1);assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,0);
  assert.equal(f.main.childNodes.length,0);assert.equal(f.nodes['#content-results'].childNodes.length,0);
 }
});
test('expiry on the retried POST clears state without further recovery',async()=>{
 const f=fixture();await flush();f.form.elements.query.value='salt';f.results.push(denied(),{status:401});f.submit();await flush();
 assert.equal(f.posts.length,2);assert.equal(f.requests.filter(([u])=>u==='/reader/session').length,1);
 assert.equal(f.main.childNodes.length,0);assert.equal(f.location.replaced,'/reader');
});

test('search leaves already handled original-reader navigation alone',async()=>{
 const f=fixture();await flush();
 const link=new Element('a');link.href='/reader/read?at=already-handled';
 const before=f.requests.length;
 f.main.events.click({defaultPrevented:true,target:link,preventDefault(){throw Error('Already handled');}});
 await flush();
 assert.equal(f.requests.length,before);
});


test('an invalid reading response cannot detach the live search form or its results',async()=>{
 const f=fixture({readingReply:{status:404,body:'{"error":"source_location_unavailable"}'}});await flush();
 f.form.elements.query.value='retained query';
 f.results.push({publication_id:'pinned',groups:{content:group([hit('missing')]),section:group()}});
 f.submit();await flush();
 const before=f.main.childNodes.length;
 f.click(f.nodes['#content-results'].childNodes[0].childNodes[0]);await flush();
 assert.equal(f.main.childNodes.length,before);
 assert.equal(f.form.elements.query.value,'retained query');
 assert.equal(f.nodes['#content-results'].childNodes.length,1);
 assert.match(f.nodes['#search-status'].textContent,/interrupted/);
});
