// Apply the persisted theme before first paint to avoid a flash of the wrong theme.
// A separate file (not inline) so the strict Content-Security-Policy can forbid inline scripts.
try {
  var stored = JSON.parse(localStorage.getItem('wesetrade.theme') || 'null');
  var theme = stored && stored.state && stored.state.theme;
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
} catch (e) {}
