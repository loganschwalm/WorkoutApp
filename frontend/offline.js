// Local-first persistence. The in-progress workout, finished workouts that have not reached the server yet, settings,
// custom templates and the training program are written to localStorage (per account) first, then pushed to the server in
// the background and retried until it accepts them. Loaded before settings.js, which keeps its settings here.
const lastUserStorageKey = 'workout-tracker-last-user';
const memoryStore = new Map();
let localUserId = readLocal(lastUserStorageKey);
let changeCounter = 0;
let activeSyncTimer = null;
let activeSyncing = false;
let activeSyncFailed = false;
let activeRetryCount = 0;
let pendingFlush = null;
let pendingRetryTimer = null;
let pendingRetryCount = 0;
let stateSyncTimer = null;
let stateSyncing = false;
let stateRetryCount = 0;
// Set once the account has been deleted (forgetLocalAccount): what the page still saves on its way out, such as the rest on
// show (rememberRest in rest-timer.js), is of nothing, and would be left behind on the device.
let localAccountForgotten = false;
// Set once another account has signed in on this browser while this page was open (accountSignedInElsewhere).
let localAccountElsewhere = false;
// The stamp of each part of the account state as this page last knew it, by its key (see takeOtherTabsChanges).
const knownStateStamps = new Map();

// Falls back to memory when localStorage is unavailable, so syncing still works (it just cannot survive a reload).
function readLocal(key) {
  if (memoryStore.has(key)) return memoryStore.get(key);
  try { return JSON.parse(localStorage.getItem(key)); }
  catch (error) { return null; }
}

function writeLocal(key, value) {
  if (localAccountForgotten) return;
  // This page's own change to a part of the account state is not another tab's (see takeOtherTabsChanges).
  if (knownStateStamps.has(key)) knownStateStamps.set(key, value?.stamp);
  try {
    localStorage.setItem(key, JSON.stringify(value));
    memoryStore.delete(key);
    // Storing works again, so whatever had to be held in memory meanwhile is stored too, not only this.
    memoryStore.forEach((held, heldKey) => {
      try { localStorage.setItem(heldKey, JSON.stringify(held)); memoryStore.delete(heldKey); } catch (error) { /* still held */ }
    });
  } catch (error) {
    // Out of room, the copies of the saved workouts (only copies: the server has them) give way to what is kept nowhere else.
    try {
      if (!dropSavedWorkoutsCopies()) throw error;
      localStorage.setItem(key, JSON.stringify(value));
      memoryStore.delete(key);
    } catch (again) {
      memoryStore.set(key, value);
    }
  }
  syncStorageWarning();
}

// Anything held in memory because the browser would not store it (its storage full, or blocked) goes with a reload,
// a workout finished offline included. A banner says so while anything is held that way, and goes once it is stored.
function syncStorageWarning() {
  let banner = document.getElementById('storageWarning');
  if (!memoryStore.size) { banner?.remove(); return; }
  if (banner || !document.body) return;
  banner = document.createElement('div');
  banner.id = 'storageWarning';
  banner.className = 'session-banner';
  banner.setAttribute('role', 'alert');
  banner.textContent = 'This browser is not letting the app save on this device: its storage may be full, or blocked. '
    + 'Anything not uploaded yet is only kept while this page stays open, so keep it open until you are back online.';
  document.body.prepend(banner);
}

function localKey(name) {
  return `workout-tracker-${name}-${localUserId ?? 'unknown'}`;
}

// ---- The saved workouts, as last loaded -----------------------------------
// A copy of the account's saved workouts as the server last sent them, so a page opened offline still lists them (the
// Tracker's recent workouts, History, Progress, Cardio) instead of saying there are none. It is kept apart from writeLocal:
// it is only a copy, so it never takes the room that work not yet uploaded needs (writeLocal drops it first), is never held
// in memory, and never brings up the storage warning. Written only once the server has said whose page this is, so one
// account's list is never kept as another's, and dropped on signing out, since unlike work waiting to upload it is not needed
// to come back to. It can be one page load behind: a workout deleted just before going offline is listed until the next load.

