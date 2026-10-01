// Help while training: the plates to load and the warm-up for a barbell lift, the weight buttons, swapping an exercise,
// notes kept with an exercise, supersets, going heavier, past sessions and how many reps each set had left.

// Notes kept with each exercise from one workout to the next, by exerciseKey ("bench press": "Grip on the rings").
let exerciseNotes = loadExerciseNotes();
// How many reps the next set had left, when that is asked (Settings); null until one of the buttons is tapped.
let effortChoice = null;

function loadExerciseNotes() {
  const stored = readLocalState('exerciseNotes');
  return stored && stored.value && typeof stored.value === 'object' && !Array.isArray(stored.value) ? stored.value : {};
}

// What to load on each side of the bar, with the bar and plates from Settings (gymEquipment in settings.js): by default a
// 45 lb bar and pound plates down to the 1.25s that a weight in 2.5 lb steps (as 5/3/1 can round to) needs, or a 20 kg
// bar and kilogram plates. Only for a lift done with a barbell: the equipment chosen for it on Progress, or else what its
// name tells (exercise-library.js): Bench Press yes, Dumbbell Bench Press or Leg Press no.
const barName = equipment => `${formatWeight(equipment.bar)} ${equipment.unit === 'kg' ? 'kg' : 'lb'} bar`;

// The fewest plates that make each side, heaviest first. Taking the heaviest plate that fits each time does not always
// manage that: with 2.5s and 2s but no 1.25s, 4 a side is two 2s, and the heaviest first would stop at 2.5. So it
// counts, in quarters (the finest plate there is), the fewest plates for every load up to the side's, and then takes
// the heaviest plate that still leads to that fewest. A weight the plates cannot make exactly (187 lbs) gets the
// nearest lighter load, and says what that comes to.
function platesPerSide(weight, equipment = gymEquipment()) {
  const side = Math.max(0, Math.floor(((weight - equipment.bar) / 2) * 4 + 1e-6));
  const sizes = equipment.plates.map(plate => Math.round(plate * 4));
  const fewest = [0];
  for (let load = 1; load <= side; load++) {
    fewest[load] = Math.min(Infinity, ...sizes.filter(size => size <= load).map(size => fewest[load - size] + 1));
  }
  let load = side;
  while (fewest[load] === Infinity) load--;
  const plates = [];
  for (let left = load; left > 0;) {
    const index = sizes.findIndex(size => size <= left && fewest[left - size] === fewest[left] - 1);
    plates.push(equipment.plates[index]);
    left -= sizes[index];
  }
  return { plates, makes:equipment.bar + load / 2 };
}

function isBarbellExercise(exercise) {
  return Boolean(exercise) && exerciseDetails(exercise.name).equipment === 'barbell';
}

// Warm-up sets to work up to a barbell lift's working weight: the empty bar for 10, then about 40%, 60% and 80% of the
// weight for 5, 3 and 2, to the nearest weight step (5 lbs, or 2.5 kg, unless Settings says otherwise), each heavier
// than the one before and lighter than the work.
function warmupSets(weight, equipment = gymEquipment()) {
  if (!(weight > equipment.bar)) return [];
  const step = equipment.step;
  const sets = [{ weight:equipment.bar, reps:10 }];
  [[0.4, 5], [0.6, 3], [0.8, 2]].forEach(([share, reps]) => {
    const load = Math.round(weight * share / step) * step;
    if (load > sets[sets.length - 1].weight && load < weight) sets.push({ weight:load, reps });
  });
  return sets;
}

// Before the first set of a barbell lift, the warm-up to its weight (Settings can turn this off). A program that plans
// its own warm-ups (5/3/1's) already says them set by set.
function showWarmups() {
  const exercise = activeSession ? activeSession.exercises[activeSession.currentIndex] : null;
  const planned = exercise && Array.isArray(exercise.plan) && exercise.plan.some(set => set.warmup);
  const sets = exercise && getWorkoutSettings().warmupSets !== false && isBarbellExercise(exercise) && !isTimed(exercise) && !planned && !exercise.sets.length
    ? warmupSets(Number($('activeWeight').value)) : [];
  $('warmupHint').hidden = !sets.length;
  if (sets.length) $('warmupHint').textContent = `Warm up first: ${sets.map(set => `${formatWeight(set.weight)} × ${set.reps}`).join(', ')} (${weightUnit()})`;
}

