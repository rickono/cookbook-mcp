(() => {
// Progressive enhancement. Protected content stays only in the live document.
const mount = document.querySelector('main');
let dead = false;
const references = new Set([...document.querySelectorAll('[data-reference-id]')].map(el => el.getAttribute('data-reference-id')));
const active = () => !dead && mount?.isConnected !== false;
let loader, places;
const destinations = new Map();
const stop = () => {
  dead = true; loader?.disconnect(); places?.disconnect();
  destinations.clear(); references.clear();
};
document.addEventListener('reader-expired', stop);
document.addEventListener('reader-unmounted', stop);
document.addEventListener('reader-withheld', stop);
const preferences = document.querySelector('.reading-preferences');
if (preferences) {
  const view = preferences.closest('.reader-view');
  const focus = preferences.querySelector('[data-reading-focus]');
  const smaller = preferences.querySelector('[data-text-smaller]');
  const larger = preferences.querySelector('[data-text-larger]');
  const size = preferences.querySelector('[data-text-size]');
  const sizes = [90, 100, 115, 130, 150];
  let index = 1;
  try {
    const saved = Number(sessionStorage.getItem('reader-text-size'));
    if (sizes.includes(saved)) index = sizes.indexOf(saved);
  } catch { /* Reading still works when browser storage is unavailable. */ }
  const resize = () => {
    view.dataset.textSize = String(sizes[index]);
    size.textContent = sizes[index] + '%';
    smaller.disabled = index === 0;
    larger.disabled = index === sizes.length - 1;
  };
  const changeSize = delta => {
    index = Math.max(0, Math.min(sizes.length - 1, index + delta));
    resize();
    try { sessionStorage.setItem('reader-text-size', String(sizes[index])); } catch {}
  };
  smaller.addEventListener('click', () => changeSize(-1));
  larger.addEventListener('click', () => changeSize(1));
  const setFocus = enabled => {
    view.classList.toggle('reading-focused', enabled);
    focus.setAttribute('aria-expanded', String(!enabled));
    focus.textContent = enabled ? 'Reading tools' : 'Hide tools';
    try { sessionStorage.setItem('reader-focus-view', String(enabled)); } catch {}
  };
  let focused = true;
  try { focused = sessionStorage.getItem('reader-focus-view') !== 'false'; } catch {}
  setFocus(focused);
  focus.addEventListener('click', () => setFocus(focus.getAttribute('aria-expanded') === 'true'));
  document.addEventListener('keydown', event => {
    if (!active() || event.key !== 'Escape') return;
    const menu = preferences.querySelector('details[open]');
    if (menu) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  resize();
  preferences.hidden = false;
}
const continuation = document.querySelector('[data-next-text]');
let automaticCharacters = 0;
function markLocation(url, chunk) {
  if (!active()) return;
  const current = new URL(location.href);
  const previous = current.searchParams.get('at');
  for (const link of document.querySelectorAll('a[href]')) {
    const target = new URL(link.href);
    if (target.pathname === '/reader/original' || target.pathname === '/reader/book-view') {
      target.searchParams.set('at', url.searchParams.get('at'));
      link.href = target.href;
    }
    if (!link.closest?.('[data-reference-id]') && target.searchParams.get('back') === previous) {
      target.searchParams.set('back', url.searchParams.get('at'));
      link.href = target.href;
    }
  }
  current.searchParams.set('at', url.searchParams.get('at'));
  current.hash = chunk.id;
  history.replaceState(null, '', current);
}
async function loadNext(explicit = false) {
  if (!active()) return;
  if (continuation.getAttribute('aria-disabled') === 'true') return;
  if (!explicit && document.visibilityState === 'hidden') return;
  continuation.setAttribute('aria-disabled', 'true');
  const status = document.querySelector('[data-reading-status]');
  status.textContent = 'Loading next text…';
  const url = new URL(continuation.href);
  try {
    const response = await fetch('/reader/content?' + url.searchParams.toString(), {
      cache: 'no-store', signal: AbortSignal.timeout(10000)
    });
    if (!active()) return;
    if (response.status === 401) {
      document.dispatchEvent?.(new Event('reader-expired'));
      document.querySelector('main').replaceChildren();
      location.replace('/reader/login?' + new URLSearchParams({return: url.searchParams.get('at')}));
      return;
    }
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    if (!active()) return;
    if (data.state === 'withheld') {
      document.querySelector('#text').replaceChildren();
      status.textContent = 'Text withheld by current withdrawal or supersession.';
      continuation.remove();
      stop();
      return;
    }
    const chunk = document.createElement('div');
    chunk.className = 'reading-chunk';
    chunk.id = 'chunk-' + data.text_offset;
    chunk.tabIndex = -1;
    if (data.text_blocks) {
      for (const block of data.text_blocks) {
        const text = document.createElement('div');
        text.className = 'source-text';
        text.textContent = block.text;
        if (block.kind === 'table') {
          const label = document.createElement('p');
          label.className = 'table-label';
          label.textContent = 'Table excerpt — authored cell boundaries; scroll horizontally. A delivery may start or end inside a table.';
          chunk.append(label);
          const region = document.createElement('div');
          region.className = 'table-region';
          region.tabIndex = 0;
          region.setAttribute('role', 'region');
          region.setAttribute('aria-label', 'Table excerpt, scroll horizontally');
          region.append(text);
          chunk.append(region);
        } else chunk.append(text);
      }
    } else {
      chunk.className = 'source-text';
      chunk.textContent = data.text;
    }
    for (const note of data.structure_notes || []) {
      const paragraph = document.createElement('p');
      paragraph.textContent = note;
      chunk.append(paragraph);
    }
    const authored = document.createElement('nav');
    authored.setAttribute('aria-label', 'Authored references');
    for (const ref of data.references || []) {
      if (!ref.id || references.has(ref.id)) continue;
      const control = document.createElement(ref.at ? 'a' : 'p');
      control.setAttribute('data-reference-id', ref.id);
      control.textContent = ref.label + (ref.at ? '' : ' — target unavailable');
      if (ref.at) {
        const target = new URL('/reader/read', location.href);
        target.search = new URLSearchParams({at: ref.at, back: url.searchParams.get('at')});
        target.hash = 'text';
        control.href = target.href;
      }
      authored.append(control);
      references.add(ref.id);
    }
    if (authored.children.length) chunk.append(authored);
    document.querySelector('#text').append(chunk);
    destinations.set(chunk, new URL(url));
    places?.observe(chunk);
    if (explicit) { markLocation(url, chunk); chunk.focus(); }
    automaticCharacters = explicit ? 0 : automaticCharacters + (data.text?.length || 0);
    status.textContent = data.next_text ? 'More text follows.' : 'End of this section.';
    if (data.next_text) {
      url.searchParams.set('at', data.next_text);
      continuation.href = url.pathname + url.search;
      loader?.unobserve(continuation);
      if (automaticCharacters < 200000) loader?.observe(continuation);
    } else {
      continuation.remove();
      const nextSection = document.querySelector('[data-book-next]');
      if (nextSection) nextSection.hidden = false;
    }
  } catch {
    if (active()) status.textContent = 'Loading interrupted. Your text is still here; use Continue reading to retry.';
    loader?.disconnect();
  } finally {
    continuation.removeAttribute('aria-disabled');
  }
}
if (continuation) {
  continuation.addEventListener('click', event => { event.preventDefault(); return loadNext(true); });
  if (typeof IntersectionObserver !== 'undefined') {
    places = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting && destinations.has(entry.target)) {
        markLocation(destinations.get(entry.target), entry.target);
      }
    }, {rootMargin: '-10% 0px -65% 0px'});
    const start = document.querySelector('#chunk-start');
    if (start) { destinations.set(start, new URL(location.href)); places.observe(start); }
    loader = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && continuation.isConnected !== false) return loadNext();
    }, {rootMargin: '0px 0px 600px 0px'});
    loader.observe(continuation);
    document.addEventListener('visibilitychange', () => {
      if (active() && document.visibilityState === 'visible' && continuation.isConnected) {
        loader.unobserve(continuation); loader.observe(continuation);
      }
    });
  }
}
})();
