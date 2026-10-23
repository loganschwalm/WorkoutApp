// The Tracker's state, and starting the page. What the Tracker does is in the files loaded before this one, each declaring functions and
// handlers that read the state below only when they run: workout-form.js (writing a workout down, changing a saved one),
// saved-workouts.js (the list on the page), active-workout.js (the workout in progress), set-logging.js (logging and correcting sets),
// beside rest-timer.js, records.js, templates.js and training-tools.js.

const exercises = [];
let editingWorkout = null;
// The workout being edited as it was kept, in its own unit, which the form shows in the unit chosen (see backToUnit).
let editingStored = null;
// The saved workouts as last loaded, so the list's buttons act without asking the server again.
let savedWorkouts = [];
// Everything saved, cardio sessions too, which is what a training day is counted from (schedule.js).
let savedSessions = [];
let savedWorkoutsLoaded = false;
let activeSession = null;
let workoutsReachable = true;
let initialLoadDone = false;

$('workoutDate').value = dateInputValue(Date.now());
// A line to start on, picked once a visit (achievements.js). The workout in progress has the screen to itself, so it is not
// shown then (see body.training).
$('splashLine').textContent = splashLine('idle');
$('splashLine').hidden = false;

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

// Tap the banner to dismiss it; opening settings also clears it so a stale message never sits over the dialog.
$('formFeedback').onclick = clearFeedback;
$('settingsButton').addEventListener('click', clearFeedback);
renderTemplates();
// The account's templates, notes, library and program as stored: the server's once it answers, and another tab's once it
// changes them (accountstatechange in offline.js), so a change made here never goes up without one made there.
function takeAccountState() {
  customTemplates = loadCustomTemplates();
  exerciseNotes = loadExerciseNotes();
  exerciseLibrary = loadExerciseLibrary();
  renderExerciseNote();
  renderExerciseSuggestions();
  // An exercise's equipment, which says whether it gets plates, may only arrive now.
  if (activeSession) showPlates();
  reloadProgram();
  renderTemplates();
}
window.serverStateReady.then(takeAccountState);
window.addEventListener('accountstatechange', takeAccountState);
// A change of unit shows everything in the new one. The workout in progress is converted and saved that way; logged
// workouts are only converted for showing (see inUnit), so switching back and forth never changes them.
function applyUnit() {
  applyUnitLabels();
  applyWeightStepper();
  // Any setting can change while a set is half typed (Settings, What's new, onboarding, another device's change arriving), and
  // drawing the workout again starts the entry fields over, so what was typed is put back, in the new unit if that changed.
  const typed = activeSession ? { weight:$('activeWeight').value, reps:$('completedReps').value, unit:recordUnit(activeSession) } : null;
  if (activeSession && recordUnit(activeSession) !== weightUnit()) {
    activeSession = inUnit(activeSession);
    persistActiveSession();
  }
  if (activeSession) {
    renderActiveWorkout();
    $('activeWeight').value = convertWeight(typed.weight, typed.unit, weightUnit());
    $('completedReps').value = typed.reps;
    showPlates();
  }
  // Once the list has loaded, whenever that was: the unit can arrive from the server while the page is still loading.
  if (savedWorkoutsLoaded) renderSavedWorkouts(savedWorkouts);
  renderTemplates();
  // Last week's totals are in the units shown, and its streak is against the weekly goal: both are settings. What's new goes
  // once it has been seen, which is a setting too.
  renderRecap();
  renderWhatsNew();
}

window.addEventListener('settingschange', applyUnit);
// The shortcut Today's workout, chosen while the Tracker is already open, only changes the address (startTodaysWorkout, schedule.js).
window.addEventListener('hashchange', () => { if (initialLoadDone) startTodaysWorkout(); });
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
}).then(flushPendingWorkouts).then(loadSavedWorkouts).then(resumeOrStartWorkout).finally(() => {
  initialLoadDone = true;
  // A new account's welcome (onboarding.js) comes once the page has started and the workout in progress, if there is one, is
  // back on screen, since a workout under way keeps it away; and once the account's settings are in, since one that has been
  // welcomed on another device never sees it again. A chain of its own, so it comes even when the start went wrong (which
  // still fails where it is seen), and nothing it does can stop the page: a missing onboarding.js (an older page from the
  // cache) or one that throws only leaves the Tracker without it. Asked first, but it runs after the line below all the same.
  window.serverStateReady.then(() => { if (typeof maybeStartOnboarding === 'function') maybeStartOnboarding(); })
    .catch(error => console.error('Unable to start the welcome.', error));
  syncTemplateArea();
});
