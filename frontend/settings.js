let legacyTheme = null;
try { legacyTheme = localStorage.getItem('workout-tracker-theme'); } catch (error) { /* no storage: follow the device */ }
// Appearance: 'system' follows the device's light or dark mode; 'light' and 'dark' fix it.
const themeChoices = ['system', 'light', 'dark'];
const defaultSettings = { theme:themeChoices.includes(legacyTheme) ? legacyTheme : 'system', restDuration:90, weeklyGoal:3, unit:'lbs', autoRest:true, confirmEnd:true, soundEnabled:true, soundVolume:40, alertSound:'beep', vibrate:true };
const getSettingElement = id => document.getElementById(id);
const canVibrate = typeof navigator.vibrate === 'function';
const alertTones = {
  beep:[{ at:0, freq:880, length:0.18 }, { at:0.25, freq:880, length:0.18 }],
  chime:[{ at:0, freq:659, length:0.22 }, { at:0.2, freq:784, length:0.22 }, { at:0.4, freq:988, length:0.4 }],
  long:[{ at:0, freq:740, length:0.7 }]
};
let audioContext = null;

// A 401 from the API means the sign-in expired while the page was open. Offer a way back in without discarding anything on screen.
const nativeFetch = window.fetch.bind(window);
window.fetch = (...args) => nativeFetch(...args).then(response => {
  if (response.status === 401) showSessionExpired();
  return response;
});