const savedWorkoutsCopyPrefix = 'workout-tracker-workouts-';
let localUserConfirmed = false;

function keepSavedWorkoutsCopy(workouts) {
  if (localAccountForgotten || !localUserConfirmed) return;
  try { localStorage.setItem(localKey('workouts'), JSON.stringify(workouts)); }
  catch (error) { dropSavedWorkoutsCopies(); }
}

function readSavedWorkoutsCopy() {
  try {
    const copy = JSON.parse(localStorage.getItem(localKey('workouts')));
    return Array.isArray(copy) ? copy : null;
  } catch (error) {
    return null;
  }
}

// Every account's copy on this device: whether any was there to drop.
function dropSavedWorkoutsCopies() {
  try {
    const keys = Object.keys(localStorage).filter(key => key.startsWith(savedWorkoutsCopyPrefix));
    keys.forEach(key => localStorage.removeItem(key));
    return keys.length > 0;
  } catch (error) {
    return false;
  }
}

// Each request says which account the page is for (the one its copies on this device are kept under), and the server refuses
// it if the browser is now signed in as another (see accountSignedInElsewhere).
function syncFetch(path, options = {}, timeout = 10000) {
  if (localAccountElsewhere) return Promise.reject(new Error('Another account is signed in on this browser.'));
  const signal = typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(timeout) : undefined;
  const headers = localUserId === null ? options.headers : { ...options.headers, 'X-Workout-Account':String(localUserId) };
  return fetch(path, { ...options, headers, signal }).then(response => {
    if (response.status === 409 && response.headers.get('X-Workout-Account-Mismatch')) {
      accountSignedInElsewhere();
      throw new Error('Another account is signed in on this browser.');
    }
    return response;
  });
}

// The cookie is the browser's, not the page's: signing in to another account in another tab signs this page in to it too.
// What this page has not uploaded is its own account's, so nothing more goes up from it (syncFetch refuses, and the server
// would too), and it stays on this device for the next time that account signs in. A banner says so, and reloading takes the
// page to the account now signed in. Seen as soon as the other tab signs in (it writes the last account seen here), and
// otherwise by the server's answer.
function accountSignedInElsewhere() {
  if (localAccountElsewhere || localAccountForgotten) return;
  localAccountElsewhere = true;
  [activeSyncTimer, pendingRetryTimer, stateSyncTimer].forEach(clearTimeout);
  const banner = document.createElement('div');
  banner.id = 'accountElsewhere';
  banner.className = 'session-banner';
  banner.setAttribute('role', 'alert');
  const message = document.createElement('span');
  message.textContent = 'Another account has signed in on this browser, so this page has stopped saving to the server. '
    + 'Anything it had not uploaded stays on this device until this account signs in again.';
  const reload = document.createElement('button');
  reload.type = 'button';
  reload.className = 'primary';
  reload.textContent = 'Reload';
  reload.onclick = () => location.reload();
  banner.append(message, reload);
  document.body.prepend(banner);
}

window.addEventListener('storage', event => {
  if (event.key !== lastUserStorageKey || localUserId === null || event.newValue === null) return;
  let signedIn = null;
  try { signedIn = JSON.parse(event.newValue); } catch (error) { return; }
  if (signedIn !== null && signedIn !== localUserId) accountSignedInElsewhere();
});

function newClientId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}

function reportSyncStatus(uploaded = 0) {
  window.dispatchEvent(new CustomEvent('syncchange', { detail:{ pendingWorkouts:readPendingWorkouts().length, rejectedWorkouts:readRejectedWorkouts().length, activeOffline:activeSyncFailed, uploaded } }));
}

