// The Tracker: the form for writing a workout down, the saved and recent workouts, the workout in progress, and
// starting the page. Its helpers load before it: rest-timer.js, records.js, templates.js and training-tools.js.

const exercises = [];
let editingWorkout = null;
// The saved workouts as last loaded, so the list's buttons act without asking the server again.
let savedWorkouts = [];
let savedWorkoutsLoaded = false;
let activeSession = null;
let workoutsReachable = true;
let initialLoadDone = false;

$('workoutDate').value = dateInputValue(Date.now());

// The form for writing a workout down by hand opens as its own card at the top, and closes again on Cancel or once saved.
function showWorkoutBuilder(editing = false) {
  $('workoutBuilderTitle').textContent = editing ? 'Edit workout' : 'Create a workout';
  $('workoutBuilderIntro').textContent = editing ? 'Change any set, add one you missed, or take one away, then update the workout.'
    : 'Add each exercise with its weight and reps, then save it to your history.';
  $('workoutBuilderCard').hidden = false;
  $('workoutBuilderCard').scrollIntoView({ behavior:'smooth', block:'start' });
}

// The banner (showFeedback, clearFeedback) is common.js's, shared with the Cardio page.

function markInvalid(element, invalid) {
  element.setAttribute('aria-invalid', String(invalid));
}

// Changes to a saved workout go straight to the server. A new one goes into the upload queue instead (see the form's Save).
function updateSavedWorkout(workout) {
  return syncFetch(`/api/workouts/${encodeURIComponent(workout.id)}`, { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(workout) })
    .then(response => response.ok ? response.json() : Promise.reject(new Error(`Unable to save workout (${response.status}).`)));
}

function deleteWorkout(id) {
  return fetch(`/api/workouts/${id}`, { method:'DELETE' })
    .then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to delete workout.')));
}

// Saved on this device immediately; offline.js uploads it in the background (activeSession === null records that the workout ended).
function persistActiveSession() {
  saveLocalActive(activeSession);
}

function getActiveSession() {
  return syncFetch('/api/active-session')
    .then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load active workout.')))
    .then(result => result.session);
}

// An exercise saved with its sets (done in a workout) is changed a set at a time, as it was logged: each set's weight and
// reps, a set added or taken away. One written down without them is changed by its weight and reps.
function exerciseRow(item, i) {
  const name = `<input class="exercise-edit" type="text" list="exerciseNames" autocomplete="off" value="${escapeHTML(item.name)}"`
    + ` data-index="${i}" data-field="name" aria-label="Exercise name">`;
  const remove = label => `<button class="remove" type="button" data-index="${i}">${label}</button>`;
  if (!item.sets?.length) {
    return `<li class="exercise">${name}`
      + `<input class="exercise-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(item.weight || '')}"`
      + ` data-index="${i}" data-field="weight" aria-label="Exercise weight">`
      + `<input class="exercise-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(item.reps)}"`
      + ` data-index="${i}" data-field="reps" aria-label="Exercise reps">${remove('Remove')}</li>`;
  }
  const count = isTimed(item) ? { unit:'s', label:'seconds' } : { unit:'reps', label:'reps' };
  const label = number => `${escapeHTML(item.name)} set ${number}`;
  // The last set stays: an exercise with none left is removed with Remove instead.
  const sets = item.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}</span>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(set.weight || '')}"`
    + ` data-exercise="${i}" data-set="${index}" data-field="weight" aria-label="${label(index + 1)} weight in ${weightUnit()}"><span>${weightUnit()}</span></div>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(set.reps)}"`
    + ` data-exercise="${i}" data-set="${index}" data-field="reps" aria-label="${label(index + 1)} ${count.label}"><span>${count.unit}</span></div>`
    + (item.sets.length > 1 ? `<button class="remove" type="button" data-exercise="${i}" data-remove-set="${index}" aria-label="Remove ${label(index + 1)}" title="Remove">&times;</button>` : '<span></span>')
    + '</li>').join('');
  return `<li class="exercise has-sets">${name}<ol class="set-list">${sets}</ol>`
    + `<button class="secondary" type="button" data-exercise="${i}" data-add-set>Add set</button>${remove('Remove exercise')}</li>`;
}

function render() {
  const list = $('exerciseList');
  list.innerHTML = exercises.length ? exercises.map(exerciseRow).join('') : '<li class="empty">Your exercises will appear here.</li>';
  $('count').textContent = `${exercises.length} exercise${exercises.length === 1 ? '' : 's'}`;
}