function showPlates() {
  showWarmups();
  const exercise = activeSession ? activeSession.exercises[activeSession.currentIndex] : null;
  const weight = Number($('activeWeight').value);
  const equipment = gymEquipment();
  const applies = isBarbellExercise(exercise) && weight >= equipment.bar;
  $('plateHint').hidden = !applies;
  if (!applies) return;
  const { plates, makes } = platesPerSide(weight, equipment);
  if (!plates.length) { $('plateHint').textContent = `Just the ${barName(equipment)}`; return; }
  // Each plate drawn to its size, the heaviest tallest, in the order they go on. The " + " between them is only for
  // screen readers, which read the whole line as "Each side of a 45 lb bar: 45 + 25 + 2.5".
  $('plateHint').innerHTML = `<span>Each side of a ${escapeHTML(barName(equipment))}: </span><span class="plates">`
    + plates.map(plate => `<span class="plate plate-size-${equipment.plates.indexOf(plate)}">${formatWeight(plate)}</span>`).join('<span class="visually-hidden"> + </span>')
    + '</span>' + (makes !== weight ? `<span> (makes ${escapeHTML(formatWeight(makes))} ${weightUnit()})</span>` : '');
}

// ---- Swapping an exercise ---------------------------------------------------
// Swap does another exercise in this one's place, for when its equipment is taken. The new exercise keeps the sets and
// rep range still to do, but not the weights: those were for the old exercise, so the new one starts from its own last
// time. Sets already logged stay with the old exercise, and the new one follows it with the sets left. Swapping back to
// the original brings its planned weights back. A program's main lift that is swapped out does not move the program's
// weights (mainLiftHit in program.js), though the day still counts as done.
function showSwap(open) {
  $('swapPanel').hidden = !open;
  $('swapToggle').setAttribute('aria-expanded', String(open));
  if (!open || !activeSession) return;
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const logged = exercise.sets.length;
  const planned = Array.isArray(exercise.plan) ? exercise.plan.length : 0;
  const main = Boolean(activeSession.programDay) && activeSession.currentIndex === 0 && planned > 0;
  $('swapName').value = '';
  markInvalid($('swapName'), false);
  $('swapHelp').textContent = [
    logged
      ? `${loggedSetsStay(logged, exercise.name)}, and the new exercise gets `
        + `${planned ? `the ${plural(planned - logged, 'set')} left` : 'the sets from here on'}.`
      : `The new exercise keeps ${planned ? `the ${plural(planned, 'planned set')} and their reps`
        : `the target of ${exercise.reps} ${isTimed(exercise) ? 'seconds' : 'reps'}`}, with weights of your own.`,
    main ? `${exercise.name} is this day's main lift, so while it is swapped out the program leaves its weight alone.` : ''
  ].filter(Boolean).join(' ');
  $('swapName').focus();
}

// "The set you logged stays with Bench Press", "The 2 sets you logged stay with Bench Press".
function loggedSetsStay(count, name) {
  return count === 1 ? `The set you logged stays with ${name}` : `The ${count} sets you logged stay with ${name}`;
}

function withoutSets(exercise) {
  const { sets, swappedFrom, swappedOut, ...rest } = exercise;
  return rest;
}

