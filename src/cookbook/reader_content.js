(() => {
// Progressive enhancement. Protected content stays only in the live document.
const mount = document.querySelector('main');
let dead = false;
const references = new Set([...document.querySelectorAll('[data-reference-id]')].map(el => el.getAttribute('data-reference-id')));
const active = () => !dead && mount?.isConnected !== false;
document.addEventListener('reader-expired', () => {dead = true;});
document.addEventListener('reader-unmounted', () => {dead = true;});
const continuation = document.querySelector('[data-next-text]');
if (continuation) continuation.addEventListener('click', async event => {
  event.preventDefault();
  if (!active()) return;
  if (continuation.getAttribute('aria-disabled') === 'true') return;
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
    // Advance only after a successful response: failed reads can be explicitly retried.
    const current = new URL(location.href);
    const previous = current.searchParams.get('at');
    for (const link of document.querySelectorAll('a[href]')) {
      const target = new URL(link.href);
      if (target.pathname === '/reader/original') {
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
    status.textContent = data.next_text ? 'Partial text — more text remains.' : 'End of selected source text.';
    if (data.next_text) {
      url.searchParams.set('at', data.next_text);
      continuation.href = url.pathname + url.search;
    } else continuation.remove();
    chunk.focus();
  } catch {
    if (active()) status.textContent = 'Text continuation interrupted. Earlier text remains; retry Continue text.';
  } finally {
    continuation.removeAttribute('aria-disabled');
  }
});

})();