// The Tracker lists the most recent workouts, the first three showing and the rest of them a tap away (Show more), since
// this list is where a workout is edited or deleted. The History page has every one.
const recentWorkoutLimit = 10;
const savedWorkoutsShown = 3;
let showingAllSaved = false;

function renderSavedWorkouts(workouts) {
  const list = $('savedWorkoutList');
  const recent = workouts.slice(0, recentWorkoutLimit);
  const folded = showingAllSaved ? 0 : Math.max(0, recent.length - savedWorkoutsShown);
  const moreButton = folded ? `<button class="secondary" type="button" data-action="more">Show ${folded} more</button>` : '';
  const historyLink = workouts.length > savedWorkoutsShown
    ? `<a class="button-link secondary" href="history.html">See all ${workouts.length} workouts in History</a>` : '';
  const more = moreButton || historyLink ? `<li class="more-workouts">${moreButton}${historyLink}</li>` : '';
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  const focusedId = focused?.closest('.saved-workout')?.dataset.id;
  const focusedAction = focused?.dataset.action;
  // One row a workout: tapping its name shows what was done, Start is the one button, and everything else (copying,
  // editing, deleting) waits in its ⋯ menu, away from a thumb reaching for Start.
  list.innerHTML = recent.length ? recent.map((workout, index) => `<li class="saved-workout" data-id="${escapeHTML(workout.id)}"`
    + `${index >= recent.length - folded ? ' hidden' : ''}>`
    + '<div class="saved-workout-summary saved-workout-row">'
    + '<button class="saved-workout-toggle" type="button" data-action="view" aria-expanded="false">'
    + `<strong>${escapeHTML(workout.name)}</strong><span>${escapeHTML(describeWorkoutDate(workout))}</span></button>`
    + '<div class="row-actions"><button class="primary" type="button" data-action="start">Start</button>'
    + `<details class="row-menu"><summary class="secondary" aria-label="More for ${escapeHTML(workout.name)}">&middot;&middot;&middot;</summary>`
    + '<div class="row-menu-items"><button type="button" data-action="repeat">Copy as new</button><button type="button" data-action="edit">Edit</button>'
    + '<button class="danger" type="button" data-action="delete">Delete</button></div></details></div></div>'
    + `<div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}`
    + `<ul>${inUnit(workout).exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong>`
      + `<span>${escapeHTML(describeSavedExercise(item))}</span></li>`).join('')}</ul>`
    + '</div></li>').join('') + more
    : '<li class="empty">No saved workouts yet.</li>';
  // Drawn again (after a sync, say) while a button in the list has the focus, the same button gets it back.
  if (focusedId) list.querySelector(`.saved-workout[data-id="${focusedId}"] [data-action="${focusedAction}"]`)?.focus({ preventScroll:true });
  renderRecentWorkouts();
}

// Up to three different workouts from the recent ones, to start again in one tap. The one done longest ago comes first:
// someone going round a rotation (push, pull, legs) is most likely due for it next. While a program is being followed,
// its card says what is next, so its workouts are left out here.
function renderRecentWorkouts() {
  const picked = new Map();
  for (const workout of savedWorkouts.slice(0, recentWorkoutLimit)) {
    if (picked.size === 3) break;
    if (currentProgram && workout.program) continue;
    if (!picked.has(exerciseKey(workout.name))) picked.set(exerciseKey(workout.name), workout);
  }
  const recent = [...picked.values()].sort((a, b) => a.createdAt - b.createdAt);
  $('recentCard').hidden = !recent.length;
  $('recentList').innerHTML = recent.map((workout, index) => `<li class="recent-workout"><div><strong>${escapeHTML(workout.name)}</strong>`
    + `<span>Last done ${new Date(workout.createdAt).toLocaleDateString(undefined, { month:'short', day:'numeric' })}`
    + ` &middot; ${workout.exercises.length} exercise${workout.exercises.length === 1 ? '' : 's'}</span></div>`
    + `<button class="${index === 0 ? 'primary' : 'secondary'}" type="button" data-recent-id="${escapeHTML(workout.id)}">Start</button></li>`).join('');
}

// Names suggested wherever an exercise is typed (the <datalist> every exercise field uses): everything logged, spelled
// the way it was most recently, then the exercises added on Progress, the templates' and the program's. Picking one keeps
// "Bench press" and "Bench Press" from becoming two exercises.
function renderExerciseSuggestions() {
  const names = new Map();
  const add = name => { const key = exerciseKey(name ?? ''); if (key && !names.has(key)) names.set(key, String(name).trim()); };
  [...savedWorkouts, ...readPendingWorkouts()].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => add(item.name)));
  Object.values(lastPerformance).sort((a, b) => b.date - a.date).forEach(entry => add(entry.name));
  Object.values(exerciseLibrary).forEach(entry => add(entry.name));
  getAllTemplates().forEach(template => template.exercises.forEach(item => add(item.name)));
  if (currentProgram) {
    programDays(currentProgram).forEach((entry, day) => programDefinition(currentProgram).workout(currentProgram, 0, day).forEach(item => add(item.name)));
  }
  $('exerciseNames').innerHTML = [...names.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity:'base' }))
    .map(name => `<option value="${escapeHTML(name)}"></option>`).join('');
}

function loadWorkoutIntoForm(stored, editMode) {
  // In the unit shown; saving it again stores it in that unit.
  const workout = inUnit(stored);
  showWorkoutBuilder(editMode);
  editingWorkout = editMode ? workout : null;
  $('workoutName').value = workout.name;
  $('workoutDate').value = editMode ? dateInputValue(workout.createdAt) : dateInputValue(Date.now());
  $('workoutNotes').value = workout.notes || '';
  // The sets are copied, so a change abandoned with Cancel leaves the saved workout as it was.
  exercises.splice(0, exercises.length, ...workout.exercises.map(item => {
    if (!editMode) { const { sets, ...plan } = item; return plan; }
    return { ...item, ...(Array.isArray(item.sets) ? { sets:item.sets.map(set => ({ ...set })) } : {}) };
  }));
  $('saveBtn').textContent = editMode ? 'Update workout' : 'Save workout';
  render();
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
    return `<li><button type="button" data-jump="${index}"${index === currentIndex ? ' aria-current="step"' : ''}${done ? ' class="done"' : ''}>`
      + `<span class="jump-name">${index + 1}. ${escapeHTML(exercise.name)}${superset}</span>`
      + `<span class="jump-sets">${escapeHTML(status)}</span></button></li>`;
  }).join('');
}

function showExerciseJump(open) {
  $('exerciseJump').hidden = !open;
  $('activeWorkoutProgress').setAttribute('aria-expanded', String(open));
}

function renderActiveWorkout() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  exercise.sets = exercise.sets || [];
  const timed = isTimed(exercise);
  const previous = lastTime(exercise.name);
  const previousFirst = previous ? { ...previous.sets[0], weight:prefillWeight(previous.sets[0].weight, previous.converted) } : null;
  const lastSet = exercise.sets[exercise.sets.length - 1];
  // A workout from a training program plans every set, so the next set is whichever planned one has not been logged yet.
  const plan = Array.isArray(exercise.plan) && exercise.plan.length ? exercise.plan : null;
  const planned = plan ? plan[exercise.sets.length] : null;
  $('activeWorkoutTitle').textContent = activeSession.name;
  renderActiveProgress();
  $('activeExerciseName').textContent = exercise.name;
  $('activeExerciseTarget').textContent = plan ? plannedTarget(exercise, previous)
    : `Target: ${exercise.reps} ${timed ? 'seconds' : 'reps'}${exercise.weight ? ` at ${formatWeight(exercise.weight)} ${weightUnit()}` : ''}`;
  $('activePlan').hidden = !plan;
  const planState = index => index < exercise.sets.length ? 'done' : index === exercise.sets.length ? 'current' : 'upcoming';
  // A set done shows what was lifted, which may not be what was planned.
  const chip = (set, index) => {
    const logged = exercise.sets[index];
    return logged ? formatPlannedSet({ weight:isBodyweight(logged.weight) ? '' : logged.weight, reps:logged.reps }) : formatPlannedSet(set);
  };
  $('activePlan').innerHTML = plan ? plan.map((set, index) => `<li class="${planState(index)}">${escapeHTML(chip(set, index))}</li>`).join('') : '';
  $('activeExerciseLast').hidden = !previous;
  if (previous) {
    const when = new Date(previous.date).toLocaleDateString(undefined, { month:'short', day:'numeric' });
    $('activeExerciseLast').textContent = `Last time (${when}): ${describeLoggedSets(previous.sets, timed)}`;
  }
  $('completedRepsLabel').textContent = timed ? 'Seconds' : 'Reps completed';
  $('holdTimer').hidden = !timed;
  $('activeNotes').value = activeSession.notes || '';
  if (planned) {
    // A planned set with no weight (an assistance exercise) takes the set just logged, or last time's.
    const plannedWeight = planned.weight === '' || planned.weight === undefined || planned.weight === null ? null : planned.weight;
    $('activeWeight').value = plannedWeight ?? (lastSet ? lastSet.weight || '' : (previousFirst && previousFirst.weight) || '');
    // A rep range (8–12) takes the reps just done, or last time's, and starts at the bottom of the range.
    $('completedReps').value = planned.repsMax ? (lastSet || previousFirst || planned).reps || '' : planned.reps || '';
  } else {
    // Next set defaults to the set just logged, or to last time's first set, so repeating a set is one tap. A timed
    // exercise done for the first time starts from its target, so its timer is ready to start.
    $('activeWeight').value = lastSet ? lastSet.weight || '' : exercise.weight || (previousFirst && previousFirst.weight) || '';
    $('completedReps').value = (lastSet || previousFirst || (timed ? { reps:exercise.reps } : {})).reps || '';
  }
  showPlates();
  renderExerciseNote();
  renderSuperset();
  renderProgression(exercise, previous);
  renderPastSessions(exercise);
  renderEffort(exercise);
  const count = timed ? { unit:'s', label:'seconds' } : { unit:'reps', label:'reps' };
  const effort = set => set.rir !== undefined && set.rir !== null ? `<small class="set-effort">${Number(set.rir) >= 4 ? '4+' : set.rir} left</small>` : '';
  $('completedSets').innerHTML = exercise.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}${effort(set)}</span>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(set.weight || '')}"`
    + ` data-set="${index}" data-field="weight" aria-label="Set ${index + 1} weight in ${weightUnit()}"><span>${weightUnit()}</span></div>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(set.reps)}" data-set="${index}"`
    + ` data-field="reps" aria-label="Set ${index + 1} ${count.label}"><span>${count.unit}</span></div>`
    + `<button class="remove" type="button" data-remove-set="${index}" aria-label="Remove set ${index + 1}" title="Remove">&times;</button></li>`).join('');
  $('completedSetsToggle').hidden = !exercise.sets.length;
  // The list is folded away, so its label says what was just logged: "Completed sets (3) · last 145 lbs × 6".
  $('completedSetsSummary').textContent = `Completed sets (${exercise.sets.length})`
    + (lastSet ? ` · last ${describeLoggedSets([lastSet], timed)}` : '');
  syncHoldDisplay();
  $('activeSyncNotice').hidden = !activeSyncFailed;
}

