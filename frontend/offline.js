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

// Falls back to memory when localStorage is unavailable, so syncing still works (it just cannot survive a reload).
function readLocal(key) {
  if (memoryStore.has(key)) return memoryStore.get(key);
  try { return JSON.parse(localStorage.getItem(key)); }
  catch (error) { return null; }
}

function writeLocal(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    memoryStore.delete(key);
  } catch (error) {
    memoryStore.set(key, value);
  }
}

function localKey(name) {
  return `workout-tracker-${name}-${localUserId ?? 'unknown'}`;
}

function syncFetch(path, options = {}, timeout = 10000) {
  const signal = typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(timeout) : undefined;
  return fetch(path, { ...options, signal });
}

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

// Resolves true once nothing is left to upload, false if the server could not be reached (a retry is scheduled).
function flushPendingWorkouts() {
  if (pendingFlush) return pendingFlush;
  clearTimeout(pendingRetryTimer);
  pendingFlush = (async () => {
    await window.localReady;
    let uploaded = 0;
    let queue = readPendingWorkouts();
    while (queue.length) {
      let rejected = false;
      try {
        const response = await syncFetch('/api/workouts', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(queue[0]) });
        // 400 and 413 say this workout can never be accepted as it is; anything else may succeed on a retry.
        rejected = response.status === 400 || response.status === 413;
        if (rejected) console.error(`The server refused a finished workout (${response.status}); it is kept on this device.`, await response.text());
        else if (!response.ok) throw new Error(`Workout sync failed (${response.status}).`);
      } catch (error) {
        console.error('Unable to sync finished workout; it is saved on this device and will be retried.', error);
        pendingRetryCount += 1;
        pendingRetryTimer = setTimeout(flushPendingWorkouts, Math.min(60000, 2000 * 2 ** (pendingRetryCount - 1)));
        reportSyncStatus(uploaded);
        return false;
      }
      if (rejected) writeLocal(localKey('rejected'), [...readRejectedWorkouts(), queue[0]]);
      writeLocal(localKey('pending'), readPendingWorkouts().slice(1));
      pendingRetryCount = 0;
      if (!rejected) uploaded += 1;
      if (rejected) reportSyncStatus();
      queue = readPendingWorkouts();
    }
    if (uploaded) reportSyncStatus(uploaded);
    return true;
  })().finally(() => { pendingFlush = null; });
  return pendingFlush;
}

// ---- Settings, custom templates and the training program -----------------
// The same rule as the in-progress workout: a change is saved on this device first and stays marked dirty until the
// server has it, and a dirty local copy beats the server's when a page loads, so a change made offline is never undone.
const accountStateParts = ['settings', 'templates', 'program'];

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
  writeLocal(localKey(part), { value, dirty:true, stamp:`${Date.now()}-${++changeCounter}` });
  scheduleStateSync(0);
}

function scheduleStateSync(delay) {
  clearTimeout(stateSyncTimer);
  stateSyncTimer = setTimeout(syncAccountState, delay);
}

async function syncAccountState() {
  clearTimeout(stateSyncTimer);
  // Only once the signed-in account is known, so a copy kept for another account is never sent to this one.
  await window.localReady;
  if (stateSyncing) return;
  const dirty = accountStateParts.map(part => [part, readLocalState(part)]).filter(([, record]) => record && record.dirty);
  if (!dirty.length) return;
  stateSyncing = true;
  try {
    const body = Object.fromEntries(dirty.map(([part, record]) => [part, record.value]));
    const response = await syncFetch('/api/state', { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body) });
    if (!response.ok) throw new Error(`Settings sync failed (${response.status}).`);
    dirty.forEach(([part, record]) => {
      const latest = readLocalState(part);
      if (latest && latest.stamp === record.stamp) writeLocal(localKey(part), { ...latest, dirty:false });
    });
    stateRetryCount = 0;
  } catch (error) {
    console.error('Unable to sync settings or templates; they are saved on this device and will be retried.', error);
    stateRetryCount += 1;
  } finally {
    stateSyncing = false;
  }
  if (accountStateParts.some(part => readLocalState(part)?.dirty)) scheduleStateSync(stateRetryCount ? Math.min(60000, 2000 * 2 ** (stateRetryCount - 1)) : 0);
}

// Resolves to { settings, templates, program } for the signed-in account: a part changed here and not uploaded yet keeps the
// local value, anything else takes the server's, and with the server unreachable the local copy (or null) is used.
async function loadAccountState() {
  await window.localReady;
  const stampsBefore = Object.fromEntries(accountStateParts.map(part => [part, readLocalState(part)?.stamp]));
  let server = null;
  try {
    const response = await syncFetch('/api/state');
    if (response.ok) server = await response.json();
  } catch (error) {
    console.error('Unable to load settings and templates; using the copy on this device.', error);
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
  return state;
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