function swapExercise() {
  const name = $('swapName').value.trim();
  markInvalid($('swapName'), !name);
  if (!name) { showFeedback('Enter the exercise to do instead.'); $('swapName').focus(); return; }
  const session = activeSession, index = session.currentIndex, exercise = session.exercises[index];
  if (exerciseKey(name) === exerciseKey(exercise.name)) { showSwap(false); return; }
  const logged = exercise.sets.length;
  const plan = Array.isArray(exercise.plan) && exercise.plan.length ? exercise.plan : null;
  if (plan && logged >= plan.length) { showFeedback(`Every planned set of ${exercise.name} is done. Add an exercise instead.`); return; }
  // What the workout had here before any swap, to come back to.
  const original = exercise.swappedFrom || withoutSets(exercise);
  const left = plan ? plan.length - logged : 0;
  const replacement = exerciseKey(name) === exerciseKey(original.name)
    ? { ...original, ...(Array.isArray(original.plan) && left ? { plan:original.plan.slice(-left) } : {}), sets:[] }
    : { name, weight:'', reps:exercise.reps, sets:[], swappedFrom:original,
      ...(isTimed(exercise) ? { timed:true } : {}), ...(exercise.rest ? { rest:exercise.rest } : {}),
      ...(plan ? { plan:plan.slice(logged).map(set => ({
        weight:'', reps:set.reps, ...(set.repsMax ? { repsMax:set.repsMax } : {}), ...(set.warmup ? { warmup:true } : {})
      })) } : {}),
      ...(exercise.group ? { group:exercise.group } : {}) };
  closeExercisePanels();
  if (logged) {
    // The sets done stay with the exercise they were done on, which ends there.
    exercise.swappedOut = true;
    if (plan) exercise.plan = plan.slice(0, logged);
    session.exercises.splice(index + 1, 0, replacement);
    session.currentIndex = index + 1;
  } else session.exercises[index] = replacement;
  persistActiveSession();
  renderActiveWorkout();
  showFeedback(`Swapped ${exercise.name} for ${replacement.name}.${logged ? ` ${loggedSetsStay(logged, exercise.name)}.` : ''}`, 'success');
}

// ---- Notes kept with an exercise ----------------------------------------------
// A note ("seat on 4") belongs to the exercise, not the workout: it shows whenever that exercise comes up. A program's
// own setup notes (Apartment Gym's "Bench at 30–45°") are part of its target line instead.
function noteFor(name) {
  return exerciseNotes[exerciseKey(name)] || '';
}

function renderExerciseNote() {
  if (!activeSession) return;
  const note = noteFor(activeSession.exercises[activeSession.currentIndex].name);
  $('exerciseNote').hidden = !note;
  $('exerciseNote').textContent = note;
  $('noteToggle').textContent = note ? 'Edit note' : 'Add note';
}

function showNotePanel(open) {
  $('notePanel').hidden = !open;
  $('noteToggle').setAttribute('aria-expanded', String(open));
  if (!open || !activeSession) return;
  $('noteText').value = noteFor(activeSession.exercises[activeSession.currentIndex].name);
  $('noteText').focus();
}

function saveExerciseNote() {
  const name = activeSession.exercises[activeSession.currentIndex].name;
  const note = $('noteText').value.trim();
  exerciseNotes = { ...exerciseNotes };
  if (note) exerciseNotes[exerciseKey(name)] = note;
  else delete exerciseNotes[exerciseKey(name)];
  saveLocalState('exerciseNotes', exerciseNotes);
  showNotePanel(false);
  renderExerciseNote();
  showFeedback(note ? `Note saved for ${name}.` : `Note removed from ${name}.`, 'success');
}

// ---- Supersets ----------------------------------------------------------------
// Exercises next to each other with the same group are a superset: one set of each in turn, and the rest only once the
// round is done. Next moves on past the whole superset.

// The positions of the exercises in the superset the one at `index` is in: just [index] when it is in none.
function supersetMembers(session, index) {
  const group = session.exercises[index]?.group;
  if (!group) return [index];
  let first = index, last = index;
  while (first > 0 && session.exercises[first - 1].group === group) first -= 1;
  while (last < session.exercises.length - 1 && session.exercises[last + 1].group === group) last += 1;
  return Array.from({ length:last - first + 1 }, (entry, offset) => first + offset);
}

