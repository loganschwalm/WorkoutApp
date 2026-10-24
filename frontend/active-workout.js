// The workout in progress: showing it, starting and ending it, going from exercise to exercise, finishing it into a saved workout,
// and getting it back when the page opens (from this device first, then the server). Loaded before script.js, which starts the page
// and declares the state these use (activeSession, savedWorkouts); nothing here reads it until the page is running.

// Saved on this device immediately; offline.js uploads it in the background (activeSession === null records that the workout ended).
function persistActiveSession() {
  saveLocalActive(activeSession);
}

function getActiveSession() {
  return syncFetch('/api/active-session')
    .then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load active workout.')))
    .then(result => result.session);
}

// "Exercise 2 of 6" opens a list of every exercise and how far each has got, to go straight to any of them: when a
// machine is taken, do one that is free and come back.
function renderActiveProgress() {
  const { exercises, currentIndex } = activeSession;
  $('activeWorkoutProgress').textContent = `Exercise ${currentIndex + 1} of ${exercises.length}`;
  $('prevExerciseBtn').hidden = currentIndex === 0;
  const members = supersetMembers(activeSession, currentIndex);
  const onLast = members[members.length - 1] === exercises.length - 1;
  $('nextExerciseBtn').textContent = onLast ? 'Finish workout' : 'Next exercise';
  // Before the last exercise, Next goes on; Finish early ends the workout there instead.
  $('finishEarlyBtn').hidden = onLast;
  $('exerciseJump').innerHTML = exercises.map((exercise, index) => {
    const sets = (exercise.sets || []).length;
    const planned = Array.isArray(exercise.plan) ? exercise.plan.length : 0;
    const done = planned ? sets >= planned : sets > 0;
    const status = planned ? `${sets} of ${plural(planned, 'set')}` : sets ? plural(sets, 'set') : 'No sets yet';
    const superset = supersetMembers(activeSession, index).length > 1 ? ' <span class="jump-superset">superset</span>' : '';
    const names = supersetMembers(activeSession, index).map(member => exercises[member].name).join(' and ');
    const move = (step, arrow, word) => `<button type="button" class="jump-move" data-move="${step}" data-index="${index}"`
      + `${moveTarget(activeSession, index, step) === null ? ' disabled' : ''} aria-label="Move ${escapeHTML(names)} ${word}">${arrow}</button>`;
    return `<li><button type="button" data-jump="${index}"${index === currentIndex ? ' aria-current="step"' : ''}${done ? ' class="done"' : ''}>`
      + `<span class="jump-name">${index + 1}. ${escapeHTML(exercise.name)}${superset}</span>`
      + `<span class="jump-sets">${escapeHTML(status)}</span></button>${move(-1, '&uarr;', 'earlier')}${move(1, '&darr;', 'later')}</li>`;
  }).join('');
  $('lastToggle').hidden = moveTarget(activeSession, currentIndex, 'last') === null;
}

// ---- Putting the exercises in another order ---------------------------------

// The exercises as the blocks that move together: a superset is one, any other exercise is its own. Each is a list of positions.
function exerciseBlocks(session) {
  const blocks = [];
  for (let index = 0; index < session.exercises.length;) {
    const members = supersetMembers(session, index);
    blocks.push(members);
    index = members[members.length - 1] + 1;
  }
  return blocks;
}

// Which block the exercise at `index` would go to, moved a place earlier (-1) or later (1) or to the end ('last'); null if it cannot.
// A program day's first exercise is the lift the day is about, which the program reads by its place (completeProgramDay), so that one
// stays where it is and nothing goes in front of it.
function moveTarget(session, index, where) {
  const blocks = exerciseBlocks(session);
  const floor = session.programDay ? 1 : 0;
  const at = blocks.findIndex(block => block.includes(index));
  if (at < floor) return null;
  const to = where === 'last' ? blocks.length - 1 : at + where;
  return to < floor || to >= blocks.length || to === at ? null : to;
}

