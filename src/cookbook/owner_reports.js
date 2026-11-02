(() => {
  const form = document.querySelector('#owner-report');
  if (!form) return;
  const status = document.querySelector('#report-status');
  let pending = null, busy = false, expired = false;
  document.addEventListener('reader-expired', () => {
    expired = true; form.reset(); pending = null;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || expired) return;
    let payload;
    try {
      const fields = Object.fromEntries(new FormData(form));
      payload = {...fields, region: fields.region.trim() ? JSON.parse('[' + fields.region + ']') : null};
      if (!pending) pending = {...payload, submission_id: crypto.randomUUID().replaceAll('-', '')};
      if (JSON.stringify({...pending, submission_id:undefined}) !== JSON.stringify(payload)) {
        status.textContent = 'Keep the original fields to retry an unconfirmed report. Reload to start a separate report.';
        return;
      }
    } catch { status.textContent = 'Enter region as four numbers separated by commas.'; return; }
    busy = true;
    status.textContent = 'Submitting — receipt not yet confirmed.';
    try {
      const response = await fetch('/reader/reports', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(pending), signal:AbortSignal.timeout(9000), cache:'no-store'});
      if (expired) return;
      if (response.status === 401) {
        form.reset(); pending = null;
        document.querySelector('main').replaceChildren();
        location.replace('/reader/login?' + new URLSearchParams({return:new URL(location.href).searchParams.get('at') || 'catalog'}));
        return;
      }
      const data = await response.json();
      if (response.ok && data.status === 'received') {
        status.textContent = 'Received, not verified. Receipt: ' + data.receipt_id;
        pending = null; form.reset();
      } else {
        status.textContent = ({rate_limited:'Rate limit reached. Retry this report later.', submission_conflict:'Submission conflict. Existing receipt was not overwritten.', reporting_unavailable:'Reporting unavailable. Draft remains in this tab.', receipt_unconfirmed:'Receipt unconfirmed. Retry the same report.'})[data.error] || 'Report not confirmed. Retry or correct the fields.';
        if (response.status === 400) pending = null;
      }
    } catch { status.textContent = 'Response timed out or connection failed. Receipt unconfirmed. Retry the same report.'; }
    finally { busy = false; }
  });
})();