// Going to another exercise, ending a workout or starting one closes whatever was open for the exercise before.
function closeExercisePanels() {
  $('exerciseMenu').open = false;
  stopHold();
  showExerciseJump(false);
  showSwap(false);
  showNotePanel(false);
}

function goToExercise(index) {
  closeExercisePanels();
  effortChoice = null;
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
  closeExercisePanels();
  activeSession = null;
  stopRestTimer();
  $('restPanel').hidden = true;
  showActiveCard(false);
  syncWakeLock();
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
  $('activeWorkout').scrollIntoView({ behavior:'smooth', block:'start' });
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
  // Records are against everything before this workout, so they are worked out before it joins the bests.
  const records = newRecords(workout, personalBests);
  rememberLastPerformance(workout);
  rememberBests(workout);
  queuePendingWorkout(workout);
  // Marks the program's day done (and may start its next cycle); says what comes next.
  const programNote = activeSession.programDay ? completeProgramWorkout(activeSession) : '';
  closeActiveWorkout();
  showWorkoutSummary(workout, records);
  const synced = await flushPendingWorkouts();
  const note = (skipped ? ` ${skipped} exercise${skipped === 1 ? '' : 's'} with no sets ${skipped === 1 ? 'was' : 'were'} left out.` : '')
    + (programNote ? ` ${programNote}` : '');
  showFeedback(synced ? `“${workout.name}” saved successfully.${note}`
    : `“${workout.name}” is saved on this device and will sync when the server is reachable again.${note}`, 'success');
}

