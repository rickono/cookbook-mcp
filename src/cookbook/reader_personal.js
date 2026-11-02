/* Metadata and pending attempts live only in this mounted authorized document. */
(() => {
  const root = document.querySelector('#reader-personal');
  if (!root || root.dataset.initialized) return;
  root.dataset.initialized = 'true';
  const status = root.querySelector('#personal-status');
  const form = root.querySelector('#bookmark-save');
  const list = root.querySelector('#bookmark-list');
  let dead = false, busy = false, pending = null;
  const id = () => crypto.randomUUID().replaceAll('-', '');
  const timeout = () => AbortSignal.timeout(8500);
  let retry = root.querySelector('#personal-retry');
  if (!retry) {
    retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry original metadata write'; root.append(retry);
  }
  retry.hidden = true;
  const active = () => !dead && root.isConnected;
  function expire() {
    dead = true; pending = null; root.dataset.at = '';
    if (form) form.elements.name.value = '';
    list?.replaceChildren();
    status.textContent = ''; retry.hidden = true;
  }
  document.addEventListener('reader-expired', expire);
  async function response(url, options={}) {
    const r = await fetch(url, {cache:'no-store', signal:timeout(), ...options});
    if (r.status === 401) {
      document.dispatchEvent(new Event('reader-expired'));
      location.replace('/reader'); throw Error('expired');
    }
    return r;
  }
  async function refresh() {
    if (!active()) return;
    try {
      const r = await response('/reader/personal');
      if (!r.ok) throw Error();
      const data = await r.json();
      if (!active()) return;
      list.replaceChildren();
      for (const row of data.bookmarks) {
        const li = document.createElement('li');
        const label = document.createElement('label'); label.textContent = 'Bookmark name';
        const input = document.createElement('input'); input.maxLength = 120; input.autocomplete = 'off'; input.value = row.name; label.append(input); li.append(label);
        if (row.at) {
          const link = document.createElement('a'); link.href = '/reader/read?' + new URLSearchParams({at:row.at}); link.textContent = row.name || 'Open bookmark'; li.append(link);
        } else {
          const notice = document.createElement('p'); notice.textContent = 'Location unavailable. Reference retained.'; li.append(notice);
        }
        for (const [action, title] of [['rename','Rename'],['remove','Remove']]) {
          const button = document.createElement('button'); button.textContent = title;
          button.addEventListener('click', () => write({action, bookmark_id:row.bookmark_id, ...(action === 'rename' ? {name:input.value} : {})})); li.append(button);
        }
        list.append(li);
      }
    } catch {if (active()) status.textContent = 'Bookmarks unavailable. Refresh explicitly to retry.';}
  }
  async function write(value) {
    if (!active() || busy) return;
    if (pending && value) {status.textContent = 'Previous write unconfirmed. Retry the original attempt first.'; return;}
    pending ??= {...value, operation_id:id()};
    busy = true; retry.hidden = true; status.textContent = 'Saving…';
    try {
      const session = await response('/reader/session');
      if (!session.ok) throw Error();
      const csrf = (await session.json()).csrf;
      if (!active()) return;
      const r = await response('/reader/personal', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...pending, csrf})});
      const result = await r.json();
      if (!active()) return;
      if (!r.ok) {
        if ([400,403,404,409,429].includes(r.status)) {
          pending = null;
          status.textContent = r.status === 409 ? 'Write conflict. Refresh bookmarks before trying again.' : 'Metadata write refused (' + result.error + ').';
          return;
        }
        throw Error(result.error);
      }
      const removed = result.status === 'removed'; pending = null;
      status.textContent = removed ? 'Removed durably.' : 'Saved durably.';
      if (form) form.elements.name.value = '';
      if (list) await refresh();
    } catch {
      if (active()) {status.textContent = 'Persistence unconfirmed. Retry the original attempt; it may already have been saved.'; retry.hidden = false;}
    } finally {busy = false;}
  }
  retry.addEventListener('click', () => write());
  form?.addEventListener('submit', e => {e.preventDefault(); write({action:'save', at:root.dataset.at, name:form.elements.name.value});});
  root.querySelector('#remember-location')?.addEventListener('click', () => write({action:'resume', at:root.dataset.at}));
  root.querySelector('#personal-refresh')?.addEventListener('click', refresh);
  if (list) refresh();
  // One accepted stable navigation per mounted document. Never write on focus,
  // pageshow, session checks, scroll, continuations or a background mount.
  if (root.dataset.stable === 'true' && root.dataset.at && document.visibilityState === 'visible' && performance.getEntriesByType('navigation')[0]?.type !== 'back_forward') {
    write({action:'resume', at:root.dataset.at});
  }
})();
