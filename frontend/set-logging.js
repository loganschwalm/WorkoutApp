// Logging sets in the workout in progress: what the entry fields start with, what is wrong with an entry, recording a set and the
// rest after it, the guard against a thumb that bounces, and correcting or taking away a set already logged (also used by the form
// for a saved workout). Loaded before script.js, which declares activeSession; nothing here reads it until a set is logged.

// The weight and reps the entry fields start the next set with. A workout from a training program plans every set, so the next
// set is whichever planned one has not been logged yet.
function nextSetDefaults(exercise, previous, timed) {
  const sets = exercise.sets || [];
  const previousFirst = previous ? { ...previous.sets[0], weight:prefillWeight(previous.sets[0].weight, previous.converted) } : null;
  const lastSet = sets[sets.length - 1];
  const plan = Array.isArray(exercise.plan) && exercise.plan.length ? exercise.plan : null;
  const planned = plan ? plan[sets.length] : null;
  if (planned) {
    // A planned set with no weight (an assistance exercise) takes the set just logged, or last time's.
    const plannedWeight = planned.weight === '' || planned.weight === undefined || planned.weight === null ? null : planned.weight;
    return {
      weight:plannedWeight ?? (lastSet ? lastSet.weight || '' : (previousFirst && previousFirst.weight) || ''),
      // A rep range (8–12) takes the reps just done, or last time's, and starts at the bottom of the range.
      reps:planned.repsMax ? (lastSet || previousFirst || planned).reps || '' : planned.reps || ''
    };
  }
  // Next set defaults to the set just logged, or to last time's first set, so repeating a set is one tap. A timed
  // exercise done for the first time starts from its target, so its timer is ready to start.
  return {
    weight:lastSet ? lastSet.weight || '' : exercise.weight || (previousFirst && previousFirst.weight) || '',
    reps:(lastSet || previousFirst || (timed ? { reps:exercise.reps } : {})).reps || ''
  };
}

// The sets logged so far, each with its weight and reps to correct in place.
function completedSetsHtml(exercise, timed) {
  const count = timed ? { unit:'s', label:'seconds' } : { unit:'reps', label:'reps' };
  // What was typed or sent can be any text (an imported file, an older version): only a number is shown, never the text itself.
  const effort = set => Number.isFinite(Number(set.rir)) && set.rir !== null && set.rir !== '' && set.rir !== undefined
    ? `<small class="set-effort">${Number(set.rir) >= 4 ? '4+' : Number(set.rir)} left</small>` : '';
  return exercise.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}${effort(set)}</span>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(set.weight || '')}"`
    + ` data-set="${index}" data-field="weight" aria-label="Set ${index + 1} weight in ${weightUnit()}"><span>${weightUnit()}</span></div>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(set.reps)}" data-set="${index}"`
    + ` data-field="reps" aria-label="Set ${index + 1} ${count.label}"><span>${count.unit}</span></div>`
    + `<button class="remove" type="button" data-remove-set="${index}" aria-label="Remove set ${index + 1}" title="Remove">&times;</button></li>`).join('');
}

// A set changed in place, during a workout or in a saved one, is asked about as a new set is when it looks like a slip
// (see implausibleSet in records.js), against the exercise's other sets and its bests. Declining puts back what it was.
// True when the change may stand.
function confirmSetChange(exercise, index, field, value, input) {
  const set = exercise.sets[index];
  const doubt = implausibleSet(exercise, { ...set, [field]:value }, exercise.sets.filter((other, at) => at !== index));
  if (!doubt || confirm(doubt.message)) return true;
  input.value = field === 'weight' ? set.weight || '' : set.reps;
  return false;
}