// Whether an exercise still has sets to do: a planned one until its plan is done, any other for as long as the superset
// goes on (Next ends it). One swapped out is done.
function hasSetsLeft(exercise) {
  if (exercise.swappedOut) return false;
  return Array.isArray(exercise.plan) && exercise.plan.length ? exercise.sets.length < exercise.plan.length : true;
}

// After a set, the next exercise in the round, or null when the round is done (or it is no superset).
function nextInRound(session, index) {
  const members = supersetMembers(session, index);
  if (members.length < 2) return null;
  return members.find(member => member > index && hasSetsLeft(session.exercises[member])) ?? null;
}

function firstWithSetsLeft(session, index) {
  return supersetMembers(session, index).find(member => hasSetsLeft(session.exercises[member])) ?? null;
}

// To another exercise of the superset, leaving the rest timer as it is.
function moveWithinSuperset(index) {
  closeExercisePanels();
  activeSession.currentIndex = index;
  persistActiveSession();
  renderActiveWorkout();
}

// Groups made or broken mid-workout kept tidy: one group to a run of neighbours, and none on an exercise left on its own.
function tidySupersets(session) {
  const seen = new Set();
  let index = 0;
  while (index < session.exercises.length) {
    const members = supersetMembers(session, index);
    const group = session.exercises[index].group;
    if (group && (members.length < 2 || seen.has(group))) {
      const fresh = members.length < 2 ? null : `s${Date.now().toString(36)}${index}`;
      members.forEach(member => { if (fresh) session.exercises[member].group = fresh; else delete session.exercises[member].group; });
    }
    if (session.exercises[index].group) seen.add(session.exercises[index].group);
    index = members[members.length - 1] + 1;
  }
}

function renderSuperset() {
  const session = activeSession, index = session.currentIndex;
  const members = supersetMembers(session, index);
  const inOne = members.length > 1;
  $('supersetLine').hidden = !inOne;
  if (inOne) {
    const others = members.filter(member => member !== index).map(member => session.exercises[member].name);
    $('supersetLine').textContent = `Superset with ${others.join(' and ')}: a set of each in turn, then rest.`;
  }
  $('supersetToggle').hidden = !inOne && index === session.exercises.length - 1;
  $('supersetToggle').textContent = inOne ? 'Leave superset' : 'Superset with next';
}

function toggleSuperset() {
  const session = activeSession, index = session.currentIndex, exercise = session.exercises[index];
  if (supersetMembers(session, index).length > 1) {
    delete exercise.group;
    tidySupersets(session);
    showFeedback(`${exercise.name} is no longer in a superset.`, 'success');
  } else {
    const next = session.exercises[index + 1];
    if (!next) return;
    exercise.group = next.group || `s${Date.now().toString(36)}`;
    next.group = exercise.group;
    tidySupersets(session);
    showFeedback(`${exercise.name} and ${next.name} are now a superset.`, 'success');
  }
  persistActiveSession();
  renderActiveWorkout();
}

// ---- Go heavier ---------------------------------------------------------------
// For an exercise with no plan (a template or a workout done before), once every set at last time's weight reached its
// target, it says to go up a step: the weight step from Settings (5 lbs or 2.5 kg unless changed), as the weight buttons
// do. The target is the exercise's reps, or the
// first set's if that was more, so a set that fell away (8, 8, 6) does not count as reaching it. A set logged with no
// reps left means the weight is still enough. A program says this in its own way.
function progressionFor(exercise, previous) {
  if (!previous || isTimed(exercise) || (Array.isArray(exercise.plan) && exercise.plan.length) || exercise.sets.length) return null;
  const top = Math.max(0, ...previous.sets.map(set => Number(set.weight) || 0));
  const target = Number(exercise.reps);
  if (!(top > 0) || !(target >= 1)) return null;
  const atTop = previous.sets.filter(set => (Number(set.weight) || 0) === top);
  const needed = Math.max(target, Number(atTop[0].reps) || 0);
  if (!atTop.every(set => Number(set.reps) >= needed) || atTop.some(set => set.rir === 0)) return null;
  const step = gymEquipment().step;
  return { from:top, to:Math.round((Math.round(top / step) * step + step) * 100) / 100, reps:needed };
}

