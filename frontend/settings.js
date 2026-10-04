// What the settings are, their defaults, and how each is shown and read back are in settings-fields.js (loaded before this file).
// The state the server keeps is told the defaults, so a default filled in on a page is not mistaken for a change made there
// (see accountStateFill in offline.js). Guarded: for one load after an update, this file can run beside an older offline.js from the cache.
if (typeof accountStateFill !== 'undefined') {
  accountStateFill.settings = value => ({ ...defaultSettings, ...(value && typeof value === 'object' && !Array.isArray(value) ? value : {}) });
}
const alertTones = {
  beep:[{ at:0, freq:880, length:0.18 }, { at:0.25, freq:880, length:0.18 }],
  chime:[{ at:0, freq:659, length:0.22 }, { at:0.2, freq:784, length:0.22 }, { at:0.4, freq:988, length:0.4 }],
  long:[{ at:0, freq:740, length:0.7 }]
};
let audioContext = null;
// Hands the phone's audio back once an alert that took it (see playRestAlert) has finished.
let audioReleaseTimer = null;

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

// Every script of the page has run by DOMContentLoaded, which the server's answer need not wait for: on a slow phone, or a fast
// server, it can come while the page's last and biggest script is still to load. The Settings change that follows it is told
// to listeners that read what that script declares (rest-timer.js's, of the Tracker's activeSession), so it waits for them.
const pageScriptsRun = document.readyState === 'loading' ? new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, { once:true })) : Promise.resolve();

// Settings and templates for this account, from offline.js: the server's copy unless one changed here is still uploading.
window.serverStateReady = loadAccountState().then(async state => {
  await pageScriptsRun;
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
    if (audioContext && audioContext.state === 'closed') audioContext = null;
    audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
    wakeAudio();
  } catch (error) {
    audioContext = null;
  }
}

// Sound that is not running plays nothing until it is resumed. Besides 'suspended', Safari has an 'interrupted' state of
// its own, which an iPhone puts the sound in when the screen locks, a call comes in, or another app takes the audio; left
// there, every alert after it would be silent.
function wakeAudio() {
  if (audioContext && audioContext.state !== 'running') Promise.resolve(audioContext.resume()).catch(() => {});
}

function setAudioSession(type) {
  try { navigator.audioSession.type = type; } catch (error) { /* not Safari, or it declined: the phone keeps its choice */ }
}

// Volume 0-100 maps to a peak gain of 0-0.3; the default of 40 is 0.12, a clear but quiet tone.
function playRestAlert(settings) {
  if (settings.vibrate && navigator.vibrate) navigator.vibrate([200, 100, 200]);
  const level = Math.min(100, Math.max(0, Number(settings.soundVolume) || 0)) / 100 * 0.3;
  if (!settings.soundEnabled || !audioContext || level <= 0) return;
  const tones = alertTones[settings.alertSound] || alertTones.beep;
  // An iPhone plays a page's sound as ambient audio, which the Ring/Silent switch mutes. As playback audio, like a music
  // app's, it follows the volume buttons and plays with the ringer silent, but the phone pauses other audio (music, a
  // podcast) while it lasts. So playback is taken only for the length of the alert: then the sound is suspended and the
  // page goes back to ambient, which lets the music app carry on. Suspended, the sound resumes before the next alert.
  const throughSilent = canPlayThroughSilent && settings.playThroughSilent !== false;
  clearTimeout(audioReleaseTimer);
  if (throughSilent) setAudioSession('playback');
  // Tones scheduled while the sound is suspended (or interrupted) wait for it, and play as soon as it resumes.
  wakeAudio();
  scheduleTones(tones, level);
  if (throughSilent) {
    const length = Math.max(...tones.map(note => note.at + note.length)) + 0.3;
    audioReleaseTimer = setTimeout(() => {
      Promise.resolve(audioContext.suspend()).catch(() => {}).then(() => setAudioSession('auto'));
    }, length * 1000);
  }
}