// What is wrong with a set's weight or reps changed in place, or null when it may stand. Shared by a saved workout's sets and
// the sets logged in a workout; the caller says it and puts the old value back. A timed exercise's reps are seconds, which
// need not be whole.
function setChangeProblem(field, value, timed) {
  if (field === 'reps' && (!value || Number(value) < 1)) return timed ? 'Seconds must be at least 1.' : 'Reps must be at least 1.';
  if (field === 'reps' && !timed && !Number.isInteger(Number(value))) return 'Reps must be a whole number.';
  if (field === 'weight' && value !== '' && Number(value) < 0) return 'Weight cannot be negative.';
  return null;
}

// Equipment that always carries a weight (see exerciseDetails in exercise-library.js).
const loadedEquipment = ['barbell', 'dumbbell', 'machine', 'cable', 'kettlebell'];

// What the set entry says, as typed.
function readSetEntry() {
  return { weightValue:$('activeWeight').value, reps:Number($('completedReps').value) };
}

// What is wrong with an entry, if anything, as [what to tell the lifter, the field to look at].
function setEntryProblem({ weightValue, reps }, timed) {
  if (!reps || reps < 1) return [timed ? 'Enter the seconds held for this set.' : 'Enter the reps completed for this set.', $('completedReps')];
  // A rep is done or not; a hold's seconds are left as typed.
  if (!timed && !Number.isInteger(reps)) return ['Reps must be a whole number.', $('completedReps')];
  if (weightValue !== '' && Number(weightValue) < 0) return ['Weight cannot be negative.', $('activeWeight')];
  return null;
}

// Asks about an entry that is likely a slip. The field to look at if the lifter says no, else null.
function refusedSet(exercise, { weightValue, reps }, timed) {
  // No weight logs the set as bodyweight. For an exercise that is always loaded, that is more likely a weight left out
  // (a new exercise has none to start from) than meant, so it is asked first. A 0 typed in is taken as meant.
  if (weightValue === '' && !timed && loadedEquipment.includes(exerciseDetails(exercise.name).equipment)
    && !confirm(`No weight entered for ${exercise.name}. Log ${reps} reps with no weight?`)) return $('activeWeight');
  // A set far past anything done before is asked about too (see implausibleSet in records.js).
  const doubt = implausibleSet(exercise, { weight:Number(weightValue) || 0, reps }, exercise.sets);
  if (doubt && !confirm(doubt.message)) return doubt.field === 'weight' ? $('activeWeight') : $('completedReps');
  return null;
}

// Adds the set to the exercise, shows it, and marks a record or a goal reached. Returns what it said of them, or '', so what
// follows the set (restAfterSet) can say it again rather than over it.
function recordSet(exercise, { weightValue, reps }) {
  const weight = Number(weightValue) || 0;
  const effort = effortAsked(exercise) && effortChoice !== null ? { rir:effortChoice } : {};
  effortChoice = null;
  const recordBefore = exerciseRecord(exercise.name);
  const goalReached = goalReachedBy(exercise, weight);
  exercise.sets.push({ reps, weight, ...effort });
  persistActiveSession();
  renderActiveWorkout();
  const recordNow = exerciseRecord(exercise.name);
  // A goal reached gets a bigger firework than a record, and the record's would only sit on top of it.
  // The fireworks go up from the button that was tapped: the big view's, when it is open over the page.
  const tapped = bigViewIsOpen() ? $('bigViewPrimary') : $('completeSetBtn');
  // A program's + set (as many reps as you can) that went past its planned reps.
  const planned = Array.isArray(exercise.plan) ? exercise.plan[exercise.sets.length - 1] : null;
  const beatBy = planned && planned.amrap && !isSwappedIn(exercise) ? reps - (Number(planned.reps) || 0) : 0;
  const record = recordNow && recordNow !== recordBefore ? `New record! ${recordNow}.` : '';
  const goal = goalReached ? `Goal reached: ${goalReached.name}, ${formatWeight(goalReached.target)} ${goalReached.unit || 'lbs'}!` : '';
  const plus = beatBy > 0 ? `+ set: ${plural(reps, 'rep')}, ${beatBy} more than the ${planned.reps} planned!` : '';
  // One message saying all of it, and one show, the size of the biggest. A goal reached says it was the heaviest yet already.
  const said = (goal ? [goal, plus] : [plus, record]).filter(Boolean).join(' ');
  if (goal || plus) celebrate(tapped, 'goal');
  else if (record) celebrate(tapped, 'record');
  if (said) showFeedback(said, 'success');
  unlockAudio();
  // A tap: the moment a phone that refused the keep-awake video (see syncWakeLock) is asked again.
  syncWakeLock();
  return said;
}