function renderStorageStatus() {
  const waiting = readPendingWorkouts().length;
  // Nothing to say while everything is saved to the account; the line only speaks up when something is not.
  const parts = workoutsReachable ? [] : ['Server unreachable'];
  if (waiting) parts.push(`${waiting} workout${waiting === 1 ? '' : 's'} waiting to sync`);
  const refused = readRejectedWorkouts().length;
  if (refused) parts.push(`${refused} workout${refused === 1 ? '' : 's'} refused by the server (kept on this device)`);
  $('storageStatus').textContent = parts.join(' · ');
}

async function loadSavedWorkouts() {
  try {
    // Strength workouts only: cardio sessions have the Cardio page, and no exercises for last time or the records.
    const workouts = (await getSavedWorkouts()).filter(workout => !isCardio(workout));
    savedWorkouts = workouts;
    savedWorkoutsLoaded = true;
    renderSavedWorkouts(workouts);
    lastPerformance = buildLastPerformance([...workouts, ...readPendingWorkouts()]);
    saveLastPerformance();
    personalBests = bestsOf([...workouts, ...readPendingWorkouts()]);
    writeLocal(localKey('bests'), personalBests);
    renderExerciseSuggestions();
    // The program card's Progress is drawn from the workouts, which have only now arrived.
    renderProgram();
    workoutsReachable = true;
    renderStorageStatus();
    return workouts;
  } catch (error) {
    workoutsReachable = false;
    renderStorageStatus();
    console.error('Unable to load saved workouts.', error);
    return null;
  }
}

