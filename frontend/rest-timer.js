// The rest timer between sets, the hold timer for a set of a timed exercise (a plank), and the screen wake lock that keeps
// them in sight. Loaded on the Tracker after program.js and before script.js, which starts the page.

let restInterval = null;
let restEndsAt = null;
let wakeLock = null;
let wakeLockRequesting = false;
let restRemaining = getWorkoutSettings().restDuration;
// The countdown for a set of a timed exercise, from an end time like the rest timer's.
let holdInterval = null;
let holdEndsAt = null;
let holdLength = 0;

function updateRestTimer() {
  $('timerDisplay').textContent = clockTime(restRemaining);
}

// The rest after a set: the current exercise's own (a program gives main lifts longer than accessories, and a template
// can set one), or else the default from Settings.
function restDuration() {
  const exercise = activeSession ? activeSession.exercises[activeSession.currentIndex] : null;
  const own = Number(exercise?.rest);
  return own > 0 ? own : getWorkoutSettings().restDuration;
}

// The countdown is derived from an end timestamp, not from counting ticks, so it stays correct when the browser
// throttles timers (locked screen, background tab) and catches up as soon as the page runs again.
function syncRestRemaining() {
  if (restEndsAt !== null) restRemaining = Math.max(0, Math.ceil((restEndsAt - Date.now()) / 1000));
}

function tickRest() {
  syncRestRemaining();
  updateRestTimer();
  if (restRemaining <= 0) {
    stopRestTimer();
    playRestAlert(getWorkoutSettings());
  }
}

function runRestTimer() {
  clearInterval(restInterval);
  restEndsAt = Date.now() + restRemaining * 1000;
  $('restToggleBtn').textContent = 'Pause rest';
  restInterval = setInterval(tickRest, 250);
}

function stopRestTimer() {
  clearInterval(restInterval);
  restInterval = null;
  restEndsAt = null;
  $('restToggleBtn').textContent = 'Start rest';
}

// −30s and +30s: more rest after a heavy set, less after an easy one, running or paused. Running, it moves the end time
// itself (so a part-second is kept), and taking it down to nothing ends the rest quietly: you asked for it, so no alert.
const REST_ADJUST_LIMIT = 60 * 60;

function adjustRest(seconds) {
  if (restInterval) {
    restEndsAt = Math.min(Date.now() + REST_ADJUST_LIMIT * 1000, restEndsAt + seconds * 1000);
    syncRestRemaining();
    if (restRemaining <= 0) stopRestTimer();
  } else {
    restRemaining = Math.min(REST_ADJUST_LIMIT, Math.max(0, restRemaining + seconds));
  }
  updateRestTimer();
}

function startRestTimer() {
  restRemaining = restDuration();
  $('restPanel').hidden = false;
  updateRestTimer();
  runRestTimer();
}

// Keeps the screen awake during a workout so the timer can alert you; the browser drops the lock whenever the page is hidden.
async function syncWakeLock() {
  const wanted = Boolean(activeSession) && !document.hidden && 'wakeLock' in navigator;
  if (wanted && !wakeLock && !wakeLockRequesting) {
    wakeLockRequesting = true;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (error) {
      console.error('Unable to keep the screen awake.', error);
    } finally {
      wakeLockRequesting = false;
    }
  } else if (!wanted && wakeLock) {
    await wakeLock.release();
  }
}

// ---- Timed exercises --------------------------------------------------------
// A set of a timed exercise is a hold. Start timer counts down the seconds in the Seconds field; when they are up it
// sounds the rest alert and logs the set by itself, since hands are busy holding the plank. Stop (or Complete set)
// ends it early, filling in the seconds actually held.
function holdRemaining() {
  return Math.max(0, Math.ceil((holdEndsAt - Date.now()) / 1000));
}

function syncHoldDisplay() {
  if (!holdInterval) $('holdDisplay').textContent = clockTime(Math.max(0, Math.floor(Number($('completedReps').value)) || 0));
}

function tickHold() {
  const left = holdRemaining();
  $('holdDisplay').textContent = clockTime(left);
  if (left > 0) return;
  stopHold();
  playRestAlert(getWorkoutSettings());
  $('completedReps').value = String(holdLength);
  logSet();
}

function startHold() {
  const length = Math.floor(Number($('completedReps').value));
  if (!(length >= 1)) { showFeedback('Enter the seconds to hold, then start the timer.'); $('completedReps').focus(); return; }
  clearFeedback();
  unlockAudio();
  // The rest is over once the next set starts.
  stopRestTimer();
  $('restPanel').hidden = true;
  holdLength = length;
  holdEndsAt = Date.now() + length * 1000;
  $('holdBtn').textContent = 'Stop';
  $('holdTimer').classList.add('running');
  clearInterval(holdInterval);
  holdInterval = setInterval(tickHold, 250);
  tickHold();
}

// Stopped by hand (early), the seconds held so far are filled in; stopped because the workout moved on, nothing is.
function stopHold(early = false) {
  if (!holdInterval) return;
  clearInterval(holdInterval);
  holdInterval = null;
  if (early) $('completedReps').value = String(Math.max(1, holdLength - holdRemaining()));
  holdEndsAt = null;
  $('holdBtn').textContent = 'Start timer';
  $('holdTimer').classList.remove('running');
  syncHoldDisplay();
}

$('holdBtn').onclick = () => { if (holdInterval) stopHold(true); else startHold(); };

$('restToggleBtn').onclick = () => {
  unlockAudio();
  if (restInterval) { syncRestRemaining(); updateRestTimer(); stopRestTimer(); }
  else {
    if (restRemaining <= 0) restRemaining = restDuration();
    updateRestTimer();
    runRestTimer();
  }
};
$('restResetBtn').onclick = () => { stopRestTimer(); restRemaining = restDuration(); updateRestTimer(); };
$('restAdjust').onclick = e => {
  const button = e.target.closest('[data-rest-adjust]');
  if (!button) return;
  unlockAudio();
  adjustRest(Number(button.dataset.restAdjust));
};

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && restInterval) tickRest();
  if (!document.hidden && holdInterval) tickHold();
  syncWakeLock();
});
