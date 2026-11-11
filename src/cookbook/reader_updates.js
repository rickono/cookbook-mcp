(() => {
// Retain source evidence in copied URLs without moving the pinned view.
const sourceNotice = document.querySelector('#publication-update');
if (!sourceNotice || sourceNotice.dataset.initialized) return;
sourceNotice.dataset.initialized = 'true';
if (sourceNotice?.dataset.at) {
  const current = new URL(location.href);
  current.searchParams.set('at', sourceNotice.dataset.at);
  history.replaceState(null, '', current);
}
// Notice checks never replace text, continuations or history. Explicit links only.
async function checkPublication() {
  const notice = sourceNotice;
  if (notice.isConnected === false || document.querySelector('#publication-update') !== notice) return;
  const at = new URL(location.href).searchParams.get('at');
  try {
    const response = await fetch('/reader/updates?' + new URLSearchParams({at}), {
      cache: 'no-store', signal: AbortSignal.timeout(10000)
    });
    if (response.status === 401) {
      document.dispatchEvent?.(new Event('reader-expired'));
      document.querySelector('main').replaceChildren();
      location.replace('/reader/login?' + new URLSearchParams({return: at}));
      return;
    }
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    if (notice.isConnected === false || document.querySelector('#publication-update') !== notice) return;
    if (data.pinned_state === 'withheld') {
      document.dispatchEvent?.(new Event('reader-withheld'));
      document.querySelector('#text')?.replaceChildren();
      document.querySelector('[data-next-text]')?.remove();
      const status = document.querySelector('[data-reading-status]');
      if (status && status !== notice) status.textContent = 'Text withheld by current withdrawal or supersession.';
    }
    const publication = JSON.parse(atob(at.replace(/-/g, '+').replace(/_/g, '/'))).publication_id;
    // Preserve keyboard focus when the same notice is checked again.
    const key = JSON.stringify(data);
    if (notice.dataset.result === key) return;
    notice.dataset.result = key;
    const restoreFocus = notice.contains?.(document.activeElement);
    notice.replaceChildren();
    const text = document.createElement('p');
    text.textContent = 'Reading publication ' + publication + '.';
    notice.append(text);
    if (data.pinned_state === 'withheld') {
      const withdrawn = document.createElement('p');
      withdrawn.textContent = 'Text withheld by current withdrawal or supersession. Original access is checked separately.';
      notice.append(withdrawn);
    }
    if (data.current_publication_id && data.current_publication_id !== publication) {
      const message = document.createElement('p');
      message.textContent = 'A newer publication is available. This view remains pinned while retained.';
      notice.append(message);
      if (data.at) {
        const link = document.createElement('a');
        const original = notice.dataset.view === 'original';
        link.href = (original ? '/reader/book-view?' : '/reader/read?') + new URLSearchParams({at: data.at}) + (original ? '' : '#text');
        link.textContent = original ? 'Open current original' : 'Open current text';
        notice.append(link);
      } else {
        const unavailable = document.createElement('p');
        unavailable.textContent = 'Current text unavailable at a reliable location in this edition.';
        notice.append(unavailable);
      }
    }
    if (restoreFocus) {
      const action = notice.querySelector('a');
      if (action) action.focus();
      else { notice.tabIndex = -1; notice.focus(); }
    }
  } catch {
    // Keep the existing explicit action usable after a transient check failure.
    notice.setAttribute('aria-label', 'Publication update check interrupted; retry by refocusing this page');
  }
}
document.addEventListener('reader-check', checkPublication);

})();
