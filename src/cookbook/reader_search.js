/* Search state and detached result DOM exist only in this live authorized tab. */
(() => {
  const main = document.querySelector('main');
  const form = document.querySelector('#search-form');
  const status = document.querySelector('#search-status');
  const book = form.elements.book_id;
  const fresh = document.querySelector('#fresh-search');
  const groups = {};
  for (const name of ['content', 'section']) groups[name] = {
    list: document.querySelector(`#${name}-results`),
    status: document.querySelector(`#${name}-status`),
    more: document.querySelector(`#${name}-more`), next: null, seen: new Set(),
  };
  if (form.dataset.book) {
    const option = text('option', 'Current book'); option.value = form.dataset.book;
    book.append(option); book.value = option.value;
  }
  let csrf = form.dataset.csrf ?? '';
  delete form.dataset.csrf;
  let state = null, busy = false, saved = null, origin = null, y = 0, dead = false;
  const timeout = () => AbortSignal.timeout(8500);
  function clear() {
    dead = true; state = null; csrf = ''; origin = null;
    form.reset();
    for (const g of Object.values(groups)) {g.list.replaceChildren(); g.seen.clear(); g.next = null;}
    if (saved) {saved.replaceChildren(); saved = null;}
    main.replaceChildren();
  }
  function discard() {document.dispatchEvent(new Event('reader-expired'));}
  function expired() {discard(); location.replace('/reader');}
  document.addEventListener('reader-expired', clear);
  // Explicitly discard even a back/forward-cache copy; a reload starts a fresh search.
  addEventListener('pagehide', discard);
  addEventListener('pageshow', e => {if (e.persisted) location.replace('/reader/search');});
  async function send(fields) {
    // Recovery is confined to this read-only endpoint; mutation requests never use it.
    const post = () => fetch('/reader/search/results', {method:'POST', cache:'no-store', signal:timeout(), headers:{'Content-Type':'application/json'}, body:JSON.stringify({...fields, csrf})});
    if (dead) throw Error();
    let r = await post();
    if (dead) throw Error();
    if (r.status !== 403) return r;
    const error = await r.json();
    if (dead) throw Error();
    if (error?.error !== 'csrf_denied') return r;
    const rejected = csrf;
    csrf = '';
    const session = await fetch('/reader/session', {cache:'no-store', signal:timeout()});
    if (dead) throw Error();
    if (session.status === 401) {expired(); throw Error();}
    if (!session.ok) throw Error();
    const data = await session.json();
    if (dead) throw Error();
    if (data?.authenticated !== true || typeof data.csrf !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(data.csrf) || data.csrf === rejected) throw Error();
    csrf = data.csrf;
    r = await post();
    if (dead) throw Error();
    if (r.status === 403) csrf = '';
    return r;
  }
  function text(tag, value) {const el = document.createElement(tag); el.textContent = value; return el;}
  function paint(name, data, append) {
    const g = groups[name];
    if (data.state === 'failed') {
      g.status.textContent = data.coverage;
      // Retain the failed page number, and all previously delivered rows, for explicit retry.
      g.more.hidden = false; g.more.textContent = `Retry ${name === 'content' ? 'Content' : 'Section'} matches`;
      return;
    }
    if (!append) {g.list.replaceChildren(); g.seen.clear();}
    g.next = data.next;
    g.status.textContent = `${data.state === 'ok' && !data.results.length ? 'No matches on this page. ' : ''}${data.cutoff ? 'Search cutoff: results may be incomplete. ' : ''}${data.coverage}`;
    if (data.details) g.status.textContent += ' ' + JSON.stringify(data.details);
    for (const hit of data.results) {
      if (g.seen.has(hit.href)) continue;
      g.seen.add(hit.href);
      const row = document.createElement('li'), link = text('a', hit.title);
      link.href = hit.href; link.dataset.searchMatch = 'true';
      row.append(link, text('p', `${hit.book} · ${hit.authors.join(', ')} · Format: ${hit.format}`), text('p', hit.excerpt));
      g.list.append(row);
    }
    g.more.hidden = g.next === null;
    g.more.textContent = `Load more ${name === 'content' ? 'Content' : 'Section'} matches`;
  }
  async function run(name = 'both', reset = false) {
    if (busy || dead) return;
    busy = true; form.querySelector('button').disabled = true;
    for (const g of Object.values(groups)) g.more.disabled = true;
    status.textContent = 'Searching…';
    if (reset) {
      state = {query:form.elements.query.value, book_id:book.value, kind:form.elements.kind.value};
      for (const g of Object.values(groups)) {g.next = null; g.list.replaceChildren(); g.seen.clear();}
      fresh.hidden = true;
    }
    try {
      const body = {...state, group:name};
      if (name === 'content') body.content_page = groups.content.next ?? 1;
      if (name === 'section') body.section_offset = groups.section.next ?? 0;
      const r = await send(Object.freeze(body));
      if (dead) return;
      if (r.status === 401) {expired(); return;}
      if (r.status === 410) {fresh.hidden = false; status.textContent = 'Pinned publication retired. Start a fresh search explicitly to use current text.'; return;}
      if (!r.ok) throw Error();
      const data = await r.json();
      if (dead) return;
      state.publication_id = data.publication_id;
      for (const [key, value] of Object.entries(data.groups)) paint(key, value, name !== 'both');
      status.textContent = Object.values(data.groups).every(g => g.state === 'failed') ? 'Search failed. Retry explicitly.' : 'Search finished. Each group has independent coverage and continuation.';
      if (name !== 'both') {groups[name].more.focus();}
    } catch {
      if (!dead) status.textContent = 'Search interrupted. Retry explicitly; existing results remain available.';
    } finally {
      busy = false; form.querySelector('button').disabled = false;
      for (const g of Object.values(groups)) g.more.disabled = false;
    }
  }
  form.addEventListener('submit', e => {e.preventDefault(); run('both', true);});
  fresh.addEventListener('click', () => run('both', true));
  for (const [name, g] of Object.entries(groups)) g.more.addEventListener('click', () => run(name));
  // Both query and selected controls remain untouched when scope changes.
  const moreScopes = document.querySelector('#more-scopes');
  let scopeURL = '/reader/catalog';
  async function books() {
    try {
      // Load one bounded catalog page per explicit action, never book text.
      moreScopes.disabled = true;
      {
        const r = await fetch(scopeURL, {cache:'no-store', signal:timeout()});
        if (r.status === 401) {expired(); return;}
        if (!r.ok) throw Error();
        const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
        if (dead) return;
        for (const a of doc.querySelectorAll('a[href^="/reader/read?at="],a[href^="/reader/book?at="]')) {
          const at = new URL(a.getAttribute('href'), location.href).searchParams.get('at');
          const loc = JSON.parse(atob(at.replace(/-/g,'+').replace(/_/g,'/')));
          const option = text('option', a.closest('li').querySelector('strong').textContent);
          option.value = loc.book_id; book.append(option);
        }
        scopeURL = [...doc.querySelectorAll('a')].find(a => a.textContent === 'More books')?.getAttribute('href');
        moreScopes.hidden = !scopeURL;
      }
    } catch {if (!dead) status.textContent = 'Book scopes unavailable. Whole-library search remains available; retry loading scopes.'; moreScopes.hidden = false;}
    finally {moreScopes.disabled = false;}
  }
  moreScopes.addEventListener('click', books);
  books();
  async function read(href, link) {
    if (busy || dead) return;
    busy = true;
    const notice = saved ? main.querySelector('[role="status"]') : status;
    if (notice) notice.textContent = 'Opening source location…';
    try {
      const r = await fetch(href, {cache:'no-store', signal:timeout()});
      if (r.status === 401) {expired(); return;}
      if (!r.ok && ![400,404,410].includes(r.status)) throw Error();
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      if (dead) return;
      const parsedMain=doc.querySelector('main');
      if (!parsedMain) throw Error('invalid reading response');
      // Moving the parsed body empties it. Capture its assets before adoption,
      // including form/continuation enhancements declared inside that body.
      const styles = [...doc.querySelectorAll('link[rel="stylesheet"][href]')];
      const enhancements = [...doc.querySelectorAll('script[src]')];
      if (!saved) {
        origin = link; y = scrollY;
        saved = document.createDocumentFragment();
        saved.append(...main.childNodes);
      }
      document.dispatchEvent(new Event('reader-unmounted'));
      main.replaceChildren(...parsedMain.childNodes);
      for (const declared of styles) {
        const href = declared.getAttribute('href');
        if (!/^\/reader\/[a-z_-]+\.css$/.test(href)) continue;
        const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = href;
        main.append(style);
      }
      history.replaceState(null, '', href);
      const back = text('button', 'Return to search results'); back.className = 'back-button button-quiet';
      back.addEventListener('click', () => {
        document.dispatchEvent(new Event('reader-unmounted'));
        main.replaceChildren(saved); saved = null;
        history.replaceState(null, '', '/reader/search');
        status.textContent = 'Search restored.';
        origin.focus({preventScroll:true}); scrollTo(0,y);
      });
      main.prepend(back);
      // DOMParser scripts are inert. Reinitialize only first-party reader enhancements
      // declared by the trusted reading response; the session monitor is already active.
      for (const declared of enhancements) {
        const src = declared.getAttribute('src');
        if (!/^\/reader\/[a-z_-]+\.js$/.test(src) || src === '/reader/session.js') continue;
        const script = document.createElement('script'); script.src = src; script.async = false;
        main.append(script);
      }
      back.focus(); scrollTo(0,0);
    } catch {if (notice) notice.textContent = 'Reading interrupted. Retry this match; search results are retained.';}
    finally {busy = false;}
  }
  main.addEventListener('click', e => {
    if (e.defaultPrevented) return;
    const scopeLink = e.target.closest('a[href^="/reader/search?at="]');
    if (saved && scopeLink && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      const at = new URL(scopeLink.href).searchParams.get('at');
      const loc = JSON.parse(atob(at.replace(/-/g,'+').replace(/_/g,'/')));
      document.dispatchEvent(new Event('reader-unmounted'));
      main.replaceChildren(saved); saved = null;
      history.replaceState(null, '', '/reader/search');
      const option = text('option', 'Current book'); option.value = loc.book_id;
      book.append(option); book.value = option.value; book.focus();
      status.textContent = 'Query retained. Choose Search to apply this book scope.';
      return;
    }
    const a = e.target.closest('a[href^="/reader/read?at="],a[href^="/reader/book-view?at="]');
    if (!a || a.hasAttribute('data-next-text') || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault(); read(a.getAttribute('href'), a);
  });
})();