// Moves the exercise at `index` (with its superset, if it is in one), and keeps the exercise on show the one on show. Returns the
// exercise's new position, or -1 if it could not move.
function moveExercise(index, where) {
  const session = activeSession;
  const to = moveTarget(session, index, where);
  if (to === null) return -1;
  const blocks = exerciseBlocks(session);
  const at = blocks.findIndex(block => block.includes(index));
  const exercise = session.exercises[index], current = session.exercises[session.currentIndex];
  const [moved] = blocks.splice(at, 1);
  blocks.splice(to, 0, moved);
  const original = [...session.exercises];
  session.exercises.splice(0, original.length, ...blocks.flat().map(position => original[position]));
  session.currentIndex = session.exercises.indexOf(current);
  persistActiveSession();
  renderActiveProgress();
  renderSuperset();
  // A rest on show was kept against the exercise it follows, by its place.
  if (!$('restPanel').hidden) rememberRest();
  if (typeof bigViewIsOpen === 'function' && bigViewIsOpen()) renderBigView();
  return session.exercises.indexOf(exercise);
}

function showExerciseJump(open) {
  $('exerciseJump').hidden = !open;
  $('activeWorkoutProgress').setAttribute('aria-expanded', String(open));
}

// The planned sets as chips: done, the one to do now, and those to come. A set done shows what was lifted, which may not be
// what was planned.
function planChipsHtml(exercise, plan) {
  const planState = index => index < exercise.sets.length ? 'done' : index === exercise.sets.length ? 'current' : 'upcoming';
  const chip = (set, index) => {
    const logged = exercise.sets[index];
    return logged ? formatPlannedSet({ weight:isBodyweight(logged.weight) ? '' : logged.weight, reps:logged.reps }) : formatPlannedSet(set);
  };
  return plan.map((set, index) => `<li class="${planState(index)}">${escapeHTML(chip(set, index))}</li>`).join('');
}

// Last time's line: the label, then each run of sets ("75 lbs × 5", "115 lbs × 5, 5, 9") as one span, which the line wraps
// whole (see .set-run), so a weight is never left on one line and its reps on the next. The text is what it always was;
// describeLoggedSets joins its runs with " · ", which no run contains.
function showLastTime(label, described) {
  const line = $('activeExerciseLast');
  const labelSpan = document.createElement('span');
  labelSpan.className = 'context-label';
  labelSpan.textContent = label;
  line.replaceChildren(labelSpan);
  described.split(' · ').forEach((run, index) => {
    if (index) line.append(' · ');
    const part = document.createElement('span');
    part.className = 'set-run';
    part.textContent = run;
    line.append(part);
  });
}

function renderActiveWorkout() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  exercise.sets = exercise.sets || [];
  const timed = isTimed(exercise);
  const previous = lastTime(exercise.name);
  const lastSet = exercise.sets[exercise.sets.length - 1];
  const plan = Array.isArray(exercise.plan) && exercise.plan.length ? exercise.plan : null;
  $('activeWorkoutTitle').textContent = activeSession.name;
  renderActiveProgress();
  $('activeExerciseName').textContent = exercise.name;
  $('activeExerciseTarget').textContent = plan ? plannedTarget(exercise, previous)
    : `Target: ${exercise.reps} ${timed ? 'seconds' : 'reps'}${exercise.weight ? ` at ${formatWeight(exercise.weight)} ${weightUnit()}` : ''}`;
  $('activePlan').hidden = !plan;
  $('activePlan').innerHTML = plan ? planChipsHtml(exercise, plan) : '';
  $('activeExerciseLast').hidden = !previous;
  if (previous) {
    const when = new Date(previous.date).toLocaleDateString(undefined, { month:'short', day:'numeric' });
    showLastTime(`Last time (${when}): `, describeLoggedSets(previous.sets, timed));
  }
  $('completedRepsLabel').textContent = timed ? 'Seconds' : 'Reps completed';
  // Once a set is logged, one tap logs it again, whatever the fields were changed to since.
  $('repeatSetBtn').hidden = !lastSet;
  if (lastSet) $('repeatSetBtn').textContent = `Same as last set: ${describeLoggedSets([lastSet], timed)}`;
  $('holdTimer').hidden = !timed;
  $('activeNotes').value = activeSession.notes || '';
  const defaults = nextSetDefaults(exercise, previous, timed);
  $('activeWeight').value = defaults.weight;
  $('completedReps').value = defaults.reps;
  showPlates();
  renderExerciseNote();
  renderSuperset();
  renderProgression(exercise, previous);
  renderPastSessions(exercise);
  renderEffort(exercise);
  renderSetType(exercise);
  $('completedSets').innerHTML = completedSetsHtml(exercise, timed);
  $('completedSetsToggle').hidden = !exercise.sets.length;
  // The list is folded away, so its label says what was just logged: "Completed sets (3) · last 145 lbs × 6".
  $('completedSetsSummary').textContent = `Completed sets (${exercise.sets.length})`
    + (lastSet ? ` · last ${describeLoggedSets([lastSet], timed)}` : '');
  syncHoldDisplay();
  $('activeSyncNotice').hidden = !activeSyncFailed;
  // What the next set or the finish is a step away from (reach.js), now the stall hint has had its say.
  renderReach();
}

