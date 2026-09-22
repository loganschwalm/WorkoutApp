// Registers the service worker and keeps the browser chrome in step with the theme.
//
// Service workers only run in a secure context, so this does nothing over plain HTTP
// to a LAN address. The app itself works exactly as before; only offline reloads and
// installing to the home screen need HTTPS (or localhost).
(() => {
  const THEME_COLORS = { light: '#f4f7fb', dark: '#151923' };

  function syncThemeColor() {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    const theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    meta.setAttribute('content', THEME_COLORS[theme]);
  }

  // settings.js sets data-theme on <html>; watching it keeps this decoupled from that,
  // and works on the login page, which does not load settings.js at all.
  syncThemeColor();
  new MutationObserver(syncThemeColor)
    .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // Nothing to do: the app runs fine uncached.
    });
  });
})();