// What follows a set: rest, or in a superset the next exercise at once, with no rest until the round is done. `said` is what
// the set's record or goal said, which the superset's message keeps in front of it, so a record is never only fireworks.
function restAfterSet(said = '') {
  const index = activeSession.currentIndex;
  const next = nextInRound(activeSession, index);
  if (next !== null) {
    stopRestTimer();
    $('restPanel').hidden = true;
    moveWithinSuperset(next);
    showFeedback(`${said ? `${said} ` : ''}Next in the superset: ${activeSession.exercises[next].name}.`, 'success');
    return;
  }
  if (getWorkoutSettings().autoRest) startRestTimer();
  else { stopRestTimer(); restRemaining = restTotal = restDuration(); updateRestTimer(); $('restPanel').hidden = false; }
  // The round is done: rest, then the superset starts again from its first exercise with sets left.
  const first = supersetMembers(activeSession, index).length > 1 ? firstWithSetsLeft(activeSession, index) : null;
  if (first !== null && first !== index) moveWithinSuperset(first);
  // The rest is what the big view is for (big-view.js), if Settings asks for it. One closed by hand stays closed until the next set.
  if (getWorkoutSettings().bigViewOnRest === true) openBigView();
}

// A thumb that lands twice on Complete set, which is still under it once the set is logged, would log the set twice. A tap
// this soon after a set was logged is taken as that bounce rather than another set, since no set takes under a second. Only
// real taps are judged: the big view passes its own on as a click of the page's button, and judges the tap itself.
const SET_BOUNCE_MS = 600;
let setLoggedAt = -Infinity;

function bouncedTap(event) {
  return event.isTrusted && event.timeStamp - setLoggedAt < SET_BOUNCE_MS;
}

// Logs a set: the one in the entry fields (Complete set), or the entry given (Same as last set), after the checks and
// questions that either gets.
function logSet(entry = null) {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const timed = isTimed(exercise);
  if (!entry) {
    // Complete set during a hold ends it there, logging the seconds held so far.
    if (holdInterval) stopHold(true);
    entry = readSetEntry();
    markInvalid($('completedReps'), !entry.reps || entry.reps < 1);
    markInvalid($('activeWeight'), entry.weightValue !== '' && Number(entry.weightValue) < 0);
  }
  const problem = setEntryProblem(entry, timed);
  if (problem) {
    markInvalid(problem[1], true);
    showFeedback(problem[0]);
    problem[1].focus();
    return;
  }
  const refused = refusedSet(exercise, entry, timed);
  if (refused) {
    markInvalid(refused, true);
    refused.focus();
    return;
  }
  clearFeedback();
  // performance.now() is the clock a tap's timeStamp is on.
  setLoggedAt = performance.now();
  restAfterSet(recordSet(exercise, entry));
}

$('completeSetBtn').onclick = event => { if (!bouncedTap(event)) logSet(); };
// Enter on the keyboard that is up moves on: from the weight to the reps, and from the reps it logs the set, as Complete set does
// (with the same guard, so a key held down logs one). The keyboard's own key says so (enterkeyhint in the page).
$('activeWeight').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing) return;
  event.preventDefault();
  $('completedReps').focus();
  $('completedReps').select();
});
$('completedReps').addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing) return;
  event.preventDefault();
  if (activeSession && !event.repeat && !bouncedTap(event)) logSet();
});

