// Refresh only the current view, preserve filters, and pause while editing a field.
setInterval(() => {
  if (document.visibilityState === 'visible' && !['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)) location.reload();
}, 30000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') fetch('/refresh', {method:'POST'}).then(() => location.reload());
});