// A link from History says what to do with one of the saved workouts once they have loaded: ?start= starts it, ?edit=
// opens it in the form to change, and ?copy= opens it there as a new workout. It is taken off the address, so a reload
// does not do it again.
function takeRequestedWorkout() {
  const params = new URLSearchParams(location.search);
  const action = ['start', 'edit', 'copy'].find(name => params.has(name));
  if (!action) return null;
  const id = Number(params.get(action));
  params.delete(action);
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  return { action, id };
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
  const workout = requested && workouts.find(item => item.id === requested.id);
  if (!workout) return;
  if (requested.action === 'start') startWorkout(workout);
  else loadWorkoutIntoForm(workout, requested.action === 'edit');
}

$('addBtn').onclick = () => {
  const name = $('exercise').value.trim(), weight = $('weight').value, reps = $('reps').value;
  markInvalid($('exercise'), !name);
  markInvalid($('reps'), !reps || Number(reps) < 1);
  markInvalid($('weight'), weight !== '' && Number(weight) < 0);
  if (!name) { showFeedback('Enter an exercise name before adding it.'); $('exercise').focus(); return; }
  if (!reps || Number(reps) < 1) { showFeedback('Enter at least 1 rep for this exercise.'); $('reps').focus(); return; }
  if (!Number.isInteger(Number(reps))) { markInvalid($('reps'), true); showFeedback('Reps must be a whole number.'); $('reps').focus(); return; }
  if (weight !== '' && Number(weight) < 0) { showFeedback('Weight cannot be negative.'); $('weight').focus(); return; }
  const doubt = implausibleSet({ name }, { weight:Number(weight) || 0, reps:Number(reps) });
  if (doubt && !confirm(doubt.message)) { markInvalid($(doubt.field), true); $(doubt.field).focus(); return; }
  clearFeedback();
  exercises.push({ name, weight, reps }); $('exercise').value = ''; $('weight').value = ''; $('reps').value = ''; render(); $('exercise').focus();
};
// Tap the banner to dismiss it; opening settings also clears it so a stale message never sits over the dialog.
$('formFeedback').onclick = clearFeedback;
$('settingsButton').addEventListener('click', clearFeedback);
$('createWorkoutBtn').onclick = () => { showWorkoutBuilder(Boolean(editingWorkout)); $('workoutName').focus({ preventScroll:true }); };
$('exercise').oninput = () => markInvalid($('exercise'), false);
$('weight').oninput = () => markInvalid($('weight'), false);
$('reps').oninput = () => markInvalid($('reps'), false);
$('exerciseList').oninput = e => {
  const index = e.target.dataset.index;
  const field = e.target.dataset.field;
  if (index !== undefined && field) exercises[+index][field] = e.target.value;
};
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

