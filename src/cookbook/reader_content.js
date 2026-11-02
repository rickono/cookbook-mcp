// Progressive enhancement. Protected content stays only in the live document.
const continuation = document.querySelector('[data-next-text]');
if (continuation) continuation.addEventListener('click', async event => {
  event.preventDefault();
  if (continuation.getAttribute('aria-disabled') === 'true') return;
  continuation.setAttribute('aria-disabled', 'true');
  const status = document.querySelector('[role="status"]');
  status.textContent = 'Loading next text…';
  const url = new URL(continuation.href);
  try {
    const response = await fetch('/reader/content?' + url.searchParams.toString(), {
      cache: 'no-store', signal: AbortSignal.timeout(10000)
    });
    if (response.status === 401) {
      document.querySelector('main').replaceChildren();
      location.replace('/reader/login?' + new URLSearchParams({return: url.searchParams.get('at')}));
      return;
    }
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    if (data.state === 'withheld') {
      document.querySelector('#text').replaceChildren();
      status.textContent = 'Text withheld by current withdrawal or supersession.';
      continuation.remove();
      return;
    }
    const chunk = document.createElement('div');
    chunk.className = 'source-text';
    chunk.id = 'chunk-' + data.text_offset;
    chunk.tabIndex = -1;
    chunk.textContent = data.text;
    document.querySelector('#text').append(chunk);
    // Advance only after a successful response: failed reads can be explicitly retried.
    const current = new URL(location.href);
    const previous = current.searchParams.get('at');
    for (const link of document.querySelectorAll('a[href]')) {
      const target = new URL(link.href);
      if (target.searchParams.get('back') === previous) {
        target.searchParams.set('back', url.searchParams.get('at'));
        link.href = target.href;
      }
    }
    current.searchParams.set('at', url.searchParams.get('at'));
    current.hash = chunk.id;
    history.replaceState(null, '', current);
    status.textContent = data.next_text ? 'Partial text — more text remains.' : 'End of section text. Loaded text does not establish a complete recipe or supporting work.';
    if (data.next_text) {
      url.searchParams.set('at', data.next_text);
      continuation.href = url.pathname + url.search;
    } else continuation.remove();
    chunk.focus();
  } catch {
    status.textContent = 'Text continuation interrupted. Earlier text remains; retry Continue text.';
  } finally {
    continuation.removeAttribute('aria-disabled');
  }
});
