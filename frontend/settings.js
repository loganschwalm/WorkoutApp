const settingsStorageKey = 'workout-tracker-settings';
const legacyTheme = localStorage.getItem('workout-tracker-theme');
const defaultSettings = { theme:legacyTheme === 'dark' ? 'dark' : 'light', restDuration:90, autoRest:true, confirmEnd:true, soundEnabled:true, soundVolume:40, alertSound:'beep', vibrate:true };
const getSettingElement = id => document.getElementById(id);
const canVibrate = typeof navigator.vibrate === 'function';
const alertTones = {
  beep:[{ at:0, freq:880, length:0.18 }, { at:0.25, freq:880, length:0.18 }],
  chime:[{ at:0, freq:659, length:0.22 }, { at:0.2, freq:784, length:0.22 }, { at:0.4, freq:988, length:0.4 }],
  long:[{ at:0, freq:740, length:0.7 }]
};
let audioContext = null;
let serverSettings = null;
window.serverStateReady = fetch('/api/state').then(response => response.ok ? response.json() : null).then(state => {
  if (!state) return null;
  serverSettings = { ...defaultSettings, ...(state.settings || {}) };
  localStorage.setItem(settingsStorageKey, JSON.stringify(serverSettings));
  applySettings(serverSettings);
  window.dispatchEvent(new Event('settingschange'));
  return state;
}).catch(() => null);

function getWorkoutSettings() {
  if (serverSettings) return { ...serverSettings };
  try {
    return { ...defaultSettings, ...JSON.parse(localStorage.getItem(settingsStorageKey) || '{}') };
  } catch (error) {
    return { ...defaultSettings };
  }
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

function readSettingsForm() {
  const restDuration = Math.min(600, Math.max(15, Number(getSettingElement('restDurationSetting').value) || defaultSettings.restDuration));
  const soundVolume = Math.min(100, Math.max(0, Number(getSettingElement('soundVolumeSetting').value) || 0));
  return { theme:getSettingElement('themeSetting').value, restDuration, autoRest:getSettingElement('autoRestSetting').checked, confirmEnd:getSettingElement('confirmEndSetting').checked, soundEnabled:getSettingElement('soundEnabledSetting').checked, soundVolume, alertSound:getSettingElement('alertSoundSetting').value, vibrate:getSettingElement('vibrateSetting').checked };
}

// Tone and volume mean nothing with sound off, and Test alert needs at least one way to alert.
function syncSoundControls() {
  const soundOn = getSettingElement('soundEnabledSetting').checked;
  getSettingElement('alertSoundSetting').disabled = !soundOn;
  getSettingElement('soundVolumeSetting').disabled = !soundOn;
  getSettingElement('testAlertButton').disabled = !soundOn && !(canVibrate && getSettingElement('vibrateSetting').checked);
}

function applySettings(settings) {
  document.documentElement.dataset.theme = settings.theme === 'dark' ? 'dark' : 'light';
  getSettingElement('themeSetting').value = settings.theme;
  getSettingElement('restDurationSetting').value = settings.restDuration;
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

function openSettings() {
  applySettings(getWorkoutSettings());
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
getSettingElement('settingsForm').onsubmit = event => {
  event.preventDefault();
  const settings = readSettingsForm();
  localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
  serverSettings = settings;
  fetch('/api/state', { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ settings }) }).catch(() => {});
  applySettings(settings);
  window.dispatchEvent(new Event('settingschange'));
  closeSettings();
};