// ---- Progression in your own templates ----------------------------------------
// A template exercise with a number of sets (setCount) is planned set by set, as a program's are: 3 × 8–12, or 3 × 5
// without a range. Its weight comes from last time: once every planned set reached the top of the range (or the reps,
// without one) at last time's heaviest weight, it goes up a weight step from Settings; otherwise it stays there until
// they do. That is double progression, as Apartment Gym's main lifts go. With nothing logged, or only bodyweight, the
// weight is the lifter's call. A saved workout started again carries the same setCount, so it progresses too.
function templateProgression(name, count, top) {
  const previous = lastTime(name);
  if (!previous || !previous.sets.length) return null;
  const heaviest = Math.max(0, ...previous.sets.map(set => Number(set.weight) || 0));
  if (!(heaviest > 0)) return null;
  const from = prefillWeight(heaviest, previous.converted);
  const atHeaviest = previous.sets.filter(set => (Number(set.weight) || 0) === heaviest);
  const up = atHeaviest.length >= count && atHeaviest.every(set => Number(set.reps) >= top);
  const step = gymEquipment().step;
  return { from, up, top, weight:up ? Math.round((Math.round(from / step) * step + step) * 100) / 100 : from };
}

// A template's (or a saved workout's) exercise as the workout in progress takes it: with its sets planned when it has a
// set count, at the weight its progression gives. Anything else is left as it is, a program's plan included.
function templateSession(item) {
  const count = Math.floor(Number(item.setCount));
  if (!(count >= 1)) return item;
  const reps = Number(item.reps) || 0;
  const repsMax = !isTimed(item) && Number(item.repsMax) > reps ? Number(item.repsMax) : null;
  const progression = isTimed(item) ? null : templateProgression(item.name, count, repsMax || reps);
  const weight = progression ? progression.weight : '';
  return { ...item, weight, plan:repeatSets(count, { weight, reps, ...(repsMax ? { repsMax } : {}) }) };
}

// The line under a planned template exercise before its first set says why its weight is what it is.
function templateAdvice(exercise) {
  if (!exercise.setCount || exercise.sets.length || isTimed(exercise)) return '';
  const plan = exercise.plan[0];
  const progression = templateProgression(exercise.name, Math.floor(Number(exercise.setCount)), plan.repsMax || plan.reps);
  if (!progression) return '';
  const unit = weightUnit();
  const reps = `${progression.top} ${progression.top === 1 ? 'rep' : 'reps'}`;
  return progression.up ? ` Up from ${formatWeight(progression.from)} ${unit}: last time every set reached ${reps}.`
    : ` The same as last time until every set reaches ${reps}.`;
}

function renderProgression(exercise, previous) {
  const hint = progressionFor(exercise, previous);
  $('progressionHint').hidden = !hint;
  if (!hint) return;
  const unit = weightUnit();
  const reps = `${hint.reps} ${hint.reps === 1 ? 'rep' : 'reps'}`;
  $('progressionText').textContent = `Last time every set at ${formatWeight(hint.from)} ${unit} reached ${reps}: time to go heavier.`;
  $('progressionUse').textContent = `Use ${formatWeight(hint.to)} ${unit}`;
  $('progressionUse').dataset.weight = String(hint.to);
}

// ---- Past sessions ------------------------------------------------------------
// The last few times this exercise was done, from saved workouts and any still uploading, newest first, with a link to
// all of them on the Progress page.
const pastSessionLimit = 5;