// A set's weight or reps is taken once it is changed; one that is not valid snaps back, as during a workout.
$('exerciseList').onchange = e => {
  const item = exercises[Number(e.target.dataset.exercise)];
  const set = item?.sets?.[Number(e.target.dataset.set)];
  const field = e.target.dataset.field;
  if (!set || !field) return;
  const value = e.target.value;
  if (field === 'reps' && (!value || Number(value) < 1)) {
    showFeedback(isTimed(item) ? 'Seconds must be at least 1.' : 'Reps must be at least 1.');
    e.target.value = set.reps;
    return;
  }
  if (field === 'reps' && !isTimed(item) && !Number.isInteger(Number(value))) { showFeedback('Reps must be a whole number.'); e.target.value = set.reps; return; }
  if (field === 'weight' && value !== '' && Number(value) < 0) { showFeedback('Weight cannot be negative.'); e.target.value = set.weight || ''; return; }
  if (!confirmSetChange(item, Number(e.target.dataset.set), field, Number(value) || 0, e.target)) return;
  set[field] = Number(value) || 0;
  clearFeedback();
};
$('exerciseList').onclick = e => {
  const button = e.target.closest('button');
  if (!button) return;
  const item = exercises[Number(button.dataset.exercise)];
  if (item && button.dataset.removeSet !== undefined) {
    item.sets.splice(Number(button.dataset.removeSet), 1);
    render();
  } else if (item && button.hasAttribute('data-add-set')) {
    // A set forgotten at the time: another like the last, its reps ready to change.
    const last = item.sets[item.sets.length - 1];
    item.sets.push({ weight:last.weight, reps:last.reps });
    render();
    document.querySelector(`#exerciseList [data-exercise="${exercises.indexOf(item)}"][data-set="${item.sets.length - 1}"][data-field=reps]`)?.focus();
  } else if (button.classList.contains('remove') && button.dataset.index !== undefined) {
    exercises.splice(Number(button.dataset.index), 1);
    render();
  }
};
$('activeNotes').oninput = () => { if (activeSession) { activeSession.notes = $('activeNotes').value; persistActiveSession(); } };
$('clearBtn').onclick = () => {
  editingWorkout = null;
  exercises.length = 0;
  $('workoutName').value = '';
  $('workoutDate').value = dateInputValue(Date.now());
  $('workoutNotes').value = '';
  $('saveBtn').textContent = 'Save workout';
  render();
  $('workoutBuilderCard').hidden = true;
};
// Equipment that always carries a weight (see exerciseDetails in exercise-library.js).
const loadedEquipment = ['barbell', 'dumbbell', 'machine', 'cable', 'kettlebell'];

function logSet() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const timed = isTimed(exercise);
  // Complete set during a hold ends it there, logging the seconds held so far.
  if (holdInterval) stopHold(true);
  const reps = Number($('completedReps').value);
  const weightValue = $('activeWeight').value;
  markInvalid($('completedReps'), !reps || reps < 1);
  markInvalid($('activeWeight'), weightValue !== '' && Number(weightValue) < 0);
  if (!reps || reps < 1) {
    showFeedback(timed ? 'Enter the seconds held for this set.' : 'Enter the reps completed for this set.');
    $('completedReps').focus();
    return;
  }
  // A rep is done or not; a hold's seconds are left as typed.
  if (!timed && !Number.isInteger(reps)) {
    markInvalid($('completedReps'), true);
    showFeedback('Reps must be a whole number.');
    $('completedReps').focus();
    return;
  }
  if (weightValue !== '' && Number(weightValue) < 0) { showFeedback('Weight cannot be negative.'); $('activeWeight').focus(); return; }
  // No weight logs the set as bodyweight. For an exercise that is always loaded, that is more likely a weight left out
  // (a new exercise has none to start from) than meant, so it is asked first. A 0 typed in is taken as meant.
  if (weightValue === '' && !timed && loadedEquipment.includes(exerciseDetails(exercise.name).equipment)
    && !confirm(`No weight entered for ${exercise.name}. Log ${reps} reps with no weight?`)) {
    markInvalid($('activeWeight'), true);
    $('activeWeight').focus();
    return;
  }
  // A set far past anything done before is asked about too (see implausibleSet in records.js).
  const doubt = implausibleSet(exercise, { weight:Number(weightValue) || 0, reps }, exercise.sets);
  if (doubt && !confirm(doubt.message)) {
    const input = doubt.field === 'weight' ? $('activeWeight') : $('completedReps');
    markInvalid(input, true);
    input.focus();
    return;
  }
  clearFeedback();
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
  if (goalReached) {
    celebrate($('completeSetBtn'), 64, 1.6);
    showFeedback(`Goal reached: ${goalReached.name}, ${formatWeight(goalReached.target)} ${goalReached.unit || 'lbs'}!`, 'success');
  } else if (recordNow && recordNow !== recordBefore) celebrate($('completeSetBtn'));
  unlockAudio();
  // A tap: the moment a phone that refused the keep-awake video (see syncWakeLock) is asked again.
  syncWakeLock();
  // A superset goes straight on to its next exercise, with no rest until the round is done.
  const index = activeSession.currentIndex;
  const next = nextInRound(activeSession, index);
  if (next !== null) {
    stopRestTimer();
    $('restPanel').hidden = true;
    moveWithinSuperset(next);
    showFeedback(`Next in the superset: ${activeSession.exercises[next].name}.`, 'success');
    return;
  }
  if (getWorkoutSettings().autoRest) startRestTimer();
  else { stopRestTimer(); restRemaining = restTotal = restDuration(); updateRestTimer(); $('restPanel').hidden = false; }
  // The round is done: rest, then the superset starts again from its first exercise with sets left.
  const first = supersetMembers(activeSession, index).length > 1 ? firstWithSetsLeft(activeSession, index) : null;
  if (first !== null && first !== index) moveWithinSuperset(first);
}