// Going to another exercise, ending a workout or starting one closes whatever was open for the exercise before.
function closeExercisePanels() {
  $('exerciseMenu').open = false;
  stopHold();
  showExerciseJump(false);
  showSwap(false);
  showNotePanel(false);
  showGuide(false);
}

function goToExercise(index) {
  closeExercisePanels();
  effortChoice = null;
  setTypeChoice = null;
  activeSession.currentIndex = index;
  stopRestTimer();
  restRemaining = restDuration();
  updateRestTimer();
  $('restPanel').hidden = true;
  renderActiveWorkout();
  persistActiveSession();
}

// While a workout goes on it has the Tracker to itself: the program, recent workouts, templates and saved workouts
// wait behind one button under it, so there is nothing to scroll past between sets.
function showActiveCard(shown) {
  $('activeWorkout').hidden = !shown;
  document.body.classList.toggle('training', shown);
  showOtherCards(false);
}

function showOtherCards(open) {
  document.body.classList.toggle('showing-all', open);
  $('otherCardsToggle').setAttribute('aria-expanded', String(open));
  $('otherCardsToggle').textContent = open ? 'Hide the rest of the Tracker' : 'Show the rest of the Tracker';
}

// Takes the workout off the screen. closeActiveWorkout also records that it ended, for the server to be told.
function hideActiveWorkout() {
  // The keyboard was on one of its buttons, which go with it; a workout ended on another device leaves it where it was.
  const hadFocus = $('activeWorkout').contains(document.activeElement);
  closeExercisePanels();
  activeSession = null;
  stopRestTimer();
  $('restPanel').hidden = true;
  showActiveCard(false);
  syncWakeLock();
  if (hadFocus) focusFirstShown(['templatesToggle', 'settingsButton']);
}

function closeActiveWorkout() {
  hideActiveWorkout();
  persistActiveSession();
}

// `template` is a template, a saved workout, or a day of a training program (program.js), whose exercises carry a
// set-by-set plan and whose programDay says which day of the program it is. A template exercise with a set count is
// planned here, at the weight its progression gives (templateSession in training-tools.js).
function startWorkout(stored) {
  if (!Array.isArray(stored.exercises) || !stored.exercises.length) {
    showFeedback(`“${stored.name}” has no exercises to start.`);
    return;
  }
  const replacing = `Replace your in-progress “${activeSession?.name}” workout? Sets you have logged so far will be lost.`;
  if (activeSession && getWorkoutSettings().confirmEnd && !confirm(replacing)) return;
  closeExercisePanels();
  setTypeChoice = null;
  stopRestTimer();
  $('restPanel').hidden = true;
  $('workoutSummary').hidden = true;
  // In the unit shown, whatever unit a saved workout was logged in; the session says which, and so will the saved workout.
  // A weight converted from the other unit becomes one to load, to the nearest half (47.63 kg is 47.5).
  const template = inUnit(stored);
  const converted = template !== stored;
  // startedAt times the workout, for its summary and History.
  activeSession = {
    name:template.name, notes:template.notes || '',
    exercises:template.exercises.map(item => templateSession({ ...item, weight:prefillWeight(item.weight, converted), sets:[] })),
    currentIndex:0, clientId:newClientId(), unit:weightUnit(), startedAt:Date.now()
  };
  if (template.programDay) activeSession.programDay = template.programDay;
  restRemaining = restDuration();
  updateRestTimer();
  persistActiveSession();
  renderActiveWorkout();
  // Notes fold away under the set entry, unless the workout brings some with it. So do the sets logged so far.
  $('activeNotesToggle').open = Boolean(activeSession.notes);
  $('completedSetsToggle').open = false;
  showActiveCard(true);
  syncWakeLock();
  scrollToCard($('activeWorkout'), 'start');
}