// The signed-in account decides which local copy is ours; fall back to the last known account when the server is unreachable.
window.localReady = syncFetch('/api/auth/me', {}, 4000).then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to identify the user.'))).then(result => {
  localUserId = result.user ? result.user.id : null;
  window.localUsername = result.user ? result.user.username : null;
  window.localEmail = result.user ? result.user.email : null;
  localUserConfirmed = localUserId !== null;
  if (localUserId !== null) writeLocal(lastUserStorageKey, localUserId);
}).catch(() => {});

// ---- In-progress workout --------------------------------------------------

function readLocalActive() {
  return readLocal(localKey('active'));
}

function mirrorActiveSession(session) {
  writeLocal(localKey('active'), { session, dirty:false, stamp:`${Date.now()}-${++changeCounter}` });
}

// A null session is recorded too: it means the workout ended and the server still has to be told.
function saveLocalActive(session) {
  writeLocal(localKey('active'), { session, dirty:true, stamp:`${Date.now()}-${++changeCounter}` });
  scheduleActiveSync(400);
}

function scheduleActiveSync(delay) {
  clearTimeout(activeSyncTimer);
  activeSyncTimer = setTimeout(syncActiveSession, delay);
}

async function syncActiveSession() {
  clearTimeout(activeSyncTimer);
  if (activeSyncing) return;
  const key = localKey('active');
  const record = readLocal(key);
  if (!record || !record.dirty) return;
  activeSyncing = true;
  try {
    const response = record.session
      ? await syncFetch('/api/active-session', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ session:record.session }) })
      : await syncFetch('/api/active-session', { method:'DELETE' });
    if (!response.ok) throw new Error(`Active workout sync failed (${response.status}).`);
    const latest = readLocal(key);
    if (latest && latest.stamp === record.stamp) writeLocal(key, { ...latest, dirty:false });
    activeRetryCount = 0;
    if (activeSyncFailed) { activeSyncFailed = false; reportSyncStatus(); }
  } catch (error) {
    console.error('Unable to sync active workout; it is saved on this device and will be retried.', error);
    activeRetryCount += 1;
    if (!activeSyncFailed) { activeSyncFailed = true; reportSyncStatus(); }
  } finally {
    activeSyncing = false;
  }
  const remaining = readLocal(key);
  if (remaining && remaining.dirty) scheduleActiveSync(activeRetryCount ? Math.min(60000, 2000 * 2 ** (activeRetryCount - 1)) : 400);
}

// ---- Finished workouts ----------------------------------------------------

function readPendingWorkouts() {
  return readLocal(localKey('pending')) || [];
}

function queuePendingWorkout(workout) {
  writeLocal(localKey('pending'), [...readPendingWorkouts(), workout]);
  reportSyncStatus();
}

// Finished workouts the server refused as invalid. Kept on this device rather than thrown away, but out of the
// upload queue, where retrying one forever would hold back every workout finished after it.
function readRejectedWorkouts() {
  return readLocal(localKey('rejected')) || [];
}

// Finished workouts carry a clientId; one queued by a build from before that is matched by its contents.
function sameQueuedWorkout(a, b) {
  return a.clientId || b.clientId ? a.clientId === b.clientId : JSON.stringify(a) === JSON.stringify(b);
}

function withoutQueuedWorkout(queue, workout) {
  const index = queue.findIndex(item => sameQueuedWorkout(item, workout));
  return index === -1 ? queue : [...queue.slice(0, index), ...queue.slice(index + 1)];
}

function schedulePendingRetry() {
  pendingRetryCount += 1;
  pendingRetryTimer = setTimeout(flushPendingWorkouts, Math.min(60000, 2000 * 2 ** (pendingRetryCount - 1)));
}

