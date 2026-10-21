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
    announceRestOver();
  }
}

// For anyone who cannot see the flash or hear the sound: a line a screen reader says, which stays in the page (a region that was
// hidden when its words changed is not read) and is emptied when a rest runs, so the same words change again. The
// big view is a modal dialog, so the page behind it is not read while it is open: it has a line of its own. Only the countdown
// reaching nothing says it; ending a rest, or taking it to nothing, is something the person just did.
function announceRestOver() {
  const inBigView = typeof bigViewIsOpen === 'function' && bigViewIsOpen();
  $(inBigView ? 'bigViewAnnouncement' : 'restAnnouncement').textContent = 'Rest over';
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
  $('restAnnouncement').textContent = $('bigViewAnnouncement').textContent = '';
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
// On a phone the rest is End rest and Pause rest with ··· beside them, which opens Fix last set and Restart rest in a row under (on a wide
// screen all four show, and ··· does not). Choosing one closes it again, so the panel is as small as it can be while the page is in use.
function showRestMore(open) {
  $('restMoreBtn').setAttribute('aria-expanded', String(open));
  $('restPanel').classList.toggle('more-open', open);
}
$('restMoreBtn').onclick = () => showRestMore($('restMoreBtn').getAttribute('aria-expanded') !== 'true');
$('restMoreItems').addEventListener('click', e => { if (e.target.closest('button')) showRestMore(false); });
$('restAdjust').onclick = e => {
  const button = e.target.closest('[data-rest-adjust]');
  if (!button) return;
  unlockAudio();
  adjustRest(Number(button.dataset.restAdjust));
};

// A phone often closes an app left locked through a rest, and the page that opens again would have no rest on show: the
// countdown lives in this page. So whenever the page is put away, the rest on show is kept on this device (it is this
// device's, so it is not uploaded with the workout), with which workout and set it follows; showSavedSession puts it back
// when the same workout comes back with nothing logged since. The end time is a clock time, so a rest that ran on while
// the page was gone comes back with the time it has left, or over.
function restSetCount(session) {
  return session.exercises.reduce((total, item) => total + (item.sets?.length || 0), 0);
}

function rememberRest() {
  if (typeof activeSession === 'undefined') return;
  const shown = activeSession && !$('restPanel').hidden;
  writeLocal(localKey('rest'), shown ? {
    startedAt:activeSession.startedAt, index:activeSession.currentIndex, sets:restSetCount(activeSession),
    endsAt:restInterval ? restEndsAt : null, remaining:restRemaining, total:restTotal,
  } : null);
}

// Puts back the rest kept by rememberRest, if it follows the last set of the workout now on show. Running, it runs on to its
// end time; paused, it keeps the time it had; over while the page was gone, it shows 0:00, as a page left open would have,
// without an alert that would come late.
function restoreRest() {
  const saved = readLocal(localKey('rest'));
  if (!saved || !activeSession || saved.startedAt !== activeSession.startedAt || saved.index !== activeSession.currentIndex
    || saved.sets !== restSetCount(activeSession)) return;
  restTotal = Number(saved.total) || 0;
  $('restPanel').hidden = false;
  if (saved.endsAt) {
    restRemaining = Math.max(0, Math.ceil((saved.endsAt - Date.now()) / 1000));
    if (restRemaining > 0) {
      runRestTimer();
      restEndsAt = saved.endsAt;
    }
  } else {
    restRemaining = Math.max(0, Number(saved.remaining) || 0);
  }
  updateRestTimer();
}

// A phone that is locked or in another app does not run the page, so it cannot sound the alert at the end of a rest. If this device has
// rest alerts on (reminders.js), the server is told, as the page is hidden, how many seconds the rest has left, and sends the
// notification when they are up; and told to forget it when the page is back on screen, which sounds its own alert. Only while the
// page is hidden: on screen, the page's alert and a notification would be two for one rest, and a notification where the app is in
// front is the kind iOS punishes. The time is seconds left, not a time of day, since the phone's clock and the server's differ.
let restAlertAsked = false;

function askRestAlert(seconds) {
  const endpoint = typeof restAlertEndpoint === 'function' ? restAlertEndpoint() : '';
  if (!endpoint) return;
  // keepalive lets it leave even as the page goes; the endpoint is kept where it can be read at once, since there is no time to ask
  // the browser for it.
  syncFetch('/api/push/rest', { method:'POST', keepalive:true, headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ endpoint, seconds }) })
    .catch(error => console.error('Unable to tell the server about the rest alert.', error));
}

function pageHiddenWithRest() {
  if (restAlertAsked || !restInterval || restEndsAt === null) return;
  const left = Math.floor((restEndsAt - Date.now()) / 1000);
  if (left < 2) return;
  restAlertAsked = true;
  askRestAlert(left);
}

function pageBackWithRest() {
  if (!restAlertAsked) return;
  restAlertAsked = false;
  askRestAlert(null);
  // One that came while the page was away is of no use now it is back.
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(registration => registration.getNotifications({ tag:'rest-over' }))
      .then(shown => shown.forEach(notification => notification.close())).catch(() => {});
  }
}

window.addEventListener('pagehide', () => { rememberRest(); pageHiddenWithRest(); });

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { rememberRest(); pageHiddenWithRest(); } else pageBackWithRest();
  // Back from a locked screen or another app, an iPhone's sound is interrupted; it is woken before the rest catches up.
  if (!document.hidden) wakeAudio();
  if (!document.hidden && restInterval) tickRest();
  if (!document.hidden && holdInterval) tickHold();
  syncWakeLock();
});
