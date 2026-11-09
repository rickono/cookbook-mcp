import assert from 'node:assert/strict';
import test from 'node:test';
import {spineItemForDocument, displayEpubDestination} from '../src/cookbook/reader_epub.mjs';
const origin='https://reader.example';
test('root-level EPUB chapters cannot collide with an earlier nested filename',()=>{
 const nested={index:0,href:'part1/intro.xhtml',url:'/part1/intro.xhtml'};
 const root={index:1,href:'intro.xhtml',url:'/intro.xhtml'};
 assert.equal(spineItemForDocument([nested,root],'intro.xhtml',origin),root);
});
test('encoded manifest paths match decoded archive-root paths including the OPF directory',()=>{
 const item={index:0,href:'Text/Part%201.xhtml',url:'/OEBPS/Text/Part%201.xhtml'};
 assert.equal(spineItemForDocument([item],'OEBPS/Text/Part 1.xhtml',origin),item);
 assert.throws(()=>spineItemForDocument([item],'Text/Part 1.xhtml',origin));
});
test('literal percent escapes in an archive filename are not decoded a second time',()=>{
 const item={index:0,url:'/100%2520coverage.xhtml'};
 assert.equal(spineItemForDocument([item],'100%20coverage.xhtml',origin),item);
 assert.throws(()=>spineItemForDocument([item],'100 coverage.xhtml',origin));
});
test('repeated documents require an explicitly retained occurrence',()=>{
 const a={index:0,url:'/same.xhtml'},b={index:1,url:'/same.xhtml'};
 assert.throws(()=>spineItemForDocument([a,b],'same.xhtml',origin));
 assert.equal(spineItemForDocument([a,b],'same.xhtml',origin,1),b);
 assert.throws(()=>spineItemForDocument([a,b],'other.xhtml',origin,1));
});
test('remote or invalid spine paths never become source-document matches',()=>{
 assert.throws(()=>spineItemForDocument([{url:'https://external.example/intro.xhtml'}],'intro.xhtml',origin));
 assert.throws(()=>spineItemForDocument([{href:'intro.xhtml'}],'intro.xhtml',origin));
});
test('display preserves occurrence zero rather than resolving an aliased href',async()=>{
 const first={index:0,href:'same.xhtml',url:'/same.xhtml'};
 const last={index:2,href:'same.xhtml',url:'/same.xhtml'};
 const book={spine:{spineItems:[first,last]}};
 let rendered;
 const rendition={
   display:async target=>{rendered=typeof target==='number'?target:2;return {index:rendered};},
   getContents:()=>[{sectionIndex:rendered}]
 };
 await displayEpubDestination(book,rendition,{epub_document:'same.xhtml',epub_occurrence:0},origin);
 assert.equal(rendered,0);
});
test('display refuses an engine result from a different occurrence',async()=>{
 const book={spine:{spineItems:[{index:0,url:'/same.xhtml'}]}};
 const rendition={display:async()=>({index:2}),getContents:()=>[{sectionIndex:2}]};
 await assert.rejects(displayEpubDestination(book,rendition,{epub_document:'same.xhtml',epub_occurrence:0},origin),/occurrence unavailable/);
});
test('duplicate source IDs refuse native and legacy anchor destinations before rendering',async()=>{
 const sourceDocument={querySelectorAll:()=>[{getAttribute:()=> 'recipe'},{getAttribute:()=> 'recipe'}]};
 const item={index:0,url:'/dup.xhtml',load:async()=>({ownerDocument:sourceDocument})};
 const book={spine:{spineItems:[item]},load(){}};
 let displayed=false;
 const rendition={display:async()=>{displayed=true;}};
 for(const xpath of ['/*/*[2]/*[122]','']){
   await assert.rejects(displayEpubDestination(book,rendition,{epub_document:'dup.xhtml',epub_anchor:'recipe',epub_xpath:xpath},origin),/anchor unavailable or ambiguous/);
 }
 assert.equal(displayed,false);
});
