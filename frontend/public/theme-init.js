// Runs before the first paint (the page's policy allows scripts from this site only, so it cannot be inline):
// sets the saved look so a Light choice does not flash dark. src/theme.ts does the rest (the browser bar colour) once the app starts.
// Keep the key and the three values in step with src/theme.ts.
try {
  var saved = localStorage.getItem('dw.theme');
  var theme = saved === 'light' || saved === 'auto' ? saved : 'dark';
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme === 'auto' ? 'light dark' : theme;
} catch {
  /* storage blocked: the dark default applies */
}