// The finished workout goes into the local upload queue first, so nothing can lose it after this point;
// the clientId lets the server ignore a retried upload it already stored.
async function finishWorkout() {
  // An exercise with no logged sets was skipped; saving it would make history and progress count its target as done.
  const performed = activeSession.exercises.filter(item => item.sets && item.sets.length);
  if (!performed.length) {
    if (getWorkoutSettings().confirmEnd && !confirm('No sets were logged. Finish without saving this workout?')) return;
    closeActiveWorkout();
    showFeedback('No sets were logged, so nothing was saved.');
    return;
  }
  const skipped = activeSession.exercises.length - performed.length;
  activeSession.clientId = activeSession.clientId || newClientId();
  // Each exercise keeps whether it is timed and its own rest, so starting the workout again brings them back. One planned
  // from a template keeps its sets and range too, and the bottom of the range as its reps, so it progresses again.
  const exercises = performed.map(item => ({
    name:item.name, weight:Math.max(...item.sets.map(set => Number(set.weight) || 0)), reps:item.setCount ? item.reps : item.sets[item.sets.length - 1].reps, sets:item.sets,
    ...(isTimed(item) ? { timed:true } : {}), ...(Number(item.rest) > 0 ? { rest:Number(item.rest) } : {}), ...(item.group ? { group:item.group } : {}),
    ...(item.setCount ? { setCount:item.setCount } : {}), ...(item.repsMax ? { repsMax:item.repsMax } : {}) }));
  const finishedAt = Date.now();
  const workout = {
    name:activeSession.name, notes:activeSession.notes || '', exercises, createdAt:finishedAt, clientId:activeSession.clientId, unit:recordUnit(activeSession)
  };
  // In seconds; a workout started before sessions were timed has no duration.
  if (activeSession.startedAt > 0 && finishedAt > activeSession.startedAt) workout.duration = Math.round((finishedAt - activeSession.startedAt) / 1000);
  if (activeSession.programDay) workout.program = programInfo(activeSession.programDay);
  // Records are against everything before this workout, so they are worked out before it joins the bests. So is whatever else
  // the summary compares it with (its last time, the week so far).
  const records = newRecords(workout, personalBests);
  const before = summaryBefore(workout);
  rememberLastPerformance(workout);
  rememberBests(workout);
  queuePendingWorkout(workout);
  // Marks the program's day done (and may start its next cycle); says what comes next.
  const programDay = activeSession.programDay ? completeProgramDay(activeSession) : { note:'', outcome:null };
  const programNote = programDay.note;
  closeActiveWorkout();
  showWorkoutSummary(workout, records, before, programDay.outcome);
  const synced = await flushPendingWorkouts();
  const note = (skipped ? ` ${skipped} exercise${skipped === 1 ? '' : 's'} with no sets ${skipped === 1 ? 'was' : 'were'} left out.` : '')
    + (programNote ? ` ${programNote}` : '');
  showFeedback(synced ? `“${workout.name}” saved successfully.${note}`
    : `“${workout.name}” is saved on this device and will sync when the server is reachable again.${note}`, 'success');
}

// A workout in progress the page can show: one with exercises, on one of them. A saved workout with none (an import or
// the API can hold one) would otherwise throw on every load, on every device, since the server keeps it for them all.
// One pointing past its last exercise goes to the last.
function usableSession(session) {
  const exercises = session && Array.isArray(session.exercises) ? session.exercises : [];
  if (!exercises.length || !exercises.every(item => item && typeof item === 'object' && typeof item.name === 'string')) return null;
  const index = Math.floor(Number(session.currentIndex));
  const currentIndex = Number.isFinite(index) ? Math.min(Math.max(index, 0), exercises.length - 1) : 0;
  return currentIndex === session.currentIndex ? session : { ...session, currentIndex };
}