function showSessionExpired() {
  if (document.getElementById('sessionExpired')) return;
  const banner = document.createElement('div');
  banner.id = 'sessionExpired';
  banner.className = 'session-banner';
  banner.setAttribute('role', 'alert');
  const message = document.createElement('span');
  message.textContent = 'Your session has expired. Sign in again to keep saving your workouts; a workout in progress stays on this device.';
  const link = document.createElement('a');
  link.className = 'button-link primary';
  link.href = `/login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
  link.textContent = 'Sign in again';
  banner.append(message, link);
  document.body.prepend(banner);
}

// Settings and templates for this account, from offline.js: the server's copy unless one changed here is still uploading.
window.serverStateReady = loadAccountState().then(state => {
  applySettings(getWorkoutSettings());
  window.dispatchEvent(new Event('settingschange'));
  return state;
});

function getWorkoutSettings() {
  const stored = readLocalState('settings');
  const value = stored && stored.value && typeof stored.value === 'object' && !Array.isArray(stored.value) ? stored.value : {};
  return { ...defaultSettings, ...value };
}

// Browsers only allow sound after a tap, so the audio context is created from buttons the user presses (rest timer, Test alert).
function unlockAudio() {
  try {
    audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === 'suspended') audioContext.resume();
  } catch (error) {
    audioContext = null;
  }
}

// Volume 0-100 maps to a peak gain of 0-0.3; the default of 40 is 0.12, a clear but quiet tone.
function playRestAlert(settings) {
  if (settings.vibrate && navigator.vibrate) navigator.vibrate([200, 100, 200]);
  const level = Math.min(100, Math.max(0, Number(settings.soundVolume) || 0)) / 100 * 0.3;
  if (!settings.soundEnabled || !audioContext || level <= 0) return;
  try {
    (alertTones[settings.alertSound] || alertTones.beep).forEach(note => {
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      const start = audioContext.currentTime + note.at;
      oscillator.frequency.value = note.freq;
      gain.gain.setValueAtTime(level, start);
      gain.gain.exponentialRampToValueAtTime(0.001, start + note.length);
      oscillator.connect(gain);
      gain.connect(audioContext.destination);
      oscillator.start(start);
      oscillator.stop(start + note.length + 0.02);
    });
  } catch (error) {
    console.error('Unable to play the rest timer sound.', error);
  }
}

// Workouts a week the training calendar on the History page counts a week as done at: a whole number from 1 to 7.
function weeklyGoalFrom(value) {
  const goal = Math.round(Number(value));
  return goal >= 1 && goal <= 7 ? goal : defaultSettings.weeklyGoal;
}

function readSettingsForm() {
  const restDuration = Math.min(600, Math.max(15, Number(getSettingElement('restDurationSetting').value) || defaultSettings.restDuration));
  const soundVolume = Math.min(100, Math.max(0, Number(getSettingElement('soundVolumeSetting').value) || 0));
  const weeklyGoal = weeklyGoalFrom(getSettingElement('weeklyGoalSetting').value);
  const unit = getSettingElement('unitSetting').value === 'kg' ? 'kg' : 'lbs';
  return { theme:getSettingElement('themeSetting').value, unit, restDuration, weeklyGoal, autoRest:getSettingElement('autoRestSetting').checked, confirmEnd:getSettingElement('confirmEndSetting').checked, soundEnabled:getSettingElement('soundEnabledSetting').checked, soundVolume, alertSound:getSettingElement('alertSoundSetting').value, vibrate:getSettingElement('vibrateSetting').checked };
}

// Tone and volume mean nothing with sound off, and Test alert needs at least one way to alert.
function syncSoundControls() {
  const soundOn = getSettingElement('soundEnabledSetting').checked;
  getSettingElement('alertSoundSetting').disabled = !soundOn;
  getSettingElement('soundVolumeSetting').disabled = !soundOn;
  getSettingElement('testAlertButton').disabled = !soundOn && !(canVibrate && getSettingElement('vibrateSetting').checked);
}

function applySettings(settings) {
  // theme.js, in <head>, applies it and follows the device. A page from before theme.js existed (served from the
  // cache for one load after an update) lacks it, and just gets light or dark.
  if (window.setColorTheme) window.setColorTheme(settings.theme);
  else document.documentElement.dataset.theme = settings.theme === 'dark' ? 'dark' : 'light';
  getSettingElement('themeSetting').value = themeChoices.includes(settings.theme) ? settings.theme : 'system';
  getSettingElement('unitSetting').value = settings.unit === 'kg' ? 'kg' : 'lbs';
  getSettingElement('restDurationSetting').value = settings.restDuration;
  getSettingElement('weeklyGoalSetting').value = String(weeklyGoalFrom(settings.weeklyGoal));
  getSettingElement('autoRestSetting').checked = settings.autoRest;
  getSettingElement('confirmEndSetting').checked = settings.confirmEnd;
  getSettingElement('soundEnabledSetting').checked = settings.soundEnabled;
  getSettingElement('alertSoundSetting').value = alertTones[settings.alertSound] ? settings.alertSound : defaultSettings.alertSound;
  getSettingElement('soundVolumeSetting').value = settings.soundVolume;
  getSettingElement('vibrateSetting').checked = settings.vibrate;
  getSettingElement('vibrateSettingRow').hidden = !canVibrate;
  syncSoundControls();
}

// Set by an import, whose workouts, templates and program the page then loads again to show.
let reloadAfterImport = false;

function closeSettings() {
  getSettingElement('settingsModal').hidden = true;
  if (reloadAfterImport) location.reload();
}

// The account's name and email. While the server has not said who is signed in (offline), there is nothing to change.
function showAccount() {
  const known = Boolean(window.localUsername);
  getSettingElement('accountName').textContent = known ? `Signed in as ${window.localUsername}` : '';
  getSettingElement('accountEmail').textContent = window.localEmail || 'No email yet. Add one so you can reset a forgotten password.';
  getSettingElement('accountEmail').hidden = getSettingElement('changeEmailButton').hidden = getSettingElement('changePasswordButton').hidden = !known;
  getSettingElement('deleteAccountButton').hidden = !known;
  getSettingElement('changeEmailButton').textContent = window.localEmail ? 'Change email' : 'Add email';
  getSettingElement('emailEditor').hidden = getSettingElement('passwordEditor').hidden = getSettingElement('deleteEditor').hidden = true;
  getSettingElement('accountNotice').hidden = true;
}

function showEmailError(message) {
  getSettingElement('emailFeedback').textContent = message;
  getSettingElement('emailFeedback').hidden = false;
}

// ---- Your data ------------------------------------------------------------
// Export saves the account to a file: all of it as JSON, which Import reads back (here or on another server), or every
// logged set as CSV for a spreadsheet. Workouts still waiting on this device upload first, so the file has them too.

function showDataStatus(message, failed = false) {
  const status = getSettingElement('dataStatus');
  status.textContent = message;
  status.className = failed ? 'auth-feedback data-status' : 'subtitle data-status';
  status.hidden = false;
}

function setDataButtonsDisabled(disabled) {
  ['exportButton', 'exportCsvButton', 'importButton'].forEach(id => { getSettingElement(id).disabled = disabled; });
}

async function exportAccount(asCsv) {
  setDataButtonsDisabled(true);
  showDataStatus('Preparing your file…');
  try {
    if (!(await flushPendingWorkouts())) throw new Error('Workouts waiting on this device could not be uploaded.');
    // The browser's time zone, so the dates in the file are the days you trained.
    const response = await syncFetch(`/api/export${asCsv ? '.csv' : ''}?offset=${-new Date().getTimezoneOffset()}`, {}, 60000);
    if (!response.ok) throw new Error(`Export failed (${response.status}).`);
    const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || (asCsv ? 'workout-tracker-sets.csv' : 'workout-tracker.json');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(await response.blob());
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    showDataStatus(`Downloaded ${name}.`);
  } catch (error) {
    console.error('Unable to export.', error);
    showDataStatus('Could not reach the server to export. Try again when you are back online.', true);
  } finally {
    setDataButtonsDisabled(false);
  }
}

// "Imported 12 workouts (3 were already here), 2 templates and the training program."
function describeImport(result) {
  const workouts = plural(result.workouts, 'workout') + (result.alreadyHere ? ` (${result.alreadyHere} ${result.alreadyHere === 1 ? 'was' : 'were'} already here)` : '');
  const parts = [workouts, result.templates ? plural(result.templates, 'template') : '', result.program ? 'the training program' : '', result.settings ? 'the settings' : ''].filter(Boolean);
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  const changed = result.workouts || result.templates || result.program || result.settings;
  return `Imported ${list}.${changed ? ' Close Settings to see them.' : ''}`;
}

async function importAccount(file) {
  let data = null;
  try { data = JSON.parse(await file.text()); } catch (error) { /* not JSON: answered below */ }
  if (!data || !Array.isArray(data.workouts)) {
    showDataStatus(`${file.name} is not a Workout Tracker export. Choose a .json file saved with Export.`, true);
    return;
  }
  if (!confirm(`Import ${plural(data.workouts.length, 'workout')} from ${file.name}? Workouts already in your account are skipped, and nothing here is replaced.`)) return;
  setDataButtonsDisabled(true);
  showDataStatus('Importing…');
  try {
    let response;
    try {
      response = await syncFetch('/api/import', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(data) }, 120000);
    } catch (error) {
      showDataStatus('Could not reach the server to import. Try again when you are back online.', true);
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      showDataStatus(result.error || 'The import failed. Nothing was added.', true);
      return;
    }
    showDataStatus(describeImport(result));
    // Settings the import brought are taken here now, so saving this form does not put the old ones back.
    if (result.settings) await loadAccountState().then(() => applySettings(getWorkoutSettings()));
    reloadAfterImport = reloadAfterImport || Boolean(result.workouts || result.templates || result.program || result.settings);
  } finally {
    setDataButtonsDisabled(false);
  }
}

function openSettings() {
  applySettings(getWorkoutSettings());
  showAccount();
  getSettingElement('dataStatus').hidden = true;
  getSettingElement('settingsModal').hidden = false;
  getSettingElement('themeSetting').focus();
}

window.getWorkoutSettings = getWorkoutSettings;
applySettings(getWorkoutSettings());
getSettingElement('settingsButton').onclick = openSettings;
getSettingElement('closeSettings').onclick = closeSettings;
getSettingElement('cancelSettings').onclick = closeSettings;
getSettingElement('settingsModal').onclick = event => { if (event.target === getSettingElement('settingsModal')) closeSettings(); };
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !getSettingElement('settingsModal').hidden) closeSettings(); });
['input', 'change'].forEach(type => getSettingElement('settingsForm').addEventListener(type, syncSoundControls));
// Plays the alert with the values currently in the form, so changes can be heard before they are saved.
getSettingElement('testAlertButton').onclick = () => { unlockAudio(); playRestAlert(readSettingsForm()); };
getSettingElement('signOutButton').onclick = async () => {
  const unsynced = typeof unsyncedWorkCount === 'function' ? unsyncedWorkCount() : 0;
  if (unsynced && !confirm('Some of your workout data has not reached the server yet. It stays on this device and uploads the next time you sign in to this account. Sign out anyway?')) return;
  try {
    const response = await fetch('/api/auth/logout', { method:'POST' });
    if (!response.ok) throw new Error('Sign out failed.');
  } catch (error) {
    alert('Could not sign out. Check your connection and try again.');
    return;
  }
  location.href = '/login.html';
};
getSettingElement('changeEmailButton').onclick = () => {
  getSettingElement('emailSetting').value = window.localEmail || '';
  getSettingElement('emailPassword').value = '';
  getSettingElement('emailFeedback').hidden = getSettingElement('accountNotice').hidden = true;
  getSettingElement('passwordEditor').hidden = getSettingElement('deleteEditor').hidden = true;
  getSettingElement('emailEditor').hidden = false;
  getSettingElement('emailSetting').focus();
};
getSettingElement('exportButton').onclick = () => exportAccount(false);
getSettingElement('exportCsvButton').onclick = () => exportAccount(true);
getSettingElement('importButton').onclick = () => getSettingElement('importFile').click();
getSettingElement('importFile').onchange = () => {
  const file = getSettingElement('importFile').files[0];
  // Cleared, so choosing the same file again still counts as a change.
  getSettingElement('importFile').value = '';
  if (file) importAccount(file);
};
getSettingElement('cancelEmail').onclick = () => { getSettingElement('emailEditor').hidden = true; };
getSettingElement('changePasswordButton').onclick = () => {
  getSettingElement('currentPassword').value = getSettingElement('newPassword').value = '';
  getSettingElement('passwordFeedback').hidden = getSettingElement('accountNotice').hidden = true;
  getSettingElement('emailEditor').hidden = getSettingElement('deleteEditor').hidden = true;
  getSettingElement('passwordEditor').hidden = false;
  getSettingElement('currentPassword').focus();
};
getSettingElement('cancelPassword').onclick = () => { getSettingElement('passwordEditor').hidden = true; };
getSettingElement('deleteAccountButton').onclick = () => {
  getSettingElement('deletePassword').value = '';
  getSettingElement('deleteFeedback').hidden = getSettingElement('accountNotice').hidden = true;
  getSettingElement('emailEditor').hidden = getSettingElement('passwordEditor').hidden = true;
  getSettingElement('deleteEditor').hidden = false;
  getSettingElement('deletePassword').focus();
};
getSettingElement('cancelDelete').onclick = () => { getSettingElement('deleteEditor').hidden = true; };
getSettingElement('deleteForm').onsubmit = async event => {
  event.preventDefault();
  const feedback = getSettingElement('deleteFeedback');
  const fail = message => { feedback.textContent = message; feedback.hidden = false; };
  feedback.hidden = true;
  if (!confirm(`Delete the account ${window.localUsername} and all its workouts? This cannot be undone.`)) return;
  const button = getSettingElement('confirmDelete');
  button.disabled = true;
  try {
    let response;
    try {
      response = await fetch('/api/account/delete', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ password:getSettingElement('deletePassword').value }) });
    } catch (error) {
      fail('Could not reach the server. Nothing was deleted; try again when you are back online.');
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      fail(result.error || 'Could not delete the account. Nothing was deleted.');
      return;
    }
    forgetLocalAccount();
    location.href = '/login.html?deleted=1';
  } finally {
    button.disabled = false;
  }
};
getSettingElement('passwordForm').onsubmit = async event => {
  event.preventDefault();
  const save = getSettingElement('savePassword');
  const feedback = getSettingElement('passwordFeedback');
  const fail = message => { feedback.textContent = message; feedback.hidden = false; };
  feedback.hidden = true;
  save.disabled = true;
  try {
    let response;
    try {
      response = await fetch('/api/account/password', { method:'POST', headers:{ 'Content-Type':'application/json' },
        body:JSON.stringify({ currentPassword:getSettingElement('currentPassword').value, newPassword:getSettingElement('newPassword').value }) });
    } catch (error) {
      fail('Could not reach the server. Try again when you are back online.');
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      fail(result.error || 'Could not change the password. Try again.');
      return;
    }
    getSettingElement('passwordEditor').hidden = true;
    const notice = getSettingElement('accountNotice');
    notice.textContent = `Password changed.${result.signedOut ? ` ${result.signedOut === 1 ? 'One other device was' : `${result.signedOut} other devices were`} signed out.` : ''}`;
    notice.hidden = false;
  } finally {
    save.disabled = false;
  }
};
getSettingElement('emailForm').onsubmit = async event => {
  event.preventDefault();
  const save = getSettingElement('saveEmail');
  getSettingElement('emailFeedback').hidden = true;
  save.disabled = true;
  try {
    let response;
    try {
      response = await fetch('/api/account/email', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ email:getSettingElement('emailSetting').value, password:getSettingElement('emailPassword').value }) });
    } catch (error) {
      showEmailError('Could not reach the server. Try again when you are back online.');
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      showEmailError(result.error || 'Could not save the email. Try again.');
      return;
    }
    window.localEmail = result.user.email;
    showAccount();
  } finally {
    save.disabled = false;
  }
};
getSettingElement('settingsForm').onsubmit = event => {
  event.preventDefault();
  const settings = readSettingsForm();
  saveLocalState('settings', settings);
  applySettings(settings);
  window.dispatchEvent(new Event('settingschange'));
  closeSettings();
};
