/* Only this boolean visual preference is persisted; no reading data or position. */
(() => {
  const button = document.querySelector('[data-kitchen]');
  if (!button) return;
  const key = 'reader-kitchen';
  const apply = active => {
    document.body.classList.toggle('kitchen', active);
    button.setAttribute('aria-pressed', String(active));
  };
  try { apply(localStorage.getItem(key) === 'true'); } catch { apply(false); }
  button.hidden = false;
  button.addEventListener('click', () => {
    const active = button.getAttribute('aria-pressed') !== 'true';
    apply(active);
    try { localStorage.setItem(key, String(active)); } catch { /* Live mode still works. */ }
    document.querySelector('[data-appearance-status]').textContent = active ? 'Kitchen mode on.' : 'Kitchen mode off.';
  });
  // Fragment destinations are focusable reading anchors, including explicit returns.
  if (location.hash === '#text') document.querySelector('#text')?.focus();
})();
