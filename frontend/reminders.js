// Reminders on training days, from Settings: "Remind me on training days" asks this browser for a push subscription and
// gives it to the server, which posts a notification to it at the time chosen on each training day (the reminder loop in
// server.py); the service worker (sw.js) shows what arrives. The days and the time belong to the account (settings.schedule,
// see schedule.js), but a subscription belongs to one browser, so whether reminders are on is asked of this browser, not
// kept in the settings: a phone can have them and a laptop not. Loaded after settings.js on every page with Settings.

const pushClockKey = 'workout-tracker-push-clock';

function onIphone() {
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function installedAsApp() {
  return Boolean(navigator.standalone) || (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
}

// Why this browser cannot show reminders, in words for the Settings dialog, or '' when it can.
function pushProblem() {
  if (!window.isSecureContext) return 'Reminders need the app to be served over HTTPS, which this address is not. The README says how to set that up.';
  if (!('serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window)) {
    return onIphone() && !installedAsApp()
      ? 'On an iPhone, reminders work once the app is added to the Home Screen: use Share, then Add to Home Screen, and open it from there.'
      : 'This browser cannot show reminders.';
  }
  if (Notification.permission === 'denied') return 'Notifications are blocked for this site. Allow them in the browser’s settings for this address, then try again.';
  return '';
}

// The service worker, once it is running the page: pwa.js registers it. Not waited for forever.
function readyRegistration() {
  return Promise.race([navigator.serviceWorker.ready,
    new Promise((resolve, reject) => setTimeout(() => reject(new Error('The app is not ready to show notifications yet. Reload the page and try again.')), 5000))]);
}

async function currentPushSubscription() {
  try {
    return await (await readyRegistration()).pushManager.getSubscription();
  } catch (error) {
    return null;
  }
}

function keyBytes(text) {
  const raw = atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - text.length % 4) % 4));
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}

function sameBytes(buffer, bytes) {
  const first = new Uint8Array(buffer || []);
  return first.length === bytes.length && first.every((value, index) => value === bytes[index]);
}

// What the server is told of a subscription: where to post, the keys, and this phone's clock, which is what "5:30pm" is by.
function pushBody(subscription) {
  const { endpoint, keys } = subscription.toJSON();
  return { endpoint, keys, timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone || '', utcOffset:-new Date().getTimezoneOffset() };
}

async function pushRequest(path, body) {
  const response = await fetch(path, { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body || {}) });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `The server answered ${response.status}.`);
  return result;
}

// What the server was last told about this subscription, to tell it again when that changes: the day (once a day), the time zone
// and the offset from UTC (a phone that travelled, or daylight saving).
function pushClockStamp(subscription) {
  return `${subscription.endpoint}|${new Date().toDateString()}|${pushBody(subscription).timeZone}|${-new Date().getTimezoneOffset()}`;
}

function rememberPushClock(subscription) {
  try { localStorage.setItem(pushClockKey, pushClockStamp(subscription)); } catch (error) { /* told again next time */ }
}