function pastSessionsOf(name) {
  const key = exerciseKey(name);
  return [...savedWorkouts, ...readPendingWorkouts()]
    .filter(workout => workout.exercises.some(item => exerciseKey(item.name) === key && (!item.sets || item.sets.length)))
    .sort((a, b) => b.createdAt - a.createdAt)
    .slice(0, pastSessionLimit)
    .map(workout => {
      const items = inUnit(workout).exercises.filter(item => exerciseKey(item.name) === key && (!item.sets || item.sets.length));
      const efforts = describeEfforts(items.flatMap(item => item.sets || []));
      return { date:workout.createdAt, name:workout.name, sets:items.map(describeSavedExercise).join(' · ') + (efforts ? ` · ${efforts}` : '') };
    });
}

function renderPastSessions(exercise) {
  const sessions = pastSessionsOf(exercise.name);
  $('pastSessions').hidden = !sessions.length;
  const day = date => new Date(date).toLocaleDateString(undefined, { month:'short', day:'numeric' });
  $('pastSessionList').innerHTML = sessions.map(session => `<li><span>${escapeHTML(day(session.date))} · ${escapeHTML(session.name)}</span>`
    + `<span>${escapeHTML(session.sets)}</span></li>`).join('');
  $('exerciseHistoryLink').href = `progress.html?exercise=${encodeURIComponent(exerciseKey(exercise.name))}`;
}

// ---- Effort -------------------------------------------------------------------
// How many more reps a set had in it, tapped before Complete set: 0 (none) to 4 or more. Optional, and asked only when
// Settings says so; a timed hold is not asked.
function effortAsked(exercise) {
  return getWorkoutSettings().trackEffort !== false && !isTimed(exercise);
}

function renderEffort(exercise) {
  $('effortChoices').hidden = !effortAsked(exercise);
  $('effortChoices').querySelectorAll('[data-effort]')
    .forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.effort) === effortChoice)));
}

$('noteToggle').onclick = () => showNotePanel($('notePanel').hidden);
$('noteCancel').onclick = () => showNotePanel(false);
$('noteSave').onclick = saveExerciseNote;
$('supersetToggle').onclick = toggleSuperset;
$('progressionUse').onclick = () => {
  $('activeWeight').value = $('progressionUse').dataset.weight;
  $('activeWeight').dispatchEvent(new Event('input', { bubbles:true }));
};
$('effortChoices').onclick = e => {
  const button = e.target.closest('[data-effort]');
  if (!button || !activeSession) return;
  // Tapping the one already chosen takes it back.
  effortChoice = effortChoice === Number(button.dataset.effort) ? null : Number(button.dataset.effort);
  renderEffort(activeSession.exercises[activeSession.currentIndex]);
};

$('swapToggle').onclick = () => showSwap($('swapPanel').hidden);
// Whatever is picked from the exercise's ⋯ menu closes it.
$('exerciseMenu').querySelector('.row-menu-items').addEventListener('click', e => { if (e.target.closest('button')) $('exerciseMenu').open = false; });
$('swapCancel').onclick = () => showSwap(false);
$('swapBtn').onclick = swapExercise;
$('swapName').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); swapExercise(); } };
$('swapName').oninput = () => markInvalid($('swapName'), false);

// −5 and +5 beside the weight: a change of 2.5 lbs a side, the smallest most plate sets make. In kilograms, −2.5 and
// +2.5: 1.25 kg a side. Settings can choose another weight step.
function applyWeightStepper() {
  const step = gymEquipment().step;
  $('weightStepper').querySelectorAll('[data-weight-step]').forEach(button => {
    const heavier = Number(button.dataset.weightStep) > 0;
    button.dataset.weightStep = String(heavier ? step : -step);
    button.textContent = `${heavier ? '+' : '\u2212'}${step}`;
    button.setAttribute('aria-label', `${step} ${weightUnit()} ${heavier ? 'heavier' : 'lighter'}`);
  });
}

$('weightStepper').onclick = e => {
  const step = Number(e.target.closest('[data-weight-step]')?.dataset.weightStep);
  if (!step) return;
  const input = $('activeWeight');
  input.value = String(Math.max(0, (Number(input.value) || 0) + step));
  input.dispatchEvent(new Event('input', { bubbles:true }));
};
$('activeWeight').oninput = () => { markInvalid($('activeWeight'), false); showPlates(); };
