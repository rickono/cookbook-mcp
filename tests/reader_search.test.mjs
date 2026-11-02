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
function fixture() {
  const nodes={},events={},posts=[],requests=[],scroll=[];
  for(const id of ['more-scopes','search-form','search-status','fresh-search','content-results','content-status','content-more','section-results','section-status','section-more'])nodes['#'+id]=new Element();
  const form=nodes['#search-form'];form.elements={query:new Element(),book_id:new Element(),kind:new Element()};form.reset=()=>{for(const e of Object.values(form.elements))e.value='';};
  const submit=new Element('button');form.querySelector=()=>submit;
  const main=new Element('main');main.append(...Object.values(nodes));main.querySelector=()=>new Element();nodes.main=main;
  const documentEvents={};
  const document={addEventListener:(k,fn)=>documentEvents[k]=fn,dispatchEvent:e=>documentEvents[e.type]?.(e),querySelector:q=>nodes[q],createElement:t=>new Element(t),createDocumentFragment:()=>new Element('fragment')};
  const location={href:'https://reader.example/reader/search',replace(url){this.replaced=url;}};
  const results=[];
  const reading=new Element('main');reading.append(new Element('article'));
  class Parser {parseFromString(body){return body==='reading'?{querySelector:()=>reading,querySelectorAll:q=>q==='link[rel="stylesheet"][href]'?[Object.assign(new Element('link'),{href:'/reader/presentation.css'})]:[]}:{querySelectorAll:()=>[]};}}
  const fetch=async(url,options={})=>{
    requests.push([url,options]);
    if(url==='/reader/session')return {ok:true,json:async()=>({csrf:'synthetic'})};
    if(url==='/reader/catalog')return {ok:true,text:async()=>''};
    if(url.startsWith('/reader/read?'))return {ok:true,text:async()=>'reading'};
    posts.push(JSON.parse(options.body)); const data=results.shift();
    if(data instanceof Error)throw data;
    return data?.status?{status:data.status,ok:false}:{ok:true,json:async()=>data};
  };
  vm.runInNewContext(script,{document,location,fetch,Event,URL,URLSearchParams,AbortSignal,DOMParser:Parser,atob,scrollY:240,scrollTo:(...p)=>scroll.push(p),history:{replaceState(a,b,url){location.href='https://reader.example'+url;}},addEventListener:(k,fn)=>events[k]=fn});
  return {nodes,form,main,posts,results,location,scroll,events,submit:()=>form.events.submit({preventDefault(){}}),click:link=>main.events.click({target:link,preventDefault(){}})};
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