function showSavedSession(savedSession) {
  const usable = usableSession(savedSession);
  if (!usable) {
    // Closed here and on the server, so the next load, here or anywhere, starts clean.
    closeActiveWorkout();
    showFeedback('The workout in progress had no exercises to show, so it was closed.');
    return;
  }
  activeSession = inUnit(usable);
  if (activeSession !== savedSession) persistActiveSession();
  stopRestTimer();
  restRemaining = restDuration();
  updateRestTimer();
  $('restPanel').hidden = true;
  // A rest this device was showing when the page went away comes back with it (see rememberRest in rest-timer.js).
  restoreRest();
  renderActiveWorkout();
  $('activeNotesToggle').open = Boolean(activeSession.notes);
  showActiveCard(true);
  syncWakeLock();
}

// The workout in progress as this device last saw it, on screen before the server is asked anything. On a connection that
// stalls rather than fails, as in a basement gym, waiting for the server would keep it hidden until the requests gave up.
function restoreLocalWorkout() {
  const local = readLocalActive();
  if (local && local.session) showSavedSession(local.session);
}

// `workouts` is null when the server could not be reached. The workout on this device is already on screen
// (restoreLocalWorkout); the server's copy replaces it only when it changed on another device.
async function resumeOrStartWorkout(workouts) {
  const requested = workouts ? takeRequestedWorkout() : null;
  const local = readLocalActive();
  if (local && local.dirty) {
    // Changes made here that the server has not seen yet win over the server's copy.
    syncActiveSession();
  } else {
    try {
      const savedSession = await getActiveSession();
      // Anything done here while the server was being asked is newer than its answer, so its answer is dropped.
      if (readLocalActive()?.stamp === local?.stamp) {
        mirrorActiveSession(savedSession);
        if (JSON.stringify(savedSession) !== JSON.stringify(local?.session ?? null)) {
          if (savedSession) showSavedSession(savedSession);
          else hideActiveWorkout();
        }
      }
    } catch (error) {
      console.error('Unable to load active workout; showing the copy on this device.', error);
    }
  }
  await startTodaysWorkout();
  const workout = requested && workouts.find(item => item.id === requested.id);
  if (!workout) return;
  if (requested.action === 'start') startWorkout(workout);
  else loadWorkoutIntoForm(workout, requested.action === 'edit');
}

$('activeNotes').oninput = () => { if (activeSession) { activeSession.notes = $('activeNotes').value; persistActiveSession(); } };
$('activeWorkoutProgress').onclick = () => showExerciseJump($('exerciseJump').hidden);
$('otherCardsToggle').onclick = () => showOtherCards(!document.body.classList.contains('showing-all'));
$('exerciseJump').onclick = e => {
  const move = e.target.closest('[data-move]');
  if (move && activeSession) {
    const now = moveExercise(Number(move.dataset.index), Number(move.dataset.move));
    // The list was drawn again: the keyboard goes to the same button of the same exercise, or to its other one if that can go no further.
    const again = [...$('exerciseJump').querySelectorAll(`[data-index="${now}"]`)];
    const same = again.find(button => button.dataset.move === move.dataset.move && !button.disabled) || again.find(button => !button.disabled);
    if (same) same.focus({ preventScroll:true });
    return;
  }
  const button = e.target.closest('[data-jump]');
  if (!button || !activeSession) return;
  const index = Number(button.dataset.jump);
  showExerciseJump(false);
  if (index !== activeSession.currentIndex && activeSession.exercises[index]) goToExercise(index);
};
// Finishing saves the exercises with sets and leaves the rest out. With some of them still to do, it asks first, since a
// stray tap would end the workout: Finish early is beside Next exercise, and Next exercise becomes Finish workout in the same
// place on the last exercise, so a double tap on the one before would reach it before the last had a set. With nothing
// logged at all, finishWorkout asks its own question.
function finishWorkoutAsking() {
  const logged = activeSession.exercises.some(item => item.sets && item.sets.length);
  const waiting = activeSession.exercises.filter(item => !(item.sets && item.sets.length)).length;
  if (logged && waiting && !confirm(`Finish ${activeSession.name} now? ${plural(waiting, 'exercise')} with no sets will be left out.`)) return;
  finishWorkout();
}

