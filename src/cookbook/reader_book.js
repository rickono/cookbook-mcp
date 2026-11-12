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
let dead = false, rendition, book, pdf, loading, viewer, resize, display, archive;
// Aborts source ranges still in flight when the reader is left.
const sources = new AbortController();
const active = () => !dead && root.isConnected;
const expire = () => {
  document.dispatchEvent(new Event('reader-expired'));
  document.querySelector('main').replaceChildren();
  location.replace('/reader/login?' + new URLSearchParams({return:at}));
};
const stop = () => {
  if (dead) return;
  dead = true;
  sources.abort();
  resize?.disconnect();
  viewer?.setDocument(null);
  book?.destroy(); loading?.destroy(); archive?.destroy();
  rendition=book=pdf=loading=viewer=display=archive=undefined;
  root.replaceChildren();
};
document.addEventListener('reader-expired', stop);
document.addEventListener('reader-unmounted', stop);
// AbortSignal.any is missing before Safari 17.4; keep the timeout either way.
function either(signals) {
  if (AbortSignal.any) return AbortSignal.any(signals);
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) controller.abort(signal.reason);
    else signal.addEventListener('abort', () => controller.abort(signal.reason), {once:true});
  }
  return controller.signal;
}
async function response(path, {headers, signal} = {}) {
  const timeout = AbortSignal.timeout(30000);
  const result = await fetch(path, {cache:'no-store', headers, signal: signal ? either([timeout, signal]) : timeout});
  if (result.status === 401) {
    expire();
    throw Error('expired');
  }
  if (!result.ok) throw Object.assign(Error('unavailable'), {transient: result.status >= 500});
  return result;
}
// Ordered classic scripts: both download at once, then run in insertion order.
const dependency = src => new Promise((resolve,reject) => {
  const script = document.createElement('script'); script.src=src; script.async=false;
  script.onload=resolve; script.onerror=reject; document.head.append(script);
});
// Viewers measure an absolutely positioned stage. When search adopts this view,
// book.css arrives with it and does not apply until its @import loads; a parsed
// link.sheet is not enough. Wait (bounded) for the stage layout itself.
const styled = async stage => {
  for (let i = 0; i < 250 && getComputedStyle(stage).position !== 'absolute'; i++)
    await new Promise(resolve => setTimeout(resolve, 20));
};
// One exact byte range of the original; anything but that span is refused.
// pdf.js never asks for a failed range again, so network errors, timeouts and
// server errors are retried twice before the range fails.
async function fetchRange(path, header) {
  for (let attempt = 1; ; attempt++) {
    try { return await rangeOnce(path, header); }
    catch (error) {
      const transient = error?.transient || error instanceof TypeError || error?.name === 'TimeoutError';
      if (attempt === 3 || !transient || sources.signal.aborted) throw error;
      await new Promise(resolve => setTimeout(resolve, 250 * attempt));
    }
  }
}
async function rangeOnce(path, header) {
  const result = await response(path, {headers:{Range:header}, signal:sources.signal});
  const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(result.headers.get('Content-Range') || '');
  if (result.status !== 206 || !match) {
    result.body?.cancel().catch(() => {});
    throw Error('unavailable');
  }
  const [start, end, size] = match.slice(1).map(Number);
  const bytes = new Uint8Array(await result.arrayBuffer());
  if (!(start <= end && end < size) || bytes.length !== end - start + 1) throw Error('unavailable');
  return {bytes, start, end, total:size};
}
// The page carries the opening's book-info; later navigation fetches it.
function inlineInformation() {
  const element = root.querySelector('script[data-book-info]');
  if (!element) return undefined;
  element.remove();
  try { return JSON.parse(element.textContent); } catch { return undefined; }
}
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
    const data = inlineInformation() || await (await response('/reader/book-info?' + new URLSearchParams({at}))).json();
    if (!active()) return;
    contents(data);
    const source='/reader/source?' + new URLSearchParams({at});
    const range = header => fetchRange(source, header);
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
      // The header and the trailer/xref are needed first; fetch both while
      // pdf.js loads, then hand pdf.js exact ranges as it asks for them.
      const CHUNK = 524288, head = range('bytes=0-' + (CHUNK - 1)), tail = range('bytes=-' + CHUNK);
      head.catch(() => {}); tail.catch(() => {});
      const pdfjs = await import('/reader/vendor/pdfjs-dist/build/pdf.mjs');
      const {EventBus, PDFLinkService, PDFViewer} = await import('/reader/vendor/pdfjs-dist/web/pdf_viewer.mjs');
      const container=root.querySelector('.pdf-stage');
      await styled(container);
      if (!active()) return;
      pdfjs.GlobalWorkerOptions.workerSrc='/reader/vendor/pdfjs-dist/build/pdf.worker.mjs';
      container.hidden=false;
      const events = new EventBus(), links = new PDFLinkService({eventBus:events});
      viewer = new PDFViewer({container,viewer:container.firstElementChild,eventBus:events,linkService:links,enableScripting:false});
      links.setViewer(viewer);
      const options={rangeChunkSize:CHUNK,disableStream:true,disableAutoFetch:true,isEvalSupported:false,useWasm:false,cMapUrl:'/reader/vendor/pdfjs-dist/cmaps/',cMapPacked:true,standardFontDataUrl:'/reader/vendor/pdfjs-dist/standard_fonts/'};
      let first, rangeFailed;
      try {first=await head;} catch (error) {if(error?.message==='expired' || !active()) throw error;}
      if (!active()) return;
      if (first) {
        const last=await tail.then(last => last.total===first.total && last.end===last.total-1 ? last : undefined, error => {if(error?.message==='expired') throw error;});
        const transport=new pdfjs.PDFDataRangeTransport(first.total, first.bytes, first.end===first.total-1);
        // A failed range never arrives, so it must end the opening here.
        let failRange;
        rangeFailed=new Promise((_, reject) => {failRange=reject;}); rangeFailed.catch(() => {});
        transport.requestDataRange=async (begin, end) => {
          try {
            let bytes;
            if (last && begin>=last.start) bytes=last.bytes.subarray(begin-last.start, end-last.start);
            else {
              const part=await range(`bytes=${begin}-${end-1}`);
              if (part.start!==begin || part.end!==end-1 || part.total!==first.total) throw Error('unavailable');
              bytes=part.bytes;
            }
            if (active()) transport.onDataRange(begin, bytes);
          } catch (error) {
            if (!active() || error?.message==='expired') return;
            failRange(error);
            status.textContent='Part of this PDF could not be loaded. Reopen this book or use Text view.';
          }
        };
        transport.abort=() => sources.abort();
        loading=pdfjs.getDocument({...options, range:transport});
      } else loading=pdfjs.getDocument({...options, url:source, withCredentials:true});
      // On a failed range the stalled task is left for stop(): destroying pdf.js
      // mid-load raises an unhandled termination error in its worker.
      pdf=await (rangeFailed ? Promise.race([loading.promise, rangeFailed]) : loading.promise);
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
      const scripts=Promise.all([
        window.JSZip || dependency('/reader/vendor/jszip/dist/jszip.min.js'),
        window.ePub || dependency('/reader/vendor/epubjs/dist/epub.min.js'),
      ]);
      scripts.catch(() => {});
      const epub=await import('/reader/epub.js');
      const container=root.querySelector('.epub-stage');
      const stage=styled(container);
      const show=async opened => {
        book=opened;
        await stage;
        if (!active() || book!==opened) return;
        container.hidden=false;
        const view=rendition=book.renderTo(container,{width:'100%',height:'100%',spread:'none',allowScriptedContent:false,allowPopups:false});
        // EPUB.js reports a failed section without settling display(), which
        // also holds later page turns. Its _display() sets displaying just
        // before calling manager.display(), so fail that display, not one that
        // has since replaced it.
        view.on('started', () => {
          const place=view.manager.display;
          view.manager.display=function (...args) {
            const pending=view.displaying;
            return place.apply(this,args).catch(error => { pending?.reject(error); throw error; });
          };
        });
        rendition.hooks.content.register(content => {
          for (const link of content.document.querySelectorAll('a[href]')) {
            if (/^(?:https?:|\/\/|mailto:|javascript:)/i.test(link.getAttribute('href'))) link.removeAttribute('href');
          }
        });
        display=destination => epub.displayEpubDestination(book,rendition,destination,location.origin);
        await display(data);
      };
      // Read the ZIP directory and only the members the first page needs. If
      // that fails before the page is shown, read the whole original instead.
      let opened;
      try {
        const index=await epub.readZipIndex(range);
        archive=new epub.RangeArchive(index);
        archive.prefetch(epub.openingMembers(index, data.epub_document));
        await scripts;
        if (!active()) return;
        opened=await epub.openRangeEpub(window.ePub, archive);
        if (!active()) {opened.destroy(); return;}
        // EPUB.js reports a failed asset without settling display(), so a
        // failed first-page member must end the wait here.
        const shown=show(opened);
        shown.catch(() => {});
        await Promise.race([shown, archive.failed]);
      } catch (error) {
        if (!active() || error?.message==='expired' || (opened && !archive?.error)) throw error;
        try {book?.destroy();} catch {}
        archive?.destroy();
        book=rendition=display=archive=undefined;
        container.replaceChildren();
        await scripts;
        const bytes=await (await response(source)).arrayBuffer();
        if (!active()) return;
        book=window.ePub(bytes);
        await book.ready;
        if (!active()) return;
        await show(book);
      }
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
