// Helpers shared by the Tracker, History and Progress pages. Loaded first, before any page script.

// A window property, deliberately not `const $`. On the first load after an update, a phone still running the
// previous service worker gets this file from the network but the previous page scripts from its cache, and
// those declare their own `const $`; a second const would stop them with a SyntaxError. A property lets theirs
// shadow it for that one load. The function declarations below can be redeclared the same way.
window.$ = id => document.getElementById(id);

// A dialog hands focus back to whatever opened it when it closes, so the keyboard carries on from there rather than from
// the top of the page. If the opener has gone (its list was drawn again), focus is left where it is.
const dialogOpeners = new Map();

function rememberOpener(dialog) {
  dialogOpeners.set(dialog, document.activeElement);
}

function returnFocus(dialog) {
  const opener = dialogOpeners.get(dialog);
  dialogOpeners.delete(dialog);
  if (opener && opener !== document.body && opener.isConnected) opener.focus({ preventScroll:true });
}

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
}

// The banner on the Strength and Cardio pages (#formFeedback) sticks to the top of the screen, so a message is seen
// wherever the page is scrolled. Errors stay until dismissed; successes and notes ('info') dismiss themselves. An action
// ({ label, run }), such as Undo, adds a button that lasts as long as the banner does, so the banner then stays up a
// little longer. Its timer is kept on the function rather than in a variable, which a script.js from before this moved
// here, served from the cache for one load, declares for itself (see the note on $ above).
function showFeedback(message, type = 'error', action = null) {
  const feedback = $('formFeedback');
  feedback.textContent = message;
  if (action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'feedback-action';
    button.textContent = action.label;
    // Kept from reaching the banner, whose own click dismisses it; running the action decides what shows next.
    button.onclick = event => { event.stopPropagation(); clearFeedback(); action.run(); };
    feedback.append(' ', button);
  }
  feedback.className = `form-feedback ${type}`;
  feedback.hidden = false;
  clearTimeout(showFeedback.timer);
  if (type !== 'error') showFeedback.timer = setTimeout(clearFeedback, action ? 10000 : 6000);
}

function clearFeedback() {
  clearTimeout(showFeedback.timer);
  $('formFeedback').hidden = true;
  $('formFeedback').textContent = '';
}

// A day as a date field takes it ("2026-09-30"), where this device is; and the time a date field's day means, at noon.
function dateInputValue(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function timestampFromDateInput(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, 12).getTime();
}

// A small firework: sparks flying out of an element, gone after a second, for a record. Skipped for anyone who asks for
// less motion. Its colours are inside it: records.js, before this moved here, kept them in a const of its own.
function celebrate(origin, sparks = 28, reach = 1) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colours = ['#f5b83d', '#ff6b6b', '#5bd6a4', '#8183f4', '#4cc3ff'];
  const box = origin.getBoundingClientRect();
  const burst = document.createElement('div');
  burst.className = 'firework';
  burst.setAttribute('aria-hidden', 'true');
  burst.style.left = `${box.left + box.width / 2}px`;
  burst.style.top = `${box.top + box.height / 2}px`;
  for (let i = 0; i < sparks; i++) {
    const angle = (i / sparks) * 2 * Math.PI + Math.random() * 0.3;
    const distance = (60 + Math.random() * 70) * reach;
    const spark = document.createElement('i');
    spark.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
    spark.style.setProperty('--dy', `${Math.sin(angle) * distance}px`);
    spark.style.background = colours[i % colours.length];
    burst.appendChild(spark);
  }
  document.body.appendChild(burst);
  setTimeout(() => burst.remove(), 1200);
}

// A cardio session (the Cardio page) is saved as a workout with kind 'cardio' and no exercises; anything else is a strength
// workout, which is everything saved before cardio existed.
function isCardio(workout) {
  return Boolean(workout) && workout.kind === 'cardio';
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

// ---- Calendar days ----------------------------------------------------------
// Days and weeks as this device counts them, which is how a workout's day is told: a workout at 11pm counts on that day wherever
// the server is. Weeks start on Monday, as the History calendar draws them. A day or a week is a Date at midnight; a day's key is
// its date as year-month-day, which is what a day is called in the calendar, the bodyweight log and the schedule.

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

// Monday of the week a date is in.
function startOfWeek(date) {
  return addDays(startOfDay(date), -((date.getDay() + 6) % 7));
}

function calendarDayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// Midnight at the start of a day given by its key, as a time.
function dayStart(key) {
  const [year, month, day] = key.split('-').map(Number);
  return new Date(year, month - 1, day).getTime();
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

// ---- Estimated one-rep max -------------------------------------------------
// Epley's formula, as estimateOneRepMax in program.js, to 2 decimals so that close results still compare. Only sets of up
// to ONE_REP_MAX_REPS reps count, beyond which the estimate stops meaning much. A window property, not a const: a
// script.js from before this moved here, served from the cache for one load, declares its own (see the note on $).
window.ONE_REP_MAX_REPS = 12;

function exactOneRepMax(weight, reps) {
  return Math.round((reps <= 1 ? weight : weight * (1 + reps / 30)) * 100) / 100;
}

// "1 set", "3 sets".
function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

// How the week stands against the goal: "This week: 2 of 4 workouts", or once it is reached "This week: 4 workouts · goal of 4 reached".
function weekGoalLine(count, goal) {
  return count >= goal ? `This week: ${plural(count, 'workout')} · goal of ${goal} reached` : `This week: ${count} of ${plural(goal, 'workout')}`;
}

// How many reps each set had left, for sets where that was recorded: "reps left 2, 1, 0" (4 is 4 or more). '' if none.
function describeEfforts(sets) {
  const efforts = (sets || []).filter(set => set.rir !== undefined && set.rir !== null).map(set => Number(set.rir) >= 4 ? '4+' : String(set.rir));
  return efforts.length ? `reps left ${efforts.join(', ')}` : '';
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

// An open ⋯ menu (a saved workout's, an exercise's, the program's) closes when anything else is tapped, another menu
// included, or on Escape.
document.addEventListener('click', event => {
  // Picking one of its items closes it too.
  const picked = event.target.closest('.row-menu-items button');
  document.querySelectorAll('.row-menu[open]').forEach(menu => { if (!menu.contains(event.target) || picked) menu.open = false; });
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelectorAll('.row-menu[open]').forEach(menu => { menu.open = false; });
});

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });
