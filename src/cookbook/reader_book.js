(() => {
const root = document.querySelector('.book-view');
if (!root || root.dataset.initialized) return;
root.dataset.initialized = 'true';
if (location.pathname === '/reader/book') {
  const current=new URL(location.href); current.pathname='/reader/book-view';
  history.replaceState(null,'',current);
}
const status = root.querySelector('[data-book-status]');
const pageInput = root.querySelector('[data-book-page]');
const total = root.querySelector('[data-book-total]');
const previous = root.querySelector('[data-book-prev]');
const next = root.querySelector('[data-book-next-page]');
let at = root.dataset.bookAt;
let dead = false, rendition, book, pdf, loading, viewer, resize, display;
const active = () => !dead && root.isConnected;
const expire = () => {
  document.dispatchEvent(new Event('reader-expired'));
  document.querySelector('main').replaceChildren();
  location.replace('/reader/login?' + new URLSearchParams({return:at}));
};
const stop = () => {
  if (dead) return;
  dead = true;
  resize?.disconnect();
  viewer?.setDocument(null);
  book?.destroy(); loading?.destroy();
  rendition=book=pdf=loading=viewer=display=undefined;
  root.replaceChildren();
};
document.addEventListener('reader-expired', stop);
document.addEventListener('reader-unmounted', stop);
async function response(path) {
  const result = await fetch(path, {cache:'no-store',signal:AbortSignal.timeout(30000)});
  if (result.status === 401) {
    expire();
    throw Error('expired');
  }
  if (!result.ok) throw Error('unavailable');
  return result;
}
const dependency = src => new Promise((resolve,reject) => {
  const script = document.createElement('script'); script.src=src;
  script.onload=resolve; script.onerror=reject; document.head.append(script);
});
async function contents(data, append=false) {
  if (!active()) return;
  const menu = root.querySelector('.book-contents nav');
  if (!append) menu.replaceChildren();
  for (const item of data.contents) {
    const link = document.createElement(item.at ? 'a' : 'span');
    link.textContent=item.title;
    if (item.at) link.href='/reader/book-view?' + new URLSearchParams({at:item.at});
    menu.append(link);
  }
  if (data.next_contents) {
    const more=document.createElement('button'); more.textContent='More contents';
    more.addEventListener('click', async () => {
      more.disabled=true;
      try {
        const result=await response('/reader/book-info?' + new URLSearchParams({at:data.next_contents}));
        const nextData=await result.json();
        if (!active()) return;
        more.remove(); contents(nextData,true);
      } catch {if(active()){more.disabled=false; status.textContent='Contents interrupted. Try More contents again.';}}
    }); menu.append(more);
  }
}
(async () => {
  try {
    const data = await (await response('/reader/book-info?' + new URLSearchParams({at}))).json();
    if (!active()) return;
    contents(data);
    const source='/reader/source?' + new URLSearchParams({at});
    root.querySelector('.book-contents nav').addEventListener('click', async event => {
      const link=event.target.closest('a[href]');
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !display) return;
      event.preventDefault();
      const selected=new URL(link.href).searchParams.get('at');
      try {
        const destination=await (await response('/reader/book-info?' + new URLSearchParams({at:selected}))).json();
        if (!active()) return;
        if (destination.publication_id!==data.publication_id || destination.source_id!==data.source_id) throw Error('different source');
        await display(destination);
        if (!active()) return;
        const current=new URL(location.href); current.searchParams.set('at',destination.personal_at); current.hash='';
        history.replaceState(null,'',current);
        at=destination.personal_at; root.dataset.bookAt=at;
        const personal=root.querySelector('#reader-personal');
        if (personal) {
          personal.dataset.at=destination.personal_at;
          personal.dataset.stable=String(destination.personal_stable);
          personal.querySelector('#remember-location').disabled=!destination.personal_stable;
          personal.dispatchEvent(new Event('reader-location'));
          const notice=root.querySelector('#publication-update');
          if (notice) notice.dataset.at=at;
        }
        root.querySelector('a[href^="/reader/read?"]').href='/reader/read?' + new URLSearchParams({at});
        root.querySelector('.book-contents').open=false;
        status.textContent='';
      } catch {if(active()) status.textContent='This source location could not be opened. Choose another location or use Text view.';}
    });
    if (data.format === 'PDF') {
      const pdfjs = await import('/reader/vendor/pdfjs-dist/build/pdf.mjs');
      const {EventBus, PDFLinkService, PDFViewer} = await import('/reader/vendor/pdfjs-dist/web/pdf_viewer.mjs');
      if (!active()) return;
      pdfjs.GlobalWorkerOptions.workerSrc='/reader/vendor/pdfjs-dist/build/pdf.worker.mjs';
      const container=root.querySelector('.pdf-stage'); container.hidden=false;
      const events = new EventBus(), links = new PDFLinkService({eventBus:events});
      viewer = new PDFViewer({container,viewer:container.firstElementChild,eventBus:events,linkService:links,enableScripting:false});
      links.setViewer(viewer);
      loading=pdfjs.getDocument({url:source,withCredentials:true,disableStream:true,disableAutoFetch:true,isEvalSupported:false,useWasm:false,cMapUrl:'/reader/vendor/pdfjs-dist/cmaps/',cMapPacked:true,standardFontDataUrl:'/reader/vendor/pdfjs-dist/standard_fonts/'});
      pdf=await loading.promise;
      if (!active()) {pdf.destroy(); return;}
      if (data.physical_page > pdf.numPages) throw Error('source page unavailable');
      events.on('pagesinit', () => {if(active()){viewer.currentScaleValue='page-width'; viewer.currentPageNumber=data.physical_page; status.textContent='Opening page…';}});
      events.on('pagerendered', event => {if(event.error?.status===401){expire();return;} if(active() && event.pageNumber===viewer.currentPageNumber)status.textContent=event.error ? 'Page could not be rendered. Use Text view or try another page.' : '';});
      events.on('pagechanging', event => {if(active()){pageInput.value=event.pageNumber; previous.disabled=event.pageNumber===1; next.disabled=event.pageNumber===pdf.numPages;}});
      viewer.setDocument(pdf); links.setDocument(pdf);
      display=async destination => {if(destination.physical_page>pdf.numPages)throw Error('source page unavailable'); viewer.currentPageNumber=destination.physical_page;};
      pageInput.max=pdf.numPages; total.textContent='of '+pdf.numPages;
      previous.disabled=data.physical_page===1; next.disabled=data.physical_page===pdf.numPages;
      previous.onclick=() => {viewer.currentPageNumber=Math.max(1,viewer.currentPageNumber-1);};
      next.onclick=() => {viewer.currentPageNumber=Math.min(pdf.numPages,viewer.currentPageNumber+1);};
      pageInput.onchange=() => {const value=Number(pageInput.value); if(Number.isInteger(value)&&value>=1&&value<=pdf.numPages)viewer.currentPageNumber=value;};
      root.querySelector('[data-book-zoom-in]').onclick=()=>viewer.increaseScale();
      root.querySelector('[data-book-zoom-out]').onclick=()=>viewer.decreaseScale();
      let lastWidth=container.clientWidth;
      resize=new ResizeObserver(()=>{if(active() && container.clientWidth!==lastWidth){lastWidth=container.clientWidth;viewer.currentScaleValue='page-width';}}); resize.observe(container);
    } else if (data.format === 'EPUB') {
      const {displayEpubDestination}=await import('/reader/epub.js');
      if (!window.JSZip) await dependency('/reader/vendor/jszip/dist/jszip.min.js');
      if (!window.ePub) await dependency('/reader/vendor/epubjs/dist/epub.min.js');
      const bytes=await (await response(source)).arrayBuffer();
      if (!active()) return;
      book=window.ePub(bytes);
      await book.ready;
      if (!active()) return;
      const container=root.querySelector('.epub-stage'); container.hidden=false;
      rendition=book.renderTo(container,{width:'100%',height:'100%',spread:'none',allowScriptedContent:false,allowPopups:false});
      rendition.hooks.content.register(content => {
        for (const link of content.document.querySelectorAll('a[href]')) {
          if (/^(?:https?:|\/\/|mailto:|javascript:)/i.test(link.getAttribute('href'))) link.removeAttribute('href');
        }
      });
      display=destination => displayEpubDestination(book,rendition,destination,location.origin);
      await display(data);
      if (!active()) return;
      status.textContent='';
      pageInput.closest('label').hidden=true;
      root.querySelector('[data-book-zoom-in]').hidden=true;
      root.querySelector('[data-book-zoom-out]').hidden=true;
      total.textContent='Original EPUB';
      const controls=location => {if(active()){previous.disabled=location.atStart; next.disabled=location.atEnd;}};
      rendition.on('relocated',controls); controls(rendition.currentLocation());
      const turn=async direction=>{try{await rendition[direction]();}catch{if(active())status.textContent='Page unavailable. Try again or use Contents.';}};
      previous.onclick=()=>turn('prev'); next.onclick=()=>turn('next');
    } else throw Error('unsupported original');
  } catch (error) {
    if(error?.status===401){expire();return;}
    if(active()) status.textContent='The original could not be opened here. Retry this page, choose a location in Contents, or use Text view.';
  }
})();
})();
