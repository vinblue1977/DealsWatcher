// Runs before the first paint (the page's policy allows scripts from this site only, so it cannot be inline):
// sets the saved look so a Light choice does not flash dark. src/theme.ts does the rest once the app starts.
try {
  var saved = localStorage.getItem('dw.theme');
  document.documentElement.dataset.theme = saved === 'light' || saved === 'auto' ? saved : 'dark';
} catch {
  /* storage blocked: the dark default applies */
}
