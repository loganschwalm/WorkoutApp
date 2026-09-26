// Helpers shared by the Tracker, History and Progress pages. Loaded first, before any page script.

// A window property, deliberately not `const $`. On the first load after an update, a phone still running the
// previous service worker gets this file from the network but the previous page scripts from its cache, and
// those declare their own `const $`; a second const would stop them with a SyntaxError. A property lets theirs
// shadow it for that one load. The function declarations below can be redeclared the same way.
window.$ = id => document.getElementById(id);

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
}

// Through offline.js's syncFetch, so a connection that stalls rather than fails gives up instead of holding the page.
// Longer than its default, since years of workouts are a bigger download than anything else the pages ask for.
function getSavedWorkouts() {
  return syncFetch('/api/workouts', {}, 15000).then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load workouts.'))).then(result => result.workouts);
}

// Exercise names are compared this way everywhere, so "Bench press" and "Bench Press " count as the same exercise.
function exerciseKey(name) {
  return String(name).trim().toLowerCase();
}

// ---- Weight units ---------------------------------------------------------
// Weights are stored in the unit they were entered in, and every saved workout, program and workout in progress says
// which ('lbs' when it says nothing: everything from before kilograms existed). What is shown and typed is always the
// unit chosen in Settings, converted where a record's own unit differs, so switching units never rewrites what was logged.

var KG_PER_LB = 0.45359237;  // var, not const: see the note on $ above

function weightUnit() {
  return typeof getWorkoutSettings === 'function' && getWorkoutSettings().unit === 'kg' ? 'kg' : 'lbs';
}

function recordUnit(record) {
  return record && record.unit === 'kg' ? 'kg' : 'lbs';
}

// A weight in another unit, to 2 decimals, so converting back gives the weight that was entered. No weight ('') and
// anything that is not a number stay as they are.
function convertWeight(value, from, to) {
  if (from === to || value === '' || value === null || value === undefined) return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return Math.round((from === 'lbs' ? number * KG_PER_LB : number / KG_PER_LB) * 100) / 100;
}

// How a weight reads: up to two decimals and no trailing zeros (45, 101.25, 102.06), so a 1.25 kg step stays exact.
function formatWeight(value) {
  const number = Number(value);
  return value === '' || value === null || value === undefined || !Number.isFinite(number) ? String(value ?? '') : String(Math.round(number * 100) / 100);
}

// A workout (or a workout in progress) with every weight in `to`: each exercise's weight, its logged sets and its
// planned sets, and those of the exercise it was swapped for, if it was. One already in that unit comes back as it is,
// so treat the result as read-only.
function inUnit(record, to = weightUnit()) {
  const from = recordUnit(record);
  if (from === to) return record;
  const convert = set => ({ ...set, weight:convertWeight(set.weight, from, to) });
  const exerciseIn = exercise => ({ ...exercise, weight:convertWeight(exercise.weight, from, to),
    ...(Array.isArray(exercise.sets) ? { sets:exercise.sets.map(convert) } : {}), ...(Array.isArray(exercise.plan) ? { plan:exercise.plan.map(convert) } : {}),
    ...(exercise.swappedFrom ? { swappedFrom:exerciseIn(exercise.swappedFrom) } : {}) });
  return { ...record, unit:to, exercises:(record.exercises || []).map(exerciseIn) };
}

// Every "lbs" label on the page (a <span class="unit-label">) follows the unit.
function applyUnitLabels() {
  document.querySelectorAll('.unit-label').forEach(label => { label.textContent = weightUnit(); });
}

// No weight, or a weight of 0, is a bodyweight exercise. Anything else, even text that is not a number, is shown as is.
function isBodyweight(weight) {
  return weight === '' || weight === null || weight === undefined || Number(weight) === 0;
}

// A timed exercise (a plank, a dead hang) is held rather than repeated: its reps, and its sets' reps, are seconds.
function isTimed(exercise) {
  return Boolean(exercise) && exercise.timed === true;
}

// Logged sets written compactly, one part per run of sets at the same weight: "3 × 5 at 185 lbs", "115 lbs × 5, 5, 5,
// 5, 9", "40 lbs × 5 · 50 lbs × 5", and for bodyweight "3 × 10" or "10, 9, 8 reps". Sets of a timed exercise are in
// seconds: "3 × 30 s", "45, 40 s". The weights must already be in the unit shown (see inUnit).
function describeLoggedSets(sets, timed = false) {
  const unit = weightUnit();
  const runs = [];
  sets.forEach(set => {
    const last = runs[runs.length - 1];
    if (last && String(last.weight) === String(set.weight ?? '')) last.reps.push(set.reps);
    else runs.push({ weight:set.weight ?? '', reps:[set.reps] });
  });
  const each = timed ? ' s' : '';
  return runs.map(({ weight, reps }) => {
    const repeated = reps.length > 1 && reps.every(rep => String(rep) === String(reps[0]));
    if (isBodyweight(weight)) return repeated ? `${reps.length} × ${reps[0]}${each}` : `${reps.join(', ')}${timed ? ' s' : ' reps'}`;
    return repeated ? `${reps.length} × ${reps[0]}${each} at ${formatWeight(weight)} ${unit}` : `${formatWeight(weight)} ${unit} × ${reps.join(', ')}${each}`;
  }).join(' · ');
}

// One exercise of a saved workout: "Skipped" if it has an empty set list, its sets if it has them, and otherwise the
// weight and reps it was saved with (the workout form saves those without sets).
function describeSavedExercise(exercise) {
  if (exercise.sets && !exercise.sets.length) return 'Skipped';
  if (exercise.sets) return describeLoggedSets(exercise.sets, isTimed(exercise));
  const count = `${exercise.reps} ${isTimed(exercise) ? 's' : 'reps'}`;
  return isBodyweight(exercise.weight) ? count : `${formatWeight(exercise.weight)} ${weightUnit()} · ${count}`;
}

// "1 set", "3 sets".
function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

// A length of time as a clock: 90 is "1:30".
function clockTime(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

// How long a workout took, to the minute: "48 min", "1 h 5 min".
function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`;
}

// The line under a saved workout's name: its date, how long it took if that was recorded, and where it sits in a program.
function describeWorkoutDate(workout) {
  const parts = [new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })];
  if (Number(workout.duration) > 0) parts.push(formatDuration(Number(workout.duration)));
  if (workoutProgramLabel(workout)) parts.push(workoutProgramLabel(workout));
  return parts.join(' · ');
}

// Where in a training program a saved workout belongs ("Cycle 1, week 2 · 3s week"), or '' for any other workout.
function workoutProgramLabel(workout) {
  return workout.program && typeof workout.program.label === 'string' ? workout.program.label : '';
}

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });
