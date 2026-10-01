// The rest timer between sets, the hold timer for a set of a timed exercise (a plank), and the screen wake lock that keeps
// them in sight. Loaded on the Tracker after program.js and before script.js, which starts the page.

let restInterval = null;
let restEndsAt = null;
let wakeLock = null;
let wakeLockRequesting = false;
let restRemaining = getWorkoutSettings().restDuration;
// The length this rest started at (or was stretched to), for the bar that drains along the panel.
let restTotal = restRemaining;
// The countdown for a set of a timed exercise, from an end time like the rest timer's.
let holdInterval = null;
let holdEndsAt = null;
let holdLength = 0;

function updateRestTimer() {
  $('timerDisplay').textContent = clockTime(restRemaining);
  restTotal = Math.max(restTotal, restRemaining);
  $('restEndBtn').disabled = restRemaining <= 0;
  $('restPanel').style.setProperty('--rest-left', restTotal ? restRemaining / restTotal : 0);
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
    flashRestOver();
  }
}

// A soft green wash over the whole screen, once, so the end of the rest shows even with the sound off. Skipped for anyone
// who asks for less motion.
function flashRestOver() {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const flash = document.createElement('div');
  flash.className = 'rest-flash';
  flash.setAttribute('aria-hidden', 'true');
  document.body.appendChild(flash);
  flash.addEventListener('animationend', () => flash.remove());
  setTimeout(() => flash.remove(), 1500);
}

// End rest: skips what is left. You asked for it, so no alert sounds, but the flash confirms the rest is over.
function endRest() {
  if (restRemaining <= 0) return;
  stopRestTimer();
  restRemaining = 0;
  updateRestTimer();
  flashRestOver();
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
  restRemaining = restTotal = restDuration();
  $('restPanel').hidden = false;
  updateRestTimer();
  runRestTimer();
}

// Keeps the screen awake during a workout so the timer can alert you; the browser drops the lock whenever the page is
// hidden. Where it has no Wake Lock to give (any page at a plain http:// address), or refuses one, a silent video does
// the job instead, unless Settings turns that off.
async function syncWakeLock() {
  // The server's settings can arrive (settingschange) before script.js, which declares activeSession, has run.
  const onScreen = typeof activeSession !== 'undefined' && Boolean(activeSession) && !document.hidden;
  if (!('wakeLock' in navigator)) {
    keepAwakeInstead(onScreen);
    return;
  }
  if (onScreen && !wakeLock && !wakeLockRequesting) {
    wakeLockRequesting = true;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
      playKeepAwakeVideo(false);
      showScreenAwakeNotice(false);
    } catch (error) {
      console.error('Unable to keep the screen awake.', error);
      keepAwakeInstead(Boolean(activeSession) && !document.hidden);
    } finally {
      wakeLockRequesting = false;
    }
  } else if (!onScreen && wakeLock) {
    await wakeLock.release();
  }
  if (!onScreen) playKeepAwakeVideo(false);
  if (!activeSession) showScreenAwakeNotice(false);
}

// The screen kept on without a Wake Lock: the video while a workout is on screen, and the note saying how it stands.
function keepAwakeInstead(onScreen) {
  const video = getWorkoutSettings().keepAwakeVideo !== false;
  playKeepAwakeVideo(onScreen && video);
  showScreenAwakeNotice(Boolean(activeSession), video);
}

// The way NoSleep.js keeps a phone awake: a phone does not sleep while a video plays. The video is two seconds of
// black, muted, so it never takes the audio from music; it carries a silent sound track all the same, since Safari lets
// the screen sleep under a video with no sound at all. Nor does it loop, which Safari also lets the screen sleep under:
// it is sent back to its start before it ends instead. Made with
//   ffmpeg -f lavfi -i color=c=black:s=16x16:r=10:d=2 -f lavfi -i anullsrc=channel_layout=mono:sample_rate=8000 -t 2
//     -c:v libx264 -profile:v baseline -pix_fmt yuv420p -c:a aac -b:a 8k -movflags +faststart media/keep-awake.mp4
let keepAwakeVideo = null;

function playKeepAwakeVideo(on) {
  if (!on) {
    if (keepAwakeVideo && !keepAwakeVideo.paused) keepAwakeVideo.pause();
    return;
  }
  if (!keepAwakeVideo) {
    keepAwakeVideo = document.createElement('video');
    keepAwakeVideo.muted = true;
    keepAwakeVideo.setAttribute('muted', '');
    keepAwakeVideo.setAttribute('playsinline', '');
    keepAwakeVideo.setAttribute('title', 'Keeping the screen on');
    keepAwakeVideo.src = '/media/keep-awake.mp4';
    keepAwakeVideo.addEventListener('timeupdate', () => { if (keepAwakeVideo.currentTime > 1) keepAwakeVideo.currentTime = 0; });
  }
  // Refused (a phone in Low Power Mode, or before any tap): logging the next set asks again.
  Promise.resolve(keepAwakeVideo.play()).catch(() => {});
}

// A page cannot run while the phone is locked, so a rest that outlasts the phone's auto-lock ends in silence. Browsers
// only keep the screen on over HTTPS (or on localhost), which a server at a plain http:// address is not, so there the
// workout says what is being done about it, and what to do if the phone locks all the same.
function showScreenAwakeNotice(show, video = false) {
  const notice = $('screenAwakeNotice');
  if (show) {
    const advice = 'Keep the screen awake while you rest (on an iPhone, set Auto-Lock to Never while you train)';
    if (video) {
      notice.textContent = window.isSecureContext
        ? `This browser will not keep the screen on, so the app plays a silent video to do it. If your phone still locks during a rest, a locked phone cannot sound the rest alert: ${advice.charAt(0).toLowerCase()}${advice.slice(1)}.`
        : 'Over a plain http:// address the browser will not keep the screen on, so the app plays a silent video to do it. '
          + `If your phone still locks during a rest, a locked phone cannot sound the rest alert: ${advice.charAt(0).toLowerCase()}${advice.slice(1)}, or reach the app over HTTPS.`;
    } else {
      notice.textContent = window.isSecureContext
        ? `This browser will not keep the screen on, and a locked phone cannot sound the rest alert. ${advice}.`
        : `Over a plain http:// address the app cannot keep the screen on, and a locked phone cannot sound the rest alert. ${advice}, or reach the app over HTTPS, where it does this itself.`;
    }
  }
  notice.hidden = !show;
}

window.addEventListener('settingschange', () => syncWakeLock());

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
    if (restRemaining <= 0) restRemaining = restTotal = restDuration();
    updateRestTimer();
    runRestTimer();
  }
};
$('restEndBtn').onclick = endRest;
$('restResetBtn').onclick = () => { stopRestTimer(); restRemaining = restTotal = restDuration(); updateRestTimer(); };
$('restAdjust').onclick = e => {
  const button = e.target.closest('[data-rest-adjust]');
  if (!button) return;
  unlockAudio();
  adjustRest(Number(button.dataset.restAdjust));
};

document.addEventListener('visibilitychange', () => {
  // Back from a locked screen or another app, an iPhone's sound is interrupted; it is woken before the rest catches up.
  if (!document.hidden) wakeAudio();
  if (!document.hidden && restInterval) tickRest();
  if (!document.hidden && holdInterval) tickHold();
  syncWakeLock();
});
