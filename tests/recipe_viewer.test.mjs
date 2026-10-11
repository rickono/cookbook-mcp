import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const html = readFileSync(new URL('../src/cookbook/recipe_viewer.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function fixture() {
  const elements = Object.fromEntries(['root','status','expand','source','source-note'].map(id => [id, {innerHTML:'',hidden:false,setAttribute(k,v){this[k]=v;},focus(){}}]));
  const sent=[], listeners={};
  const parent={postMessage:m=>sent.push(m)};
  const window={parent,addEventListener:(n,f)=>listeners[n]=f};
  const style={};
  vm.runInNewContext(script, {window,document:{getElementById:id=>elements[id],documentElement:{style},body:{getBoundingClientRect:()=>({height:500})}},ResizeObserver:class {observe(){}}});
  return {elements,sent,listeners,window,style,send:(data,source=parent)=>listeners.message({source,data})};
}
const recipe={title:'Beans <script>alert(1)</script>',metadata:['Serves 2'],steps:[{title:'Warm beans',ingredients:['400 g beans'],method:'Warm gently.'}],source:{kind:'original',label:'Original recipe',citations:[]}};
const deliver=(f,r=recipe)=>f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{recipe:r}}});

test('renders final data as escaped text through the standard bridge',()=>{
 const f=fixture();
 assert.equal(f.sent[0].method,'ui/initialize');
 f.send({jsonrpc:'2.0',id:'recipe-init',result:{hostContext:{theme:'dark'}}});
 assert.equal(f.style.colorScheme,'dark');
 assert.ok(f.sent.some(m=>m.method==='ui/notifications/initialized'));
 deliver(f);
 assert.equal(f.elements.status.hidden,true);
 assert.match(f.elements.root.innerHTML,/400 g beans/);
 assert.match(f.elements.root.innerHTML,/&lt;script&gt;/);
 assert.ok(!f.elements.root.innerHTML.includes('<script>'));
 f.send({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:{theme:'light'}});
 assert.equal(f.style.colorScheme,'light');
});

test('compact state survives duplicate compatibility results, resets on a new recipe',()=>{
 const f=fixture(); deliver(f); f.elements.expand.onclick();
 assert.match(f.elements.root.innerHTML,/id="recipe-body" hidden/);
 f.window.openai={toolOutput:{recipe}}; f.listeners['openai:set_globals']();
 assert.match(f.elements.root.innerHTML,/id="recipe-body" hidden/);
 deliver(f,{...recipe,title:'Different beans'});
 assert.ok(!f.elements.root.innerHTML.includes('id="recipe-body" hidden'));
 f.elements.source.onclick();
 assert.equal(f.elements['source-note'].hidden,false);
 assert.equal(f.elements.source['aria-expanded'],'true');
});

test('ignores foreign messages, rejects invalid data and clears stale content on errors',()=>{
 const f=fixture();
 f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{recipe}}},{});
 assert.equal(f.elements.root.innerHTML,'');
 deliver(f);
 deliver(f,{...recipe,steps:[]});
 assert.equal(f.elements.root.innerHTML,'');
 assert.equal(f.elements.status.hidden,false);
 deliver(f);
 f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{isError:true}});
 assert.equal(f.elements.root.innerHTML,'');
});

test('book source details retain exact escaped identifiers',()=>{
 const f=fixture();
 const source={kind:'adapted',label:'Sample cookbook',note:'Less salt.',citations:[{publication_id:'publication',book_id:'book',source_id:'source',section_id:'<section>'}]};
 deliver(f,{...recipe,source});
 assert.match(f.elements.root.innerHTML,/Adapted from Sample cookbook/);
 assert.match(f.elements.root.innerHTML,/&lt;section&gt;/);
 deliver(f,{...recipe,source:{...source,citations:[]}});
 assert.equal(f.elements.root.innerHTML,'');
});

test('template stays empty until a recipe result arrives',()=>{
 assert.match(html, /id="status" role="status" hidden><\/p>/);
 const f=fixture();
 f.send({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{results:[]}}});
 assert.equal(f.elements.root.innerHTML,'');
});