$('completeSetBtn').onclick = logSet;
$('completedReps').oninput = () => { markInvalid($('completedReps'), false); syncHoldDisplay(); };
$('activeWorkoutProgress').onclick = () => showExerciseJump($('exerciseJump').hidden);
$('otherCardsToggle').onclick = () => showOtherCards(!document.body.classList.contains('showing-all'));
$('exerciseJump').onclick = e => {
  const button = e.target.closest('[data-jump]');
  if (!button || !activeSession) return;
  const index = Number(button.dataset.jump);
  showExerciseJump(false);
  if (index !== activeSession.currentIndex && activeSession.exercises[index]) goToExercise(index);
};
// Next goes on past the superset the current exercise is in, which is done as rounds rather than one exercise at a time.
// On the last exercise it is Finish, so a second tap can arrive after the workout has closed: that one does nothing.
$('nextExerciseBtn').onclick = () => {
  if (!activeSession) return;
  const members = supersetMembers(activeSession, activeSession.currentIndex);
  const after = members[members.length - 1] + 1;
  if (after >= activeSession.exercises.length) finishWorkout();
  else goToExercise(after);
};
// Finish early ends the workout from any exercise, as Finish does on the last: the exercises with sets are saved and the
// rest left out. With some of them still to do, it asks first, since a stray tap would end the workout.
$('finishEarlyBtn').onclick = () => {
  if (!activeSession) return;
  const logged = activeSession.exercises.some(item => item.sets && item.sets.length);
  const waiting = activeSession.exercises.filter(item => !(item.sets && item.sets.length)).length;
  if (logged && waiting && !confirm(`Finish ${activeSession.name} now? ${plural(waiting, 'exercise')} with no sets will be left out.`)) return;
  finishWorkout();
};
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
// Logged sets can be corrected in place; a value that is not valid snaps back to what was logged.
$('completedSets').onchange = e => {
  const index = Number(e.target.dataset.set);
  const field = e.target.dataset.field;
  if (!activeSession || !field || Number.isNaN(index)) return;
  const set = activeSession.exercises[activeSession.currentIndex].sets[index];
  if (!set) return;
  const value = e.target.value;
  if (field === 'reps' && (!value || Number(value) < 1)) {
    showFeedback(isTimed(activeSession.exercises[activeSession.currentIndex]) ? 'Seconds must be at least 1.' : 'Reps must be at least 1.');
    e.target.value = set.reps;
    return;
  }
  if (field === 'reps' && !isTimed(activeSession.exercises[activeSession.currentIndex]) && !Number.isInteger(Number(value))) {
    showFeedback('Reps must be a whole number.');
    e.target.value = set.reps;
    return;
  }
  if (field === 'weight' && value !== '' && Number(value) < 0) { showFeedback('Weight cannot be negative.'); e.target.value = set.weight || ''; return; }
  if (!confirmSetChange(activeSession.exercises[activeSession.currentIndex], index, field, Number(value) || 0, e.target)) return;
  set[field] = Number(value) || 0;
  clearFeedback();
  persistActiveSession();
};
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
$('savedWorkoutList').onclick = async e => {
  const button = e.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'more') {
    showingAllSaved = true;
    renderSavedWorkouts(savedWorkouts);
    // Focus goes to the first of the workouts that were folded away, where reading carries on.
    $('savedWorkoutList').querySelectorAll('.saved-workout-toggle')[savedWorkoutsShown]?.focus({ preventScroll:true });
    return;
  }
  const workoutElement = button.closest('.saved-workout');
  const workoutId = Number(workoutElement.dataset.id);
  // The list on screen was drawn from savedWorkouts, so the workout a button belongs to is already here: no request,
  // and the buttons keep working if the connection drops after the list has loaded.
  const workout = savedWorkouts.find(item => item.id === workoutId);
  if (!workout) return;
  const menu = button.closest('.row-menu');
  if (menu) menu.open = false;

  if (action === 'start') startWorkout(workout);
  if (action === 'view') {
    const details = workoutElement.querySelector('.workout-details');
    const isHidden = details.hasAttribute('hidden');
    details.toggleAttribute('hidden', !isHidden);
    button.setAttribute('aria-expanded', String(isHidden));
  }
  if (action === 'repeat') loadWorkoutIntoForm(workout, false);
  if (action === 'edit') loadWorkoutIntoForm(workout, true);
  if (action === 'delete' && confirm(`Delete “${workout.name}”?`)) {
    try {
      await deleteWorkout(workout.id);
      if (editingWorkout && editingWorkout.id === workout.id) $('clearBtn').click();
      await loadSavedWorkouts();
    } catch (error) {
      showFeedback('This workout could not be deleted.');
      console.error('Unable to delete workout.', error);
    }
  }
};
$('recentList').onclick = e => {
  const button = e.target.closest('[data-recent-id]');
  const workout = button && savedWorkouts.find(item => item.id === Number(button.dataset.recentId));
  if (workout) startWorkout(workout);
};
$('saveBtn').onclick = async () => {
  if (!exercises.length) { showFeedback('Add at least one exercise before saving the workout.'); return; }
  if (!$('workoutDate').value) { showFeedback('Choose a workout date before saving.'); $('workoutDate').focus(); return; }
  // An exercise with sets takes its weight and reps from them, as finishing a workout gives them: the heaviest set, and
  // the last set's reps (or the reps a template planned, which it progresses from).
  const savedExercises = exercises.map(item => item.sets?.length
    ? { ...item, weight:Math.max(...item.sets.map(set => Number(set.weight) || 0)), reps:item.setCount ? item.reps : item.sets[item.sets.length - 1].reps }
    : { ...item });
  const workout = {
    ...editingWorkout, name:$('workoutName').value.trim() || 'Untitled workout', notes:$('workoutNotes').value.trim(), exercises:savedExercises,
    createdAt:timestampFromDateInput($('workoutDate').value), unit:weightUnit()
  };
  if (!workout.id) {
    // A new workout goes into the upload queue like a finished one, so it survives a dropped connection, and its clientId
    // lets the server ignore a retried upload. The form is cleared first, so a second tap has nothing left to save twice.
    // Once it uploads, the syncchange it reports lists it with the rest.
    workout.clientId = newClientId();
    queuePendingWorkout(workout);
    $('clearBtn').click();
    const synced = await flushPendingWorkouts();
    showFeedback(synced ? `“${workout.name}” saved successfully.`
      : `“${workout.name}” is saved on this device and will sync when the server is reachable again.`, 'success');
    return;
  }
  $('saveBtn').disabled = true;
  try {
    await updateSavedWorkout(workout);
  } catch (error) {
    showFeedback('This workout could not be saved. Check your connection and try again.');
    console.error('Unable to save workout.', error);
    return;
  } finally {
    $('saveBtn').disabled = false;
  }
  showFeedback(`“${workout.name}” saved successfully.`, 'success');
  $('clearBtn').click();
  await loadSavedWorkouts();
};

