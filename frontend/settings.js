let legacyTheme = null;
try { legacyTheme = localStorage.getItem('workout-tracker-theme'); } catch (error) { /* no storage: follow the device */ }
// Appearance: 'system' follows the device's light or dark mode; 'light' and 'dark' fix it.
const themeChoices = ['system', 'light', 'dark'];
const defaultSettings = { theme:themeChoices.includes(legacyTheme) ? legacyTheme : 'system', restDuration:90, weeklyGoal:3, autoRest:true, confirmEnd:true, soundEnabled:true, soundVolume:40, alertSound:'beep', vibrate:true };
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
  return { theme:getSettingElement('themeSetting').value, restDuration, weeklyGoal, autoRest:getSettingElement('autoRestSetting').checked, confirmEnd:getSettingElement('confirmEndSetting').checked, soundEnabled:getSettingElement('soundEnabledSetting').checked, soundVolume, alertSound:getSettingElement('alertSoundSetting').value, vibrate:getSettingElement('vibrateSetting').checked };
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

function closeSettings() {
  getSettingElement('settingsModal').hidden = true;
}

// The account's name and email. While the server has not said who is signed in (offline), there is nothing to change.
function showAccount() {
  const known = Boolean(window.localUsername);
  getSettingElement('accountName').textContent = known ? `Signed in as ${window.localUsername}` : '';
  getSettingElement('accountEmail').textContent = window.localEmail || 'No email yet. Add one so you can reset a forgotten password.';
  getSettingElement('accountEmail').hidden = getSettingElement('changeEmailButton').hidden = !known;
  getSettingElement('changeEmailButton').textContent = window.localEmail ? 'Change email' : 'Add email';
  getSettingElement('emailEditor').hidden = true;
}

function showEmailError(message) {
  getSettingElement('emailFeedback').textContent = message;
  getSettingElement('emailFeedback').hidden = false;
}

function openSettings() {
  applySettings(getWorkoutSettings());
  showAccount();
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
  getSettingElement('emailFeedback').hidden = true;
  getSettingElement('emailEditor').hidden = false;
  getSettingElement('emailSetting').focus();
};
getSettingElement('cancelEmail').onclick = () => { getSettingElement('emailEditor').hidden = true; };
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