// Logs the set before this one again: the weight, reps or seconds are as it was, whatever the fields say, and the usual
// checks and rest follow, as for Complete set. A hold being timed is stopped first, so its seconds do not replace the set's.
function repeatLastSet() {
  const exercise = activeSession && activeSession.exercises[activeSession.currentIndex];
  const last = exercise && exercise.sets && exercise.sets[exercise.sets.length - 1];
  if (!last) return;
  stopHold();
  logSet({ weightValue:String(last.weight || 0), reps:Number(last.reps) });
}
$('repeatSetBtn').onclick = event => { if (!bouncedTap(event)) repeatLastSet(); };
$('completedReps').oninput = () => { markInvalid($('completedReps'), false); syncHoldDisplay(); };
// Logged sets can be corrected in place; a value that is not valid snaps back to what was logged.
$('completedSets').onchange = e => {
  const index = Number(e.target.dataset.set);
  const field = e.target.dataset.field;
  if (!activeSession || !field || Number.isNaN(index)) return;
  const set = activeSession.exercises[activeSession.currentIndex].sets[index];
  if (!set) return;
  const value = e.target.value;
  const problem = setChangeProblem(field, value, isTimed(activeSession.exercises[activeSession.currentIndex]));
  if (problem) {
    showFeedback(problem);
    e.target.value = field === 'weight' ? set.weight || '' : set.reps;
    return;
  }
  if (!confirmSetChange(activeSession.exercises[activeSession.currentIndex], index, field, Number(value) || 0, e.target)) return;
  // If this is the last set, the fields for the next one started from it: they follow the correction, unless they were changed since.
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const entry = field === 'weight' ? $('activeWeight') : $('completedReps');
  const followed = index === exercise.sets.length - 1 && entry.value === String(set[field] || '');
  set[field] = Number(value) || 0;
  if (followed) {
    entry.value = set[field] || '';
    if (field === 'weight') showPlates();
  }
  clearFeedback();
  persistActiveSession();
  renderReach();
};
// Fix last set, in the rest after a set (and in the big view): the list of completed sets is opened, and the cursor put in the last
// set's reps with the number selected, so a slip is a few keys. Nothing is drawn again, so what is typed for the next set stays.
function fixLastSet() {
  if (!activeSession) return;
  const last = (activeSession.exercises[activeSession.currentIndex].sets || []).length - 1;
  if (last < 0) return;
  $('completedSetsToggle').open = true;
  const reps = $('completedSets').querySelector(`[data-set="${last}"][data-field="reps"]`);
  if (!reps) return;
  scrollToCard(reps.closest('li'), 'nearest');
  reps.focus({ preventScroll:true });
  reps.select();
}
$('restFixBtn').onclick = fixLastSet;

// Remove takes the set away at once, with no question asked mid-workout, and the banner offers it back for a few
// seconds in case the tap was a slip. Undo puts it back in its place, even after moving on to another exercise.
$('completedSets').onclick = e => {
  const button = e.target.closest('[data-remove-set]');
  if (!button || !activeSession) return;
  const session = activeSession;
  const exercise = session.exercises[session.currentIndex];
  const index = Number(button.dataset.removeSet);
  const [removed] = exercise.sets.splice(index, 1);
  if (!removed) return;
  persistActiveSession();
  renderActiveWorkout();
  showFeedback(`Removed set ${index + 1} of ${exercise.name} (${describeLoggedSets([removed], isTimed(exercise))}).`, 'info', { label:'Undo', run:() => {
    if (activeSession !== session) {
      showFeedback('That set cannot come back: its workout has ended.');
      return;
    }
    if (!session.exercises.includes(exercise)) {
      showFeedback(`That set cannot come back: ${exercise.name} was swapped out.`);
      return;
    }
    exercise.sets.splice(Math.min(index, exercise.sets.length), 0, removed);
    persistActiveSession();
    renderActiveWorkout();
    showFeedback(`Set ${index + 1} of ${exercise.name} is back.`, 'success');
  } });
};
