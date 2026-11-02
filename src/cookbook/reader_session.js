(() => {
  let busy = false;
  function clear() {
    document.dispatchEvent(new Event('reader-expired'));
    document.querySelector('main')?.replaceChildren();
  }
  async function check() {
    if (busy) return;
    try {
      const response = await fetch('/reader/session', {cache:'no-store'});
      if (response.status === 401) {
        clear();
        const at = new URL(location.href).searchParams.get('at');
        location.replace(at ? '/reader/login?' + new URLSearchParams({return:at}) : '/reader');
      }
    } catch {}
  }
  setInterval(check, 60000);
  addEventListener('pageshow', check);
  addEventListener('focus', check);
  document.addEventListener('visibilitychange', () => {if (!document.hidden) check();});

  const form = document.querySelector('form[action="/reader/logout"]');
  if (!form) return;
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  form.append(status);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const scope = event.submitter?.value;
    if (!['device', 'all'].includes(scope)) return;
    busy = true;
    const buttons = form.querySelectorAll('button');
    for (const button of buttons) button.disabled = true;
    status.textContent = 'Signing out…';
    const body = JSON.stringify({csrf:new FormData(form).get('csrf'), scope});
    try {
      const response = await fetch('/reader/logout', {
        method:'POST', body, headers:{'Content-Type':'application/json'},
        cache:'no-store', signal:AbortSignal.timeout(8500),
      });
      if (response.status === 401) {
        clear();
        location.replace('/reader');
        return;
      }
      if (!response.ok) throw Error();
      const result = await response.json();
      if (result.status !== 'signed_out' || result.scope !== scope) throw Error();
      clear();
      const main = document.querySelector('main');
      if (main) main.textContent = 'Reader signed out. Clearing browser data…';
      location.replace('/reader/signed-out');
    } catch {
      status.textContent = 'Sign-out not confirmed. Try again explicitly.';
      for (const button of buttons) button.disabled = false;
      busy = false;
    }
  });
})();
