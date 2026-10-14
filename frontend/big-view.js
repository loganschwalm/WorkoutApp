// The big view: the set to do and the rest timer in very large type on a plain high-contrast screen, to read from a few feet
// away with the phone propped on a bench. It is only a view of the Tracker's own workout: every number is the page's text
// (the rest clock, the hold clock, the weight and reps the entry fields hold, which is what Complete set will log), and every
// button presses the page's own button, so the rules for a set, a rest or a superset are the page's, in one place.
//
// It does not touch how the screen is kept awake: that is rest-timer.js's, and goes on while a workout is on screen, whatever
// is drawn over it. A web page cannot draw on the lock screen, so this is for the screen kept on, not a locked one. Loaded
// after script.js, which declares the workout it reads; nothing here reads it until it is opened.

let bigViewTimer = null;

function bigViewIsOpen() {
  return !$('bigView').hidden;
}

// Each is set only when it has changed, so a quarter-second of polling neither rebuilds the view nor moves the focus.
function setBigText(id, text) {
  const element = $(id);
  if (element.textContent !== text) element.textContent = text;
}

function setBigHidden(id, hidden) {
  const element = $(id);
  if (element.hidden !== hidden) element.hidden = hidden;
}

// What the view says, from the workout as it stands. `kind` is what its big button does.
function bigViewState() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const sets = exercise.sets || [];
  const plan = Array.isArray(exercise.plan) && exercise.plan.length ? exercise.plan : null;
  const timed = isTimed(exercise);
  const holding = holdInterval !== null;
  const restShown = !$('restPanel').hidden;
  // A rest still to go (running or paused), or one that has just run out and is waiting for the set.
  const resting = !holding && restShown && restRemaining > 0;
  const over = !holding && restShown && restRemaining <= 0;
  const finished = Boolean(plan) && sets.length >= plan.length;
  const kind = holding || timed ? 'hold' : finished ? 'next' : 'complete';
  return { exercise, sets, plan, timed, holding, resting, over, finished, kind };
}

function bigViewNumbers(state) {
  const reps = $('completedReps').value.trim();
  if (!reps) return '';
  if (state.timed) return `${reps} s`;
  const weight = $('activeWeight').value.trim();
  return Number(weight) > 0 ? `${formatWeight(weight)} ${weightUnit()} × ${reps}` : `${reps} ${Number(reps) === 1 ? 'rep' : 'reps'}`;
}

function renderBigView() {
  if (!bigViewIsOpen()) return;
  // The workout ended (finished, cancelled or taken back) with the view open.
  if (!activeSession) { closeBigView(false); return; }
  const state = bigViewState();
  const view = $('bigView');
  view.classList.toggle('resting', state.resting);
  view.classList.toggle('go', state.over);
  setBigText('bigViewExercise', $('activeExerciseName').textContent);
  setBigText('bigViewProgress', `${$('activeWorkoutProgress').textContent} · ${activeSession.name}`);
  // The clock is the hold's while one is being held, otherwise the rest's; the page's own text for either.
  const label = state.holding ? 'Hold' : state.resting ? (restInterval ? 'Rest' : 'Rest · paused') : state.over ? 'Rest over' : '';
  setBigText('bigViewLabel', label);
  setBigHidden('bigViewLabel', !label);
  setBigText('bigViewClock', state.holding ? $('holdDisplay').textContent : $('timerDisplay').textContent);
  setBigHidden('bigViewClock', !(state.holding || state.resting));
  setBigHidden('bigViewBar', !state.resting);
  if (state.resting) $('bigViewBar').style.setProperty('--rest-left', restTotal ? restRemaining / restTotal : 0);
  const number = state.sets.length + 1;
  setBigText('bigViewSet', state.finished ? 'All sets done'
    : `${state.resting ? 'Next: ' : ''}Set ${number}${state.plan ? ` of ${state.plan.length}` : ''}`);
  const numbers = state.finished || state.holding ? '' : bigViewNumbers(state);
  setBigText('bigViewNumbers', numbers);
  setBigHidden('bigViewNumbers', !numbers);
  // What the set would be a record of (reach.js), as the page says it under the exercise.
  const reach = state.finished || state.holding || $('reachHint').hidden ? '' : $('reachHint').textContent;
  setBigText('bigViewReach', reach);
  setBigHidden('bigViewReach', !reach);
  const primary = $('bigViewPrimary');
  primary.dataset.kind = state.kind;
  setBigText('bigViewPrimary', state.kind === 'hold' ? $('holdBtn').textContent : state.kind === 'next' ? $('nextExerciseBtn').textContent : 'Complete set');
  setBigHidden('bigViewRest', !state.resting);
  setBigText('bigViewToggle', $('restToggleBtn').textContent);
}