async function turnOnReminders() {
  if (Notification.permission !== 'granted' && (await Notification.requestPermission()) !== 'granted') {
    throw new Error('Notifications were not allowed, so there is nothing to show reminders with.');
  }
  const response = await fetch('/api/push/key');
  if (!response.ok) throw new Error('Could not reach the server.');
  const key = keyBytes((await response.json()).publicKey);
  const registration = await readyRegistration();
  let subscription = await registration.pushManager.getSubscription();
  // One made for another server's key (this server's database was replaced, say) cannot be used.
  if (subscription && !sameBytes(subscription.options && subscription.options.applicationServerKey, key)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription = subscription || await registration.pushManager.subscribe({ userVisibleOnly:true, applicationServerKey:key });
  await pushRequest('/api/push/subscribe', pushBody(subscription));
  rememberPushClock(subscription);
}

async function turnOffReminders() {
  const subscription = await currentPushSubscription();
  if (!subscription) return;
  await pushRequest('/api/push/unsubscribe', { endpoint:subscription.endpoint });
  await subscription.unsubscribe();
  try { localStorage.removeItem(pushClockKey); } catch (error) { /* nothing to forget */ }
}

// Signing out takes this browser off the account's reminders, so the next person to use it is not sent them. Best effort.
async function unsubscribePushDevice() {
  try { await turnOffReminders(); } catch (error) { /* the server is out of reach: signing out goes on */ }
}

// A subscription is told to the server again once a day, and whenever the phone's clock changed (travel, daylight saving),
// so reminders stay at the right time and survive a server that lost it.
async function syncPushDevice() {
  if (pushProblem() || Notification.permission !== 'granted') return;
  const subscription = await currentPushSubscription();
  if (!subscription) return;
  let told = null;
  try { told = localStorage.getItem(pushClockKey); } catch (error) { /* no storage: told every time */ }
  if (told === pushClockStamp(subscription)) return;
  try {
    await pushRequest('/api/push/subscribe', pushBody(subscription));
    rememberPushClock(subscription);
  } catch (error) {
    console.error('Unable to tell the server about this device’s reminders.', error);
  }
}

// ---- The Settings dialog --------------------------------------------------------

let remindersOn = false;

function showReminderStatus(message, failed = false) {
  const status = getSettingElement('remindStatus');
  status.textContent = message;
  status.className = failed ? 'auth-feedback' : 'subtitle';
}

function renderReminders() {
  const problem = pushProblem();
  const box = getSettingElement('remindSetting');
  box.disabled = Boolean(problem);
  box.checked = !problem && remindersOn;
  getSettingElement('testReminderButton').hidden = !box.checked;
  const days = getSettingElement('scheduleDays').querySelectorAll('input:checked').length;
  if (problem) showReminderStatus(problem);
  else if (remindersOn) showReminderStatus(days ? 'Reminders are on for this device.' : 'Reminders are on for this device. Choose the days you train, above, to be reminded.');
  else showReminderStatus('A notification on the days you train, at this time, even when the app is closed.');
}

async function refreshReminders() {
  remindersOn = !pushProblem() && Notification.permission === 'granted' && Boolean(await currentPushSubscription());
  renderReminders();
}

getSettingElement('remindSetting').addEventListener('change', async event => {
  const box = event.target;
  const wanted = box.checked;
  box.disabled = true;
  showReminderStatus(wanted ? 'Turning reminders on…' : 'Turning reminders off…');
  try {
    if (wanted) await turnOnReminders();
    else await turnOffReminders();
    remindersOn = wanted;
  } catch (error) {
    console.error('Unable to change reminders.', error);
    remindersOn = !wanted;
    await refreshReminders();
    showReminderStatus(`Could not turn reminders ${wanted ? 'on' : 'off'}: ${error.message || error}`, true);
    return;
  }
  box.disabled = false;
  renderReminders();
});

getSettingElement('testReminderButton').onclick = async () => {
  const button = getSettingElement('testReminderButton');
  button.disabled = true;
  showReminderStatus('Sending…');
  try {
    const result = await pushRequest('/api/push/test');
    showReminderStatus(!result.devices ? 'The server has no device to send to. Turn reminders off and on again.'
      : result.sent ? `Sent to ${result.sent === 1 ? 'your device' : `${result.sent} devices`}. It should arrive in a moment.`
        : 'The push service did not take it. The server needs to reach the internet to send reminders.', !result.sent);
  } catch (error) {
    showReminderStatus(error.message || 'Could not send the test.', true);
  } finally {
    button.disabled = false;
  }
};

// Choosing days changes what the status says.
getSettingElement('scheduleDays').addEventListener('change', renderReminders);
window.addEventListener('settingsopen', refreshReminders);
window.serverStateReady.then(syncPushDevice);
