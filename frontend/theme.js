// Sets the colour theme before anything is drawn, so a dark page never flashes light on the way in. Loaded in <head>
// on every page, the sign-in page included.
//
// The theme is the Appearance setting as last saved on this device: 'light', 'dark', or 'system' (the default), which
// follows the device's own light or dark mode, and keeps following it while the page is open. settings.js calls
// setColorTheme when the setting changes or the server's copy arrives.
(() => {
  const deviceDark = window.matchMedia('(prefers-color-scheme: dark)');
  let choice = 'system';

  window.setColorTheme = theme => {
    choice = theme === 'light' || theme === 'dark' ? theme : 'system';
    const dark = choice === 'dark' || (choice === 'system' && deviceDark.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  };
  deviceDark.addEventListener('change', () => { if (choice === 'system') window.setColorTheme('system'); });

  let saved = null;
  try {
    // offline.js keeps each account's settings under its id, and remembers who signed in here last. Before any
    // account has, the browser-only version's theme may still be here.
    const user = JSON.parse(localStorage.getItem('workout-tracker-last-user'));
    const record = JSON.parse(localStorage.getItem(`workout-tracker-settings-${user ?? 'unknown'}`));
    saved = record && record.value ? record.value.theme : localStorage.getItem('workout-tracker-theme');
  } catch (error) { /* no storage: follow the device */ }
  window.setColorTheme(saved);
})();