renderTemplates();
window.serverStateReady.then(() => {
  customTemplates = loadCustomTemplates();
  exerciseNotes = loadExerciseNotes();
  exerciseLibrary = loadExerciseLibrary();
  renderExerciseNote();
  renderExerciseSuggestions();
  // An exercise's equipment, which says whether it gets plates, may only arrive now.
  if (activeSession) showPlates();
  reloadProgram();
  renderTemplates();
});
// A change of unit shows everything in the new one. The workout in progress is converted and saved that way; logged
// workouts are only converted for showing (see inUnit), so switching back and forth never changes them.
function applyUnit() {
  applyUnitLabels();
  applyWeightStepper();
  if (activeSession && recordUnit(activeSession) !== weightUnit()) {
    activeSession = inUnit(activeSession);
    persistActiveSession();
  }
  if (activeSession) renderActiveWorkout();
  // Once the list has loaded, whenever that was: the unit can arrive from the server while the page is still loading.
  if (savedWorkoutsLoaded) renderSavedWorkouts(savedWorkouts);
  renderTemplates();
}

window.addEventListener('settingschange', applyUnit);
applyUnitLabels();
applyWeightStepper();
window.addEventListener('syncchange', event => {
  renderStorageStatus();
  $('activeSyncNotice').hidden = !(event.detail.activeOffline && activeSession);
  if (event.detail.uploaded && initialLoadDone) loadSavedWorkouts();
});
window.localReady.then(() => {
  lastPerformance = readLocal(localKey('lastperf')) || {};
  personalBests = readLocal(localKey('bests')) || {};
  syncTemplateArea();
  renderExerciseSuggestions();
  // Whatever goes wrong showing the workout in progress, the rest still loads: waiting workouts upload, and the saved
  // ones are listed.
  try {
    restoreLocalWorkout();
  } catch (error) {
    console.error('Unable to show the workout in progress.', error);
  }
}).then(flushPendingWorkouts).then(loadSavedWorkouts).then(resumeOrStartWorkout).finally(() => { initialLoadDone = true; syncTemplateArea(); });