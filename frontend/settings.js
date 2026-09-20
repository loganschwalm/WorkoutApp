const settingsStorageKey = 'workout-tracker-settings';
const legacyTheme = localStorage.getItem('workout-tracker-theme');
const defaultSettings = { theme:legacyTheme === 'dark' ? 'dark' : 'light', restDuration:90, autoRest:true, confirmEnd:true };
const getSettingElement = id => document.getElementById(id);
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

function applySettings(settings) {
  document.documentElement.dataset.theme = settings.theme === 'dark' ? 'dark' : 'light';
  getSettingElement('themeSetting').value = settings.theme;
  getSettingElement('restDurationSetting').value = settings.restDuration;
  getSettingElement('autoRestSetting').checked = settings.autoRest;
  getSettingElement('confirmEndSetting').checked = settings.confirmEnd;
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
getSettingElement('settingsForm').onsubmit = event => {
  event.preventDefault();
  const restDuration = Math.min(600, Math.max(15, Number(getSettingElement('restDurationSetting').value) || defaultSettings.restDuration));
  const settings = { theme:getSettingElement('themeSetting').value, restDuration, autoRest:getSettingElement('autoRestSetting').checked, confirmEnd:getSettingElement('confirmEndSetting').checked };
  localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
  serverSettings = settings;
  fetch('/api/state', { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ settings }) }).catch(() => {});
  applySettings(settings);
  window.dispatchEvent(new Event('settingschange'));
  closeSettings();
};