function scheduleTones(tones, level) {
  try {
    tones.forEach(note => {
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

// What the controls say: every entry of settingFields reads its own (settings-fields.js), and what they say is merged.
function readSettingsForm() {
  const current = getWorkoutSettings();
  return Object.assign({}, ...settingFields.map(field => field.read(current)));
}

// The last plate ticked cannot be unticked: with no plates there is nothing to load.
function syncPlateControls() {
  const ticked = [...getSettingElement('plateSetting').querySelectorAll('input')].filter(input => input.checked);
  getSettingElement('plateSetting').querySelectorAll('input').forEach(input => { input.disabled = ticked.length === 1 && input.checked; });
}

// Tone and volume mean nothing with sound off, and Test alert needs at least one way to alert.
function syncSoundControls() {
  const soundOn = getSettingElement('soundEnabledSetting').checked;
  getSettingElement('alertSoundSetting').disabled = !soundOn;
  getSettingElement('soundVolumeSetting').disabled = !soundOn;
  getSettingElement('silentSetting').disabled = !soundOn;
  getSettingElement('testAlertButton').disabled = !soundOn && !(canVibrate && getSettingElement('vibrateSetting').checked);
}

// Puts the settings into the controls: every entry of settingFields shows its own (settings-fields.js).
function applySettings(settings) {
  settingFields.forEach(field => field.show(settings));
  syncSoundControls();
  syncPlateControls();
}

// Set by an import, whose workouts, templates and program the page then loads again to show.
let reloadAfterImport = false;

// Settings are kept as they change, so every way out of the dialog keeps them: Done, the ×, Escape and a tap outside it.
// Closing also keeps a rest duration still being typed, which is only taken once its field is left.
function closeSettings() {
  saveSettings();
  getSettingElement('settingsModal').hidden = true;
  returnFocus('settings');
  if (reloadAfterImport) location.reload();
}

// Keeps what the form says, when that differs from what is kept already, and tells the page. True when anything changed.
function saveSettings() {
  const settings = readSettingsForm();
  const current = getWorkoutSettings();
  if (Object.keys(settings).every(key => JSON.stringify(settings[key]) === JSON.stringify(current[key]))) return false;
  saveLocalState('settings', settings);
  applySettings(settings);
  window.dispatchEvent(new Event('settingschange'));
  return true;
}

let settingsSavedTimer = null;

function showSettingsSaved() {
  const status = getSettingElement('settingsSaved');
  status.textContent = 'Saved.';
  clearTimeout(settingsSavedTimer);
  settingsSavedTimer = setTimeout(() => { status.textContent = 'Changes are saved as you make them.'; }, 2000);
}

// The account's name and email. While the server has not said who is signed in (offline), there is nothing to change.
function showAccount() {
  const known = Boolean(window.localUsername);
  getSettingElement('accountName').textContent = known ? `Signed in as ${window.localUsername}` : '';
  getSettingElement('accountEmail').textContent = window.localEmail || 'No email yet. Add one so you can reset a forgotten password.';
  getSettingElement('accountEmail').hidden = getSettingElement('changeEmailButton').hidden = getSettingElement('changePasswordButton').hidden = !known;
  getSettingElement('deleteAccountButton').hidden = !known;
  getSettingElement('changeEmailButton').textContent = window.localEmail ? 'Change email' : 'Add email';
  showAccountPanel(null);
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
  const parts = [workouts, result.templates ? plural(result.templates, 'template') : '', result.program ? 'the training program' : '', result.settings ? 'the settings' : '',
    result.bodyweights ? plural(result.bodyweights, 'bodyweight') : '', result.exercises ? `the muscle and equipment of ${plural(result.exercises, 'exercise')}` : ''].filter(Boolean);
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  const changed = result.workouts || result.templates || result.program || result.settings || result.bodyweights || result.exercises;
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
    reloadAfterImport = reloadAfterImport || Boolean(result.workouts || result.templates || result.program || result.settings || result.bodyweights || result.exercises);
  } finally {
    setDataButtonsDisabled(false);
  }
}

function openSettings() {
  rememberOpener('settings');
  applySettings(getWorkoutSettings());
  showAccount();
  getSettingElement('dataStatus').hidden = true;
  getSettingElement('settingsModal').hidden = false;
  getSettingElement('themeSetting').querySelector('input[name=theme]:checked').focus();
  // reminders.js looks at what this browser can do and has been told, which can have changed since.
  window.dispatchEvent(new Event('settingsopen'));
}

window.getWorkoutSettings = getWorkoutSettings;
applySettings(getWorkoutSettings());
getSettingElement('settingsButton').onclick = openSettings;
getSettingElement('closeSettings').onclick = closeSettings;
getSettingElement('settingsModal').onclick = event => { if (event.target === getSettingElement('settingsModal')) closeSettings(); };
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !getSettingElement('settingsModal').hidden) closeSettings(); });
['input', 'change'].forEach(type => getSettingElement('settingsForm').addEventListener(type, () => { syncSoundControls(); syncPlateControls(); }));
// A setting is kept as soon as it changes: a box ticked, a choice picked, the volume let go, the rest duration's field left.
// The account's fields and the import's file belong to forms of their own, and are left out.
getSettingElement('settingsForm').addEventListener('change', event => {
  if (event.target.form !== getSettingElement('settingsForm') || event.target.type === 'file') return;
  if (saveSettings()) showSettingsSaved();
  // A bar weight that was not kept (empty, or too light or heavy) goes back to the one that was.
  else if (event.target.id === 'barSetting') event.target.value = formatWeight(gymEquipment().bar);
});
// Picking a distance unit keeps it, rather than leaving it to follow the weight unit. The select hears its change before
// the form does, which then saves it.
getSettingElement('distanceUnitSetting').addEventListener('change', event => { event.target.dataset.chosen = 'true'; });
// Plays the alert with the values currently in the form, so changes can be heard before they are saved.
getSettingElement('testAlertButton').onclick = () => { unlockAudio(); playRestAlert(readSettingsForm()); };
getSettingElement('signOutButton').onclick = async () => {
  const unsynced = typeof unsyncedWorkCount === 'function' ? unsyncedWorkCount() : 0;
  if (unsynced && !confirm('Some of your workout data has not reached the server yet. It stays on this device and uploads the next time you sign in to this account. Sign out anyway?')) return;
  // This browser stops being sent the account's reminders (reminders.js), before the session that says whose they are goes.
  if (typeof unsubscribePushDevice === 'function') await unsubscribePushDevice();
  try {
    const response = await fetch('/api/auth/logout', { method:'POST' });
    if (!response.ok) throw new Error('Sign out failed.');
  } catch (error) {
    alert('Could not sign out. Check your connection and try again.');
    return;
  }
  location.href = '/login.html';
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

// ---- The account's panels ------------------------------------------------
// Change email, Change password and Delete account each open a panel under the account, one at a time. Each asks for the
// password again and sends its own form. `start` fills the panel as it opens, `send` gives what to send (or nothing, to
// stop: a question answered no), and `done` takes the server's answer.
const offlineMessage = 'Could not reach the server. Try again when you are back online.';
const accountPanels = {
  email:{
    editor:'emailEditor', open:'changeEmailButton', cancel:'cancelEmail', form:'emailForm', submit:'saveEmail', feedback:'emailFeedback', focus:'emailSetting',
    path:'/api/account/email', offline:offlineMessage, failed:'Could not save the email. Try again.',
    start:() => { getSettingElement('emailSetting').value = window.localEmail || ''; getSettingElement('emailPassword').value = ''; },
    check:() => [['emailSetting', ruleProblem('emailProblem', getSettingElement('emailSetting').value)]],
    send:() => ({ email:getSettingElement('emailSetting').value, password:getSettingElement('emailPassword').value }),
    done:result => { window.localEmail = result.user.email; showAccount(); }
  },
  password:{
    editor:'passwordEditor', open:'changePasswordButton', cancel:'cancelPassword', form:'passwordForm', submit:'savePassword', feedback:'passwordFeedback',
    focus:'currentPassword', path:'/api/account/password', offline:offlineMessage, failed:'Could not change the password. Try again.',
    start:() => { getSettingElement('currentPassword').value = getSettingElement('newPassword').value = ''; },
    check:() => [['newPassword', ruleProblem('passwordProblem', getSettingElement('newPassword').value, window.localUsername || '', window.localEmail || '')]],
    send:() => ({ currentPassword:getSettingElement('currentPassword').value, newPassword:getSettingElement('newPassword').value }),
    done:result => {
      getSettingElement('passwordEditor').hidden = true;
      const others = result.signedOut === 1 ? 'One other device was' : `${result.signedOut} other devices were`;
      getSettingElement('accountNotice').textContent = `Password changed.${result.signedOut ? ` ${others} signed out.` : ''}`;
      getSettingElement('accountNotice').hidden = false;
    }
  },
  delete:{
    editor:'deleteEditor', open:'deleteAccountButton', cancel:'cancelDelete', form:'deleteForm', submit:'confirmDelete', feedback:'deleteFeedback', focus:'deletePassword',
    path:'/api/account/delete', offline:'Could not reach the server. Nothing was deleted; try again when you are back online.',
    failed:'Could not delete the account. Nothing was deleted.',
    start:() => { getSettingElement('deletePassword').value = ''; },
    send:() => confirm(`Delete the account ${window.localUsername} and all its workouts? This cannot be undone.`)
      && { password:getSettingElement('deletePassword').value },
    done:() => { forgetLocalAccount(); location.href = '/login.html?deleted=1'; }
  }
};

// Opens one panel and closes the others; null closes them all.
function showAccountPanel(name) {
  Object.entries(accountPanels).forEach(([key, panel]) => { getSettingElement(panel.editor).hidden = key !== name; });
  getSettingElement('settingsModal').querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
  getSettingElement('accountNotice').hidden = true;
  if (!name) return;
  const panel = accountPanels[name];
  getSettingElement(panel.feedback).hidden = true;
  panel.start();
  getSettingElement(panel.focus).focus();
}

// What account-rules.js says is wrong with a value, or ''. A page from before that file existed (served from the cache
// for one load after an update) does not have it, and leaves the checking to the server.
function ruleProblem(rule, ...values) {
  return typeof window[rule] === 'function' ? window[rule](...values) : '';
}

async function sendAccountPanel(panel) {
  const feedback = getSettingElement(panel.feedback);
  const fail = message => { feedback.textContent = message; feedback.hidden = false; };
  feedback.hidden = true;
  // A field that will not do is pointed out before anything is sent.
  const [field, problem] = (panel.check ? panel.check() : []).find(([, found]) => found) || [];
  if (problem) {
    getSettingElement(field).setAttribute('aria-invalid', 'true');
    getSettingElement(field).focus();
    fail(problem);
    return;
  }
  const body = panel.send();
  if (!body) return;
  const button = getSettingElement(panel.submit);
  button.disabled = true;
  try {
    let response;
    try {
      response = await fetch(panel.path, { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body) });
    } catch (error) {
      fail(panel.offline);
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      fail(result.error || panel.failed);
      return;
    }
    panel.done(result);
  } finally {
    button.disabled = false;
  }
}

// Typing in a field that was pointed out takes the mark away.
getSettingElement('settingsModal').addEventListener('input', event => event.target.removeAttribute('aria-invalid'));
Object.entries(accountPanels).forEach(([name, panel]) => {
  getSettingElement(panel.open).onclick = () => showAccountPanel(name);
  getSettingElement(panel.cancel).onclick = () => { getSettingElement(panel.editor).hidden = true; };
  getSettingElement(panel.form).onsubmit = event => { event.preventDefault(); sendAccountPanel(panel); };
});
// Done, or Enter in a field.
getSettingElement('settingsForm').onsubmit = event => {
  event.preventDefault();
  closeSettings();
};
