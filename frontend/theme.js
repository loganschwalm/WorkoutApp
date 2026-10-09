// Sets the colour theme and the text size before anything is drawn, so a dark page never flashes light on the way in, nor a
// large one small. Loaded in <head> on every page, the sign-in page included.
//
// The theme is the Appearance setting as last saved on this device: one of colorThemes below, or 'system' (the
// default), which is Light or Dark as the device's own mode is, and keeps following it while the page is open.
// settings.js calls setColorTheme when the setting changes or the server's copy arrives.
//
// <html> gets data-palette, the theme whose colours styles.css uses, and data-theme, whether that theme is light or
// dark, which the rules that differ in the dark go by.
//
// The Text size setting is one of textSizes below. Anything but 'normal' is data-text-size on <html>, which styles.css turns into a
// larger font size for the page; every size in the stylesheet is in rem, so all of the text follows it.
(() => {
  const deviceDark = window.matchMedia('(prefers-color-scheme: dark)');
  // Each theme, with whether it is light or dark. Settings names them (settings-dialog.js).
  window.colorThemes = { light:'light', dark:'dark', sunrise:'light', meadow:'light', blossom:'light',
    crimson:'dark', emerald:'dark', ocean:'dark', gold:'dark', violet:'dark' };
  // The sizes the Text size setting offers. Settings names them (settings-fields.js) and styles.css gives each its scale.
  window.textSizes = ['normal', 'large', 'larger', 'largest'];
  let choice = 'system';

  window.setColorTheme = theme => {
    choice = Object.prototype.hasOwnProperty.call(window.colorThemes, theme) ? theme : 'system';
    const palette = choice === 'system' ? (deviceDark.matches ? 'dark' : 'light') : choice;
    document.documentElement.dataset.theme = window.colorThemes[palette];
    document.documentElement.dataset.palette = palette;
  };
  window.setTextSize = size => {
    if (window.textSizes.includes(size) && size !== 'normal') document.documentElement.dataset.textSize = size;
    else delete document.documentElement.dataset.textSize;
  };
  deviceDark.addEventListener('change', () => { if (choice === 'system') window.setColorTheme('system'); });

  let saved = null;
  let savedSize = null;
  try {
    // offline.js keeps each account's settings under its id, and remembers who signed in here last. Before any
    // account has, the browser-only version's theme may still be here.
    const user = JSON.parse(localStorage.getItem('workout-tracker-last-user'));
    const record = JSON.parse(localStorage.getItem(`workout-tracker-settings-${user ?? 'unknown'}`));
    saved = record && record.value ? record.value.theme : localStorage.getItem('workout-tracker-theme');
    savedSize = record && record.value ? record.value.textSize : null;
  } catch (error) { /* no storage: follow the device */ }
  window.setColorTheme(saved);
  window.setTextSize(savedSize);
})();
