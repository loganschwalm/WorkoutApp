// Registers the service worker, keeps the browser chrome in step with the theme, and on a
// phone shows how to install the app.
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

// A bar along the bottom of the page, on a phone that has the app open in its browser, saying
// how to install it. Chrome and Edge on Android hand over their own install dialog, which the
// Install button opens; until they do, and in browsers that never do, the bar points at the
// browser menu. Safari has no such dialog, so iPhones and iPads are told where Add to Home
// Screen is. Installing needs HTTPS, so over plain HTTP there is nothing to offer.
//
// Closing it keeps it away for a week on this device, and installing keeps it away for good,
// since the page cannot otherwise tell it is open in a browser tab on a phone that has the app.
(() => {
  const KEY = 'workout-tracker-install-banner'; // 'installed', or when it was last closed
  const SNOOZE = 7 * 24 * 60 * 60 * 1000;
  const userAgent = navigator.userAgent;
  // iPadOS reports itself as a Mac; the touch screen gives it away.
  const isIOS = /iPad|iPhone|iPod/.test(userAgent) || (userAgent.includes('Mac') && navigator.maxTouchPoints > 1);
  const isPhone = isIOS || /Android/i.test(userAgent);
  const installed = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  let snoozed = false;
  try {
    const stored = localStorage.getItem(KEY);
    snoozed = stored === 'installed' || Date.now() - Number(stored) < SNOOZE;
  } catch (error) { /* no storage: show it */ }
  if (!window.isSecureContext || !isPhone || installed || snoozed) return;

  const SHARE_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 8.25H7.5a2.25 2.25 0 0 0-2.25 2.25v9a2.25 2.25 0 0 0 2.25 2.25h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25H15M12 2.25v10.5M12 2.25l3 3M12 2.25l-3 3"/></svg>';
  const banner = document.createElement('aside');
  banner.id = 'installBanner';
  banner.className = 'install-banner';
  banner.setAttribute('aria-label', 'Install the app');
  banner.innerHTML = '<img class="install-banner-icon" src="/icons/icon-192.png" alt="" />'
    + '<div class="install-banner-text"><strong class="install-banner-title">Install Workout Tracker</strong><span class="install-banner-hint"></span></div>'
    + '<button class="primary" type="button" hidden>Install</button>'
    + '<button class="modal-close" type="button" aria-label="Dismiss">&times;</button>';
  const hint = banner.querySelector('.install-banner-hint');
  const [installButton, dismissButton] = banner.querySelectorAll('button');
  hint.innerHTML = isIOS
    ? `Tap Share ${SHARE_ICON}, then <strong>Add to Home Screen</strong>.`
    : 'Open the browser menu <strong>&#8942;</strong> and choose <strong>Add to Home screen</strong>.';
  document.body.append(banner);
  document.body.classList.add('has-install-banner');

  let installPrompt = null;
  function close(remember) {
    banner.remove();
    document.body.classList.remove('has-install-banner');
    try { localStorage.setItem(KEY, remember); } catch (error) { /* shown again on the next page */ }
  }

  // Taking the dialog over stops Chrome from showing its own install bar on top of this one.
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    hint.textContent = 'Opens full screen like an app, and works offline.';
    installButton.hidden = false;
  });
  installButton.addEventListener('click', async () => {
    const prompt = installPrompt;
    if (!prompt) return;
    installPrompt = null;
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    close(outcome === 'accepted' ? 'installed' : String(Date.now()));
  });
  // Also fires for an install from the browser menu rather than the button.
  window.addEventListener('appinstalled', () => close('installed'));
  dismissButton.addEventListener('click', () => close(String(Date.now())));
})();
