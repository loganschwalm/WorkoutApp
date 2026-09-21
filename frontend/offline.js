// Local-first persistence. The in-progress workout and finished workouts that have not reached the server yet are
// written to localStorage (per account) first, then pushed to the server in the background and retried until it accepts them.
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
  window.dispatchEvent(new CustomEvent('syncchange', { detail:{ pendingWorkouts:readPendingWorkouts().length, activeOffline:activeSyncFailed, uploaded } }));
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

// Resolves true once nothing is left to upload, false if the server could not be reached (a retry is scheduled).
function flushPendingWorkouts() {
  if (pendingFlush) return pendingFlush;
  clearTimeout(pendingRetryTimer);
  pendingFlush = (async () => {
    await window.localReady;
    let uploaded = 0;
    let queue = readPendingWorkouts();
    while (queue.length) {
      try {
        const response = await syncFetch('/api/workouts', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(queue[0]) });
        if (!response.ok) throw new Error(`Workout sync failed (${response.status}).`);
      } catch (error) {
        console.error('Unable to sync finished workout; it is saved on this device and will be retried.', error);
        pendingRetryCount += 1;
        pendingRetryTimer = setTimeout(flushPendingWorkouts, Math.min(60000, 2000 * 2 ** (pendingRetryCount - 1)));
        reportSyncStatus(uploaded);
        return false;
      }
      writeLocal(localKey('pending'), readPendingWorkouts().slice(1));
      pendingRetryCount = 0;
      uploaded += 1;
      queue = readPendingWorkouts();
    }
    if (uploaded) reportSyncStatus(uploaded);
    return true;
  })().finally(() => { pendingFlush = null; });
  return pendingFlush;
}

// Finished workouts still queued plus an in-progress workout the server has not seen the latest version of.
function unsyncedWorkCount() {
  const active = readLocalActive();
  return readPendingWorkouts().length + (active && active.dirty && active.session ? 1 : 0);
}

function syncNow() {
  syncActiveSession();
  flushPendingWorkouts();
}

window.addEventListener('online', syncNow);
document.addEventListener('visibilitychange', () => { if (!document.hidden) syncNow(); });