// Resolves true once nothing is left to upload, false if something is still waiting (a retry is scheduled).
function flushPendingWorkouts() {
  if (pendingFlush) return pendingFlush;
  clearTimeout(pendingRetryTimer);
  pendingFlush = (async () => {
    await window.localReady;
    let uploaded = 0;
    // Workouts the server answered with an error this time round. They stay queued for the retry, but the ones after
    // them go up now: one the server keeps failing on must not hold back every workout finished since.
    const failed = [];
    const untried = () => readPendingWorkouts().filter(workout => !failed.some(other => sameQueuedWorkout(other, workout)));
    let queue = untried();
    while (queue.length) {
      const workout = queue[0];
      let rejected = false;
      try {
        const response = await syncFetch('/api/workouts', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(workout) });
        // 400 and 413 say this workout can never be accepted as it is; anything else may succeed on a retry.
        rejected = response.status === 400 || response.status === 413;
        if (rejected) console.error(`The server refused a finished workout (${response.status}); it is kept on this device.`, await response.text());
        // A signed-out answer would be the same for every workout, so the rest wait for signing in again.
        else if (response.status === 401) throw new Error('Workout sync failed: signed out.');
        else if (!response.ok) {
          console.error(`The server could not store a finished workout (${response.status}); it stays queued, and the rest go on.`);
          failed.push(workout);
          queue = untried();
          continue;
        }
      } catch (error) {
        // The server could not be reached, so the rest would fail too: all of them wait for the retry.
        console.error('Unable to sync finished workout; it is saved on this device and will be retried.', error);
        schedulePendingRetry();
        reportSyncStatus(uploaded);
        return false;
      }
      // By clientId, never by position: another tab uploading the same queue may have removed this one already, and
      // dropping whatever is first would then drop a workout that has not been uploaded.
      if (rejected && !readRejectedWorkouts().some(other => sameQueuedWorkout(other, workout))) writeLocal(localKey('rejected'), [...readRejectedWorkouts(), workout]);
      writeLocal(localKey('pending'), withoutQueuedWorkout(readPendingWorkouts(), workout));
      if (!rejected) uploaded += 1;
      if (rejected) reportSyncStatus();
      queue = untried();
    }
    if (failed.length) {
      schedulePendingRetry();
      reportSyncStatus(uploaded);
      return false;
    }
    pendingRetryCount = 0;
    if (uploaded) reportSyncStatus(uploaded);
    return true;
  })().finally(() => { pendingFlush = null; });
  return pendingFlush;
}

// ---- Settings, custom templates and the training program -----------------
// The same rule as the in-progress workout: a change is saved on this device first and stays marked dirty until the
// server has it, and a dirty local copy beats the server's when a page loads, so a change made offline is never undone.
// Nor does it undo a change made on another device meanwhile: a part goes up with the copy it was changed from (its
// base), and the server keeps both devices' changes (merge_part in server.py), the later winning only where both changed
// the same thing.
const accountStateParts = ['settings', 'templates', 'program', 'exerciseNotes', 'goals', 'bodyweight', 'exerciseLibrary'];
// For a part whose pages fill in what the stored copy leaves out (settings' defaults), how they do, so a default filled
// in on a page is not mistaken for a change made there. settings.js and program.js add theirs.
const accountStateFill = {};

// Before these were kept per account, one copy per browser was shared by whoever signed in. It was last written
// by the last account seen here, so it becomes that account's copy, marked clean so the server's copy replaces it.
[['settings', 'workout-tracker-settings'], ['templates', 'workout-tracker-custom-templates']].forEach(([part, legacyKey]) => {
  try {
    const legacy = localStorage.getItem(legacyKey);
    if (legacy === null) return;
    if (localUserId !== null && !readLocalState(part)) writeLocal(localKey(part), { value:JSON.parse(legacy), dirty:false, stamp:'legacy' });
    localStorage.removeItem(legacyKey);
  } catch (error) {
    // Unreadable old copy or no storage: the server's copy is loaded instead.
  }
});

function readLocalState(part) {
  const record = readLocal(localKey(part));
  return record && typeof record === 'object' && 'value' in record ? record : null;
}

