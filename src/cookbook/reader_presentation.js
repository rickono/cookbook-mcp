/* Fragment destinations preserve keyboard focus on explicit reading returns. */
(() => {
  if (location.hash === '#text') document.querySelector('#text')?.focus();
})();