// Next goes on past the superset the current exercise is in, which is done as rounds rather than one exercise at a time.
// On the last exercise it is Finish, so a second tap can arrive after the workout has closed: that one does nothing.
$('nextExerciseBtn').onclick = () => {
  if (!activeSession) return;
  const members = supersetMembers(activeSession, activeSession.currentIndex);
  const after = members[members.length - 1] + 1;
  if (after >= activeSession.exercises.length) finishWorkoutAsking();
  else goToExercise(after);
};
// Finish early ends the workout from any exercise, as Finish does on the last.
$('finishEarlyBtn').onclick = () => { if (activeSession) finishWorkoutAsking(); };
$('prevExerciseBtn').onclick = () => { if (activeSession && activeSession.currentIndex > 0) goToExercise(activeSession.currentIndex - 1); };
// Cancel takes the workout away without saving it, as if it had never been started: nothing joins History, last time's
// numbers, the records or Progress, a program's day stays to do, and the server is told it ended. One started by mistake,
// with nothing logged, goes at once; one with sets logged asks first (unless Settings says not to). Either way the banner
// offers it back for a few seconds, in case the tap was the mistake.
$('endWorkoutBtn').onclick = () => {
  const session = activeSession;
  if (!session) return;
  const logged = session.exercises.reduce((total, item) => total + (item.sets?.length || 0), 0);
  if (logged && getWorkoutSettings().confirmEnd && !confirm(`Cancel this workout? Its ${plural(logged, 'logged set')} will not be saved.`)) return;
  closeActiveWorkout();
  showFeedback(`“${session.name}” was cancelled. Nothing was saved.`, 'info', { label:'Undo', run:() => resumeWorkout(session) });
};

// Puts a cancelled workout back as it was, unless another has started since.
function resumeWorkout(session) {
  if (activeSession) {
    showFeedback(`“${session.name}” cannot come back: another workout has started.`);
    return;
  }
  activeSession = session;
  restRemaining = restDuration();
  updateRestTimer();
  persistActiveSession();
  renderActiveWorkout();
  showActiveCard(true);
  syncWakeLock();
  showFeedback(`“${session.name}” is back.`, 'success');
}
// Tapping a number in the workout selects it, so typing replaces the prefilled weight or reps instead of adding to it.
// Selecting a moment later keeps iOS Safari from undoing it as the tap that focused the box ends.
$('activeWorkout').addEventListener('focusin', e => {
  const input = e.target;
  if (input.matches('input[type=number]')) setTimeout(() => { if (document.activeElement === input) input.select(); });
});
$('activeAddName').oninput = () => markInvalid($('activeAddName'), false);
$('activeAddReps').oninput = () => markInvalid($('activeAddReps'), false);
$('activeAddTimed').onchange = () => { $('activeAddRepsLabel').textContent = $('activeAddTimed').checked ? 'Target seconds' : 'Target reps'; };
// The new exercise goes right after the current one so Next reaches it; the current exercise is not re-rendered, keeping anything typed.
$('activeAddBtn').onclick = () => {
  const name = $('activeAddName').value.trim(), reps = $('activeAddReps').value, timed = $('activeAddTimed').checked;
  markInvalid($('activeAddName'), !name);
  markInvalid($('activeAddReps'), !reps || Number(reps) < 1);
  if (!name) { showFeedback('Enter an exercise name before adding it.'); $('activeAddName').focus(); return; }
  if (!reps || Number(reps) < 1) {
    showFeedback(timed ? 'Enter at least 1 target second for this exercise.' : 'Enter at least 1 target rep for this exercise.');
    $('activeAddReps').focus();
    return;
  }
  // After the superset the current exercise is in, if it is in one, so the new exercise does not split it.
  const members = supersetMembers(activeSession, activeSession.currentIndex);
  const added = { name, weight:'', reps:String(Math.floor(Number(reps))), ...(timed ? { timed:true } : {}), sets:[] };
  activeSession.exercises.splice(members[members.length - 1] + 1, 0, added);
  $('activeAddTimed').checked = false;
  $('activeAddRepsLabel').textContent = 'Target reps';
  persistActiveSession();
  renderActiveProgress();
  $('activeAddName').value = '';
  $('activeAddReps').value = '';
  $('addActiveExercise').open = false;
  showFeedback(`Added “${name}” as your next exercise.`, 'success');
};