function saveLocalState(part, value) {
  const record = readLocalState(part);
  // The copy this change starts from: the one last loaded or uploaded, kept while changes wait to go up, with any copies
  // sent meanwhile that have had no answer yet. A part never loaded here, or changed by a version from before bases, has
  // none, and its change replaces the server's whole.
  const base = !record ? {} : !record.dirty ? { base:record.value }
    : { ...('base' in record ? { base:record.base } : {}), ...(Array.isArray(record.sent) ? { sent:record.sent } : {}) };
  writeLocal(localKey(part), { value, dirty:true, stamp:`${Date.now()}-${++changeCounter}`, ...base });
  scheduleStateSync(0);
}

function scheduleStateSync(delay) {
  clearTimeout(stateSyncTimer);
  stateSyncTimer = setTimeout(syncAccountState, delay);
}

// Resolves to the server's state once these changes are merged into it, or null if nothing went up.
async function syncAccountState() {
  clearTimeout(stateSyncTimer);
  // Only once the signed-in account is known, so a copy kept for another account is never sent to this one.
  await window.localReady;
  if (stateSyncing) return null;
  const dirty = accountStateParts.map(part => [part, readLocalState(part)]).filter(([, record]) => record && record.dirty);
  if (!dirty.length) return null;
  stateSyncing = true;
  let merged = null;
  try {
    const body = Object.fromEntries(dirty.map(([part, record]) => {
      const fill = accountStateFill[part] || (value => value);
      // Copies sent before without an answer go too: the server may have stored them (see merge_values in server.py).
      const unanswered = 'base' in record && Array.isArray(record.sent) && record.sent.length ? { sent:record.sent.map(fill) } : {};
      return [part, { value:fill(record.value), ...('base' in record ? { base:fill(record.base) } : {}), ...unanswered }];
    }));
    // Noted before it goes, since its answer may never come (the page closed, the connection dropped) though the server
    // stored it: a change made after it, even one back to how things were, is then still told apart from the base.
    dirty.forEach(([part, record]) => {
      if ('base' in record) writeLocal(localKey(part), { ...record, sent:[...(Array.isArray(record.sent) ? record.sent : []), record.value].slice(-5) });
    });
    const response = await syncFetch('/api/state', { method:'PATCH', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body) });
    if (!response.ok) throw new Error(`Settings sync failed (${response.status}).`);
    merged = await response.json().catch(() => null);
    dirty.forEach(([part, record]) => {
      const latest = readLocalState(part);
      if (!latest) return;
      // Unchanged since it went up: clean, and what the next change starts from. The copy here stays as this page knows
      // it, rather than taking the server's merged one under it; the next page load brings that.
      if (latest.stamp === record.stamp) writeLocal(localKey(part), { value:latest.value, dirty:false, stamp:latest.stamp });
      // Changed while it went up: still to go, now from what just went, so the next upload carries only what came after.
      else {
        const { sent, ...waiting } = latest;
        writeLocal(localKey(part), { ...waiting, base:record.value });
      }
    });
    stateRetryCount = 0;
  } catch (error) {
    console.error('Unable to sync settings or templates; they are saved on this device and will be retried.', error);
    stateRetryCount += 1;
  } finally {
    stateSyncing = false;
  }
  if (accountStateParts.some(part => readLocalState(part)?.dirty)) scheduleStateSync(stateRetryCount ? Math.min(60000, 2000 * 2 ** (stateRetryCount - 1)) : 0);
  return merged;
}

