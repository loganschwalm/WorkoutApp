// Helpers shared by the Tracker, History and Progress pages. Loaded first, before any page script.

// A window property, deliberately not `const $`. On the first load after an update, a phone still running the
// previous service worker gets this file from the network but the previous page scripts from its cache, and
// those declare their own `const $`; a second const would stop them with a SyntaxError. A property lets theirs
// shadow it for that one load. The function declarations below can be redeclared the same way.
window.$ = id => document.getElementById(id);

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
}

function getSavedWorkouts() {
  return fetch('/api/workouts').then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load workouts.'))).then(result => result.workouts);
}

// Exercise names are compared this way everywhere, so "Bench press" and "Bench Press " count as the same exercise.
function exerciseKey(name) {
  return String(name).trim().toLowerCase();
}

// No weight, or a weight of 0, is a bodyweight exercise. Anything else, even text that is not a number, is shown as is.
function isBodyweight(weight) {
  return weight === '' || weight === null || weight === undefined || Number(weight) === 0;
}

// Logged sets written compactly, one part per run of sets at the same weight: "3 × 5 at 185 lbs", "115 lbs × 5, 5, 5,
// 5, 9", "40 lbs × 5 · 50 lbs × 5", and for bodyweight "3 × 10" or "10, 9, 8 reps".
function describeLoggedSets(sets) {
  const runs = [];
  sets.forEach(set => {
    const last = runs[runs.length - 1];
    if (last && String(last.weight) === String(set.weight ?? '')) last.reps.push(set.reps);
    else runs.push({ weight:set.weight ?? '', reps:[set.reps] });
  });
  return runs.map(({ weight, reps }) => {
    const repeated = reps.length > 1 && reps.every(rep => String(rep) === String(reps[0]));
    if (isBodyweight(weight)) return repeated ? `${reps.length} × ${reps[0]}` : `${reps.join(', ')} reps`;
    return repeated ? `${reps.length} × ${reps[0]} at ${weight} lbs` : `${weight} lbs × ${reps.join(', ')}`;
  }).join(' · ');
}

// One exercise of a saved workout: "Skipped" if it has an empty set list, its sets if it has them, and otherwise the
// weight and reps it was saved with (the workout form saves those without sets).
function describeSavedExercise(exercise) {
  if (exercise.sets && !exercise.sets.length) return 'Skipped';
  if (exercise.sets) return describeLoggedSets(exercise.sets);
  return isBodyweight(exercise.weight) ? `${exercise.reps} reps` : `${exercise.weight} lbs · ${exercise.reps} reps`;
}

// Where in a training program a saved workout belongs ("Cycle 1, week 2 · 3s week"), or '' for any other workout.
function workoutProgramLabel(workout) {
  return workout.program && typeof workout.program.label === 'string' ? workout.program.label : '';
}

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });
