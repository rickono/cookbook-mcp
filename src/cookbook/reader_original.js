/* Explicit recovery only; load/error report visible delivery, never byte receipt. */
(() => {
  const image = document.querySelector('[data-original-image]');
  const status = document.querySelector('#original-status');
  if (!image) return;
  status.textContent = 'Loading selected original…';
  let finished = false;
  const finish = success => {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    if (!success) image.removeAttribute('src');
    status.textContent = success ? 'Original displayed at supported size.' : 'Original unavailable or timed out. Retry explicitly, choose the whole page, or return to text.';
  };
  const deadline = setTimeout(() => finish(false), 30000);
  image.addEventListener('load', () => finish(image.naturalWidth > 0));
  image.addEventListener('error', () => finish(false));
  if (image.complete) finish(image.naturalWidth > 0);
  document.querySelector('[data-compare]')?.addEventListener('click', event => {
    const active = document.querySelector('.original-layout').classList.toggle('comparing');
    event.currentTarget.setAttribute('aria-pressed', String(active));
  });
})();