// Resolves to { settings, templates, program } for the signed-in account: a part changed here and not uploaded yet keeps the
// local value, anything else takes the server's, and with the server unreachable the local copy (or null) is used.
async function loadAccountState() {
  await window.localReady;
  const stampsBefore = Object.fromEntries(accountStateParts.map(part => [part, readLocalState(part)?.stamp]));
  // Changes still waiting go up first, so the copy loaded is the server's merge of them with any made elsewhere, rather
  // than this device's, which would hide the other device's until the next load. Its answer is that merged copy.
  let server = accountStateParts.some(part => readLocalState(part)?.dirty) ? await syncAccountState() : null;
  if (!server) {
    try {
      const response = await syncFetch('/api/state');
      if (response.ok) server = await response.json();
    } catch (error) {
      console.error('Unable to load settings and templates; using the copy on this device.', error);
    }
  }
  const state = {};
  accountStateParts.forEach(part => {
    const local = readLocalState(part);
    // Also keep a local change made while the request was out, even one already uploaded: the reply may predate it.
    const changedMeanwhile = (local?.stamp) !== stampsBefore[part];
    if (server && part in server && !(local && (local.dirty || changedMeanwhile))) {
      writeLocal(localKey(part), { value:server[part], dirty:false, stamp:`${Date.now()}-${++changeCounter}` });
      state[part] = server[part];
    } else {
      state[part] = local ? local.value : null;
    }
  });
  syncAccountState();
  noteStateStamps();
  return state;
}

// ---- Changes from another tab ---------------------------------------------
// Each page keeps the parts it shows in memory (customTemplates, goals, the notes...) and saves a change from there, while
// the base the change goes up with is read from the stored copy. Another tab (or the installed app beside a browser tab)
// storing a change meanwhile left this page's copy without it and the base with it, so the server took the gap as this page
// deleting it (merge_values). So when the stored copy changes under a page, the page is told, with an 'accountstatechange'
// naming the parts, and takes them in as it takes the server's copy on loading: at once, on the browser's storage event,
// and on coming back into view, for a page the browser froze in the background meanwhile. A stamp is a stored copy's
// identity (a new one with every change), so a part counts as changed when its stamp is not the one this page last knew:
// written here (writeLocal notes those) or taken in. knownStateStamps is declared at the top, as writeLocal reads it.

function noteStateStamps() {
  accountStateParts.forEach(part => knownStateStamps.set(localKey(part), readLocalState(part)?.stamp));
}

function takeOtherTabsChanges() {
  if (localAccountForgotten) return;
  const parts = accountStateParts.filter(part => knownStateStamps.has(localKey(part)) && knownStateStamps.get(localKey(part)) !== readLocalState(part)?.stamp);
  if (!parts.length) return;
  noteStateStamps();
  window.dispatchEvent(new CustomEvent('accountstatechange', { detail:{ parts } }));
}

window.addEventListener('storage', event => { if (event.key === null || event.key.startsWith('workout-tracker-')) takeOtherTabsChanges(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) takeOtherTabsChanges(); });

// Everything kept on this device for the signed-in account, once that account has been deleted: its copies are of
// nothing now, and anything still waiting to upload has nowhere to go.
function forgetLocalAccount() {
  localAccountForgotten = true;
  [activeSyncTimer, pendingRetryTimer, stateSyncTimer].forEach(clearTimeout);
  const suffix = `-${localUserId}`;
  [...memoryStore.keys()].filter(key => key.endsWith(suffix)).forEach(key => memoryStore.delete(key));
  try {
    Object.keys(localStorage).filter(key => key.startsWith('workout-tracker-') && key.endsWith(suffix)).forEach(key => localStorage.removeItem(key));
    if (JSON.parse(localStorage.getItem(lastUserStorageKey)) === localUserId) localStorage.removeItem(lastUserStorageKey);
  } catch (error) {
    // No storage: nothing was kept.
  }
}

// ---- Status ---------------------------------------------------------------

// Finished workouts still queued plus an in-progress workout the server has not seen the latest version of.
function unsyncedWorkCount() {
  const active = readLocalActive();
  return readPendingWorkouts().length + (active && active.dirty && active.session ? 1 : 0);
}

function syncNow() {
  syncActiveSession();
  flushPendingWorkouts();
  syncAccountState();
}

window.addEventListener('online', syncNow);
document.addEventListener('visibilitychange', () => { if (!document.hidden) syncNow(); });
