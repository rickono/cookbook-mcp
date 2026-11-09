/* Run against scripts/preview_reader.py, using invented books only.
   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node scripts/verify_original_reader.mjs */
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,channel:'chrome'});
try {
 const page=await browser.newPage({viewport:{width:1200,height:900}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:8766/reader/login');
 await page.waitForURL('**/reader/catalog');
 assert.match(await page.locator('.preview-banner').textContent(),/Local preview/);
 let laterAt;
 await page.route('**/reader/book-info?*',async route=>{
   const response=await route.fetch(); const data=await response.json();
   const loc=JSON.parse(Buffer.from(new URL(route.request().url()).searchParams.get('at'),'base64url').toString());
   if(data.format==='EPUB' && !loc.section_id && !loc.target_id){
     if(loc.contents_offset===30){
       data.contents=[{title:'Later contents pagination check',at:laterAt}];data.next_contents=null;
     }else{
       laterAt=data.contents[1].at;
       data.contents=[...data.contents,...Array.from({length:27},(_,i)=>({title:'Synthetic contents '+(i+4),at:data.contents[0].at}))];
       data.next_contents=Buffer.from(JSON.stringify({...loc,contents_offset:30})).toString('base64url');
     }
   }
   await route.fulfill({response,json:data});
 });
 await page.getByRole('link',{name:'The Weeknight Table',exact:false}).first().click();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
 assert.equal(new URL(page.url()).pathname,'/reader/book-view');
 await page.locator('.book-contents summary').click();
 await page.getByRole('button',{name:'More contents',exact:true}).click();
 await page.getByRole('link',{name:'Later contents pagination check',exact:true}).waitFor();
 await page.locator('.book-contents summary').click();
 await page.unroute('**/reader/book-info?*');
 let frame=page.frames().find(frame=>frame.parentFrame());
 assert.ok(frame,'Original EPUB iframe missing');
 assert.equal(await frame.locator('h1').textContent(),'Lemony white beans with greens');
 assert.equal(await frame.locator('body').evaluate(el=>getComputedStyle(el).color),'rgb(36, 63, 50)','Publisher stylesheet did not load');
 assert.equal(await frame.frameElement().then(el=>el.getAttribute('sandbox')),'allow-same-origin');
 let downloads=0; page.on('request',r=>{if(new URL(r.url()).pathname==='/reader/source')downloads++;});
 await page.locator('.book-contents summary').click();
 await page.getByRole('navigation',{name:'Book contents'}).getByRole('link',{name:'Green herb sauce',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]').textContent==='');
 await page.waitForFunction(()=>document.querySelector('iframe')?.contentDocument.querySelector('h1')?.textContent==='Green herb sauce');
 assert.equal(downloads,0,'A contents jump downloaded the book again');
 await page.waitForFunction(()=>document.querySelector('#personal-status')?.textContent==='Saved durably.');
 let personal=await page.evaluate(()=>fetch('/reader/personal').then(r=>r.json()));
 const resume=personal.resume.find(item=>item.book_id==='weeknight');
 assert.equal(JSON.parse(Buffer.from(resume.at,'base64url').toString()).section_id,'weeknight-1');
 await page.locator('.book-places > summary').click();
 await page.locator('#bookmark-save').locator('..').locator('summary').click();
 await page.locator('#bookmark-save input').fill('Council source bookmark');
 await page.getByRole('button',{name:'Save bookmark',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#personal-status')?.textContent==='Saved durably.');
 personal=await page.evaluate(()=>fetch('/reader/personal').then(r=>r.json()));
 const saved=personal.bookmarks.find(item=>item.name==='Council source bookmark');
 assert.ok(saved);
 assert.equal(JSON.parse(Buffer.from(saved.at,'base64url').toString()).section_id,'weeknight-1');
 await page.evaluate(async id=>{
   const csrf=(await (await fetch('/reader/session')).json()).csrf;
   const result=await fetch('/reader/personal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'remove',bookmark_id:id,operation_id:crypto.randomUUID().replaceAll('-',''),csrf})});
   if(!result.ok)throw Error('Synthetic bookmark cleanup failed');
 },saved.bookmark_id);
 await page.locator('.book-places > summary').click();
 for(const width of [390,320]) {
   await page.setViewportSize({width,height:844});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.locator('.book-contents summary').click();
   const menu=await page.getByRole('navigation',{name:'Book contents'}).boundingBox();
   assert.ok(menu.x>=0 && menu.x+menu.width<=width);
   await page.locator('.book-contents summary').click();
 }
 // Invented hostile EPUB verifies that publisher content cannot execute scripts
 // or make external requests, while its embedded image still renders.
 const altered=await page.evaluate(async () => {
   const at=new URL(location.href).searchParams.get('at');
   const bytes=await (await fetch('/reader/source?'+new URLSearchParams({at}))).arrayBuffer();
   const zip=await window.JSZip.loadAsync(bytes);
   for(const file of Object.values(zip.files).filter(file=>file.name.endsWith('.xhtml'))) {
     const html=await file.async('string');
     zip.file(file.name,html.replace('</body>',`<script>parent.__sourceExecuted=true</script><img src="https://outside.invalid/book-image" onerror="parent.__sourceExecuted=true"/><img data-fixture="image" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1sAAAAASUVORK5CYII="/></body>`));
   }
   return Array.from(await zip.generateAsync({type:'uint8array'}));
 });
 let escaped=false;
 await page.route('https://outside.invalid/**',route=>{escaped=true;route.abort();});
 await page.route('**/reader/source?*',route=>route.fulfill({body:Buffer.from(altered),contentType:'application/epub+zip'}));
 await page.reload();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
 frame=page.frames().find(frame=>frame.parentFrame());
 await frame.locator('img[data-fixture]').evaluate(image=>image.decode());
 assert.equal(await frame.locator('img[data-fixture]').evaluate(image=>image.naturalWidth),1);
 assert.equal(await page.evaluate(()=>window.__sourceExecuted),undefined);
 assert.equal(escaped,false,'Publication made an external request');
 assert.equal(await frame.frameElement().then(el=>el.getAttribute('sandbox')),'allow-same-origin');
 await page.unroute('**/reader/source?*');
 // Exercise actual EPUB.js archive paths with nested/same-name and encoded entries.
 const pathArchive=await page.evaluate(async()=>{
   const zip=new window.JSZip();
   zip.file('mimetype','application/epub+zip');
   zip.file('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
   zip.file('OEBPS/book.opf','<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">paths</dc:identifier><dc:title>Source path fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="a" href="../part1/intro.xhtml" media-type="application/xhtml+xml"/><item id="b" href="../intro.xhtml" media-type="application/xhtml+xml"/><item id="c" href="Text/Part%201.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/><itemref idref="c"/></spine></package>');
   for(const [path,title] of [['part1/intro.xhtml','Nested source chapter'],['intro.xhtml','Root source chapter'],['OEBPS/Text/Part 1.xhtml','Encoded source chapter']]){
     zip.file(path,'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>'+title+'</title></head><body><h1 id="start">'+title+'</h1><p>Invented source for path checks.</p></body></html>');
   }
   return Array.from(await zip.generateAsync({type:'uint8array'}));
 });
 let requestedDocument='intro.xhtml';
 await page.route('**/reader/source?*',route=>route.fulfill({body:Buffer.from(pathArchive),contentType:'application/epub+zip'}));
 await page.route('**/reader/book-info?*',async route=>{
   const response=await route.fetch();const data=await response.json();
   data.epub_document=requestedDocument;data.epub_anchor='start';delete data.epub_xpath;delete data.epub_occurrence;
   await route.fulfill({response,json:data});
 });
 for(const [document,title] of [['intro.xhtml','Root source chapter'],['OEBPS/Text/Part 1.xhtml','Encoded source chapter']]){
   requestedDocument=document;await page.reload();
   await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
   const currentFrame=page.frames().find(frame=>frame.parentFrame());
   assert.equal(await currentFrame.locator('h1').textContent(),title);
 }
 await page.unroute('**/reader/source?*');await page.unroute('**/reader/book-info?*');
 // Exercise the production display handoff, including repeated occurrences and
 // href aliases that EPUB.js itself maps to the same lookup key.
 const edgeArchive=await page.evaluate(async()=>{
   const zip=new window.JSZip();
   zip.file('mimetype','application/epub+zip');
   zip.file('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
   zip.file('book.opf','<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">destination-edges</dc:identifier><dc:title>Destination fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="same" href="same.xhtml" media-type="application/xhtml+xml"/><item id="middle" href="middle.xhtml" media-type="application/xhtml+xml"/><item id="percent" href="100%2520coverage.xhtml" media-type="application/xhtml+xml"/><item id="space" href="100%20coverage.xhtml" media-type="application/xhtml+xml"/><item id="split" href="split.xhtml" media-type="application/xhtml+xml"/><item id="valid" href="valid.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="same"/><itemref idref="middle"/><itemref idref="same"/><itemref idref="percent"/><itemref idref="space"/><itemref idref="split"/><itemref idref="valid"/></spine></package>');
   const documents={
     'same.xhtml':'<h1 id="start">Repeated source chapter</h1><p>First or third occurrence.</p>',
     'middle.xhtml':'<h1 id="start">Middle source chapter</h1>',
     '100%20coverage.xhtml':'<h1 id="start">Literal percent chapter</h1>',
     '100 coverage.xhtml':'<h1 id="start">Space chapter</h1>',
     'split.xhtml':['A','B','C','D'].map(name=>'<h2>Recipe '+name+' target</h2><p>Prose '+name+'<div>Step '+name+'</div></p>').join(''),
     'valid.xhtml':'<h2>First recipe</h2>'+Array.from({length:120},(_,i)=>'<p>Source paragraph '+i+'.</p>').join('')+'<h2>Valid target</h2>',
     'dup.xhtml':'<h2 id="recipe">Recipe A</h2>'+Array.from({length:120},(_,i)=>'<p>Source paragraph '+i+'.</p>').join('')+'<h2 id="recipe">Recipe B</h2>'
   };
   const opf=await zip.file('book.opf').async('string');
   zip.file('book.opf',opf.replace('</manifest>','<item id="dup" href="dup.xhtml" media-type="application/xhtml+xml"/></manifest>').replace('</spine>','<itemref idref="dup"/></spine>'));
   for(const [path,body] of Object.entries(documents))zip.file(path,'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Destination check</title></head><body>'+body+'</body></html>');
   return Array.from(await zip.generateAsync({type:'uint8array'}));
 });
 let edgeDestination;
 await page.route('**/reader/source?*',route=>route.fulfill({body:Buffer.from(edgeArchive),contentType:'application/epub+zip'}));
 await page.route('**/reader/book-info?*',async route=>{
   const response=await route.fetch();const data=await response.json();
   delete data.epub_document;delete data.epub_anchor;delete data.epub_xpath;delete data.epub_occurrence;
   Object.assign(data,edgeDestination);
   await route.fulfill({response,json:data});
 });
 for(const anchor of ['start','']){
   edgeDestination={epub_document:'same.xhtml',epub_occurrence:0,epub_anchor:anchor};
   await page.reload();
   await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
   await page.waitForFunction(()=>!document.querySelector('[data-book-next-page]').disabled);
   assert.equal(await page.getByRole('button',{name:'Previous page',exact:true}).isDisabled(),true,'First repeated occurrence rendered at the end of the spine');
   await page.getByRole('button',{name:'Next page',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('iframe')?.contentDocument.querySelector('h1')?.textContent==='Middle source chapter');
 }
 for(const [document,occurrence,title] of [['100%20coverage.xhtml',3,'Literal percent chapter'],['100 coverage.xhtml',4,'Space chapter']]){
   edgeDestination={epub_document:document,epub_occurrence:occurrence,epub_anchor:'start'};
   await page.reload();
   await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
   assert.equal(await page.frames().find(frame=>frame.parentFrame()).locator('h1').textContent(),title);
 }
 edgeDestination={epub_document:'valid.xhtml',epub_occurrence:6,epub_xpath:'/*/*[2]/*[122]'};
 await page.reload();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
 assert.equal(await page.frames().find(frame=>frame.parentFrame()).getByRole('heading',{name:'Valid target',exact:true}).evaluate(node=>{
   const rect=node.getBoundingClientRect(), view=node.ownerDocument.defaultView;
   return rect.right>0 && rect.left<view.innerWidth && rect.bottom>0 && rect.top<view.innerHeight;
 }),true,'Valid anchorless target did not become visible');
 edgeDestination={epub_document:'split.xhtml',epub_occurrence:5,epub_xpath:'/*/*[2]/*[7]'};
 await page.reload();
 await page.waitForFunction(()=>/could not be opened/.test(document.querySelector('[data-book-status]')?.textContent));
 assert.equal(await page.frames().find(frame=>frame.parentFrame()).locator('body').evaluate(body=>body.ownerDocument.evaluate('/*/*[2]/*[7]',body.ownerDocument,null,9,null).singleNodeValue.textContent),'Step B','Malformed XHTML fixture no longer demonstrates a wrong-node XPath');
 // Both native targets and legacy anchor-only destinations must refuse an
 // ambiguous ID instead of accepting the first recipe as the requested second.
 for(const xpath of ['/*/*[2]/*[122]','']){
   edgeDestination={epub_document:'dup.xhtml',epub_occurrence:7,epub_anchor:'recipe',epub_xpath:xpath};
   await page.reload();
   await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent!=='Opening original book…');
   assert.match(await page.locator('[data-book-status]').textContent(),/could not be opened/,'Duplicate EPUB anchor was reported as a successful target');
 }
 await page.unroute('**/reader/source?*');await page.unroute('**/reader/book-info?*');
 await page.getByRole('link',{name:'Books',exact:true}).click();
 await page.getByRole('link',{name:'The Soup Notebook',exact:false}).first().click();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
 assert.equal(await page.locator('[data-book-total]').textContent(),'of 2');
 const originalWidth=await page.locator('.pdfViewer .page').first().evaluate(el=>el.getBoundingClientRect().width);
 await page.getByRole('button',{name:'Zoom in',exact:true}).click();
 await page.waitForFunction(width=>document.querySelector('.pdfViewer .page').getBoundingClientRect().width>width,originalWidth);
 const zoomedWidth=await page.locator('.pdfViewer .page').first().evaluate(el=>el.getBoundingClientRect().width);
 await page.setViewportSize({width:320,height:944});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 assert.ok(Math.abs(await page.locator('.pdfViewer .page').first().evaluate(el=>el.getBoundingClientRect().width)-zoomedWidth)<1,'Height-only resize reset the selected PDF zoom');
 assert.ok(await page.locator('.pdfViewer canvas').first().evaluate(el=>el.width>0 && el.height>0));
 await page.getByRole('button',{name:'Next page',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-page]').value==='2');
 await page.getByRole('button',{name:'Previous page',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-page]').value==='1');
 await page.locator('.book-contents summary').click();
 await page.getByRole('navigation',{name:'Book contents'}).getByRole('link',{name:'A pot for tomorrow',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-page]').value==='2');
 await page.getByRole('link',{name:'Text view',exact:true}).click();
 assert.match(await page.locator('#text').textContent(),/A bowl of soup/);
 await page.getByRole('link',{name:'Read original',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-status]')?.textContent==='');
 await page.getByRole('link',{name:'Search this book',exact:true}).click();
 assert.equal(await page.getByLabel('Look in',{exact:true}).inputValue(),'notebook');
 await page.getByLabel('Keywords',{exact:true}).fill('lentils');
 await page.getByRole('button',{name:'Search',exact:true}).click();
 await page.locator('#section-results a[href^="/reader/book-view?"]').first().click();
 await page.waitForFunction(()=>document.querySelector('.book-view') && document.querySelector('[data-book-status]').textContent==='');
 assert.equal(await page.locator('[data-book-page]').inputValue(),'1');
 await page.locator('.book-view').evaluate(el=>el.dataset.reviewIdentity='retained');
 const beforeJump=downloads;
 await page.locator('.book-contents summary').click();
 await page.getByRole('navigation',{name:'Book contents'}).getByRole('link',{name:'A pot for tomorrow',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-book-page]').value==='2');
 assert.equal(await page.locator('.book-view').getAttribute('data-review-identity'),'retained');
 assert.equal(downloads,beforeJump,'Search adapter reloaded a handled contents jump');
 await page.getByRole('button',{name:/Return to search results/}).click();
 assert.equal(await page.getByLabel('Keywords',{exact:true}).inputValue(),'lentils');
 await page.locator('#section-results a[href^="/reader/book-view?"]').first().click();
 await page.waitForFunction(()=>document.querySelector('.book-view') && document.querySelector('[data-book-status]').textContent==='');
 await page.getByRole('button',{name:/Return to search results/}).click();
 assert.deepEqual(errors,[]);
 console.log('PASS: original EPUB with publisher CSS, sandbox, source jumps without reloading, original PDF rendering/paging/page jumps, text fallback, search-and-return, hostile-book script/network isolation, desktop/390px/320px.');
}finally{await browser.close();}