function openBigView() {
  if (!activeSession || bigViewIsOpen()) return;
  $('bigView').hidden = false;
  document.body.classList.add('big-view-open');
  renderBigView();
  clearInterval(bigViewTimer);
  bigViewTimer = setInterval(renderBigView, 250);
  $('bigViewPrimary').focus();
}

// `restoreFocus` is false when the workout is gone, and with it the button that opened the view.
function closeBigView(restoreFocus = true) {
  if (!bigViewIsOpen()) return;
  clearInterval(bigViewTimer);
  bigViewTimer = null;
  $('bigView').hidden = true;
  document.body.classList.remove('big-view-open');
  if (restoreFocus) $('bigViewBtn').focus();
}

// The big button does what the page's own button does, pressed here so it counts as a tap (the rest alert's sound is unlocked
// by one). A set the page will not take (no reps, or an implausible weight declined) is the page's to say, with its field in
// reach, so the view gets out of the way. A tap just after a set was logged is a thumb bouncing (bouncedTap in script.js), and
// is ignored whatever the button has become since: Complete set again, or Next exercise once the last planned set is done.
$('bigViewPrimary').onclick = event => {
  if (!activeSession || bouncedTap(event)) return;
  const state = bigViewState();
  // What the button said when it was tapped, which a quarter-second of change since cannot alter.
  const kind = $('bigViewPrimary').dataset.kind;
  if (kind === 'hold') {
    // Starting a hold needs its seconds, which the page asks for beside the field.
    if (!state.holding && !(Math.floor(Number($('completedReps').value)) >= 1)) closeBigView();
    $('holdBtn').click();
  } else if (kind === 'next') {
    // The last exercise's button finishes the workout, whose summary is on the page.
    if ($('nextExerciseBtn').textContent === 'Finish workout') closeBigView();
    $('nextExerciseBtn').click();
  } else {
    if (setEntryProblem(readSetEntry(), state.timed)) closeBigView();
    $('completeSetBtn').click();
    if ($('completedReps').getAttribute('aria-invalid') === 'true' || $('activeWeight').getAttribute('aria-invalid') === 'true') closeBigView();
  }
  renderBigView();
};

$('bigViewRest').onclick = event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.bigRest) $('restAdjust').querySelector(`[data-rest-adjust="${button.dataset.bigRest}"]`).click();
  else if (button.id === 'bigViewToggle') $('restToggleBtn').click();
  else if (button.id === 'bigViewSkip') $('restEndBtn').click();
  renderBigView();
};

$('bigViewBtn').onclick = openBigView;
$('bigViewClose').onclick = () => closeBigView();

// Escape closes it, and Tab stays inside it: the page behind is not to be reached from here.
document.addEventListener('keydown', event => {
  if (!bigViewIsOpen()) return;
  if (event.key === 'Escape') { closeBigView(); return; }
  if (event.key !== 'Tab') return;
  const buttons = [...$('bigView').querySelectorAll('button')].filter(button => !button.disabled && !button.closest('[hidden]'));
  if (!buttons.length) return;
  const first = buttons[0], last = buttons[buttons.length - 1];
  if (!$('bigView').contains(document.activeElement)) { event.preventDefault(); first.focus(); }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
