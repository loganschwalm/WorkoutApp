const exercises = [];
let editingWorkout = null;
// The saved workouts as last loaded, so the list's buttons act without asking the server again.
let savedWorkouts = [];
let savedWorkoutsLoaded = false;
// Weight/reps an exercise had when its logged sets were loaded for editing; used to tell whether the user changed them.
const setBaselines = new WeakMap();
let activeSession = null;
let restInterval = null;
let restEndsAt = null;
let wakeLock = null;
let wakeLockRequesting = false;
let workoutsReachable = true;
let initialLoadDone = false;
let feedbackTimer = null;
let lastPerformance = {};
let personalBests = {};
let restRemaining = getWorkoutSettings().restDuration;
// The countdown for a set of a timed exercise, from an end time like the rest timer's.
let holdInterval = null;
let holdEndsAt = null;
let holdLength = 0;
let customTemplates = loadCustomTemplates();
let editingTemplateId = null;
let templateDraftExercises = [];
const templates = [
  { name:'Push Day', exercises:[{ name:'Bench Press', weight:'', reps:'8' }, { name:'Overhead Press', weight:'', reps:'8' }, { name:'Tricep Pushdown', weight:'', reps:'12' }] },
  { name:'Pull Day', exercises:[{ name:'Deadlift', weight:'', reps:'5' }, { name:'Barbell Row', weight:'', reps:'8' }, { name:'Lat Pulldown', weight:'', reps:'10' }, { name:'Bicep Curl', weight:'', reps:'12' }] },
  { name:'Leg Day', exercises:[{ name:'Back Squat', weight:'', reps:'8' }, { name:'Romanian Deadlift', weight:'', reps:'10' }, { name:'Leg Press', weight:'', reps:'10' }, { name:'Calf Raise', weight:'', reps:'15' }] },
  { name:'Upper Body', exercises:[{ name:'Bench Press', weight:'', reps:'8' }, { name:'Pull-up', weight:'', reps:'8' }, { name:'Dumbbell Row', weight:'', reps:'10' }, { name:'Lateral Raise', weight:'', reps:'12' }] },
  { name:'Full Body', exercises:[{ name:'Goblet Squat', weight:'', reps:'10' }, { name:'Push-up', weight:'', reps:'10' }, { name:'Dumbbell Row', weight:'', reps:'10' }, { name:'Plank', weight:'', reps:'30', timed:true }] }
];

function dateInputValue(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function timestampFromDateInput(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, 12).getTime();
}

$('workoutDate').value = dateInputValue(Date.now());

// The form for writing a workout down by hand opens as its own card at the top, and closes again on Cancel or once saved.
function showWorkoutBuilder(editing = false) {
  $('workoutBuilderTitle').textContent = editing ? 'Edit workout' : 'Create a workout';
  $('workoutBuilderCard').hidden = false;
  $('workoutBuilderCard').scrollIntoView({ behavior:'smooth', block:'start' });
}

// The banner sticks to the top of the screen so a message is seen wherever the page is scrolled. Errors stay until
// dismissed; successes and notes ('info') dismiss themselves. An action ({ label, run }), such as Undo, adds a button
// that lasts as long as the banner does, so the banner then stays up a little longer.
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
  clearTimeout(feedbackTimer);
  if (type !== 'error') feedbackTimer = setTimeout(clearFeedback, action ? 10000 : 6000);
}

function clearFeedback() {
  clearTimeout(feedbackTimer);
  $('formFeedback').hidden = true;
  $('formFeedback').textContent = '';
}

function markInvalid(element, invalid) {
  element.setAttribute('aria-invalid', String(invalid));
}

function persistWorkout(workout) {
  const method = workout.id ? 'PUT' : 'POST';
  const path = workout.id ? `/api/workouts/${workout.id}` : '/api/workouts';
  return fetch(path, { method, headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(workout) }).then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to save workout.')));
}

function deleteWorkout(id) {
  return fetch(`/api/workouts/${id}`, { method:'DELETE' }).then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to delete workout.')));
}

// Saved on this device immediately; offline.js uploads it in the background (activeSession === null records that the workout ended).
function persistActiveSession() {
  saveLocalActive(activeSession);
}

function getActiveSession() {
  return fetch('/api/active-session').then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load active workout.'))).then(result => result.session);
}

// Kept per account by offline.js, which uploads a change as soon as the server can be reached.
function loadCustomTemplates() {
  const stored = readLocalState('templates');
  return stored && Array.isArray(stored.value) ? stored.value : [];
}

function saveCustomTemplates() {
  saveLocalState('templates', customTemplates);
}

function getAllTemplates() {
  return [...templates.map((template, index) => ({ ...template, id:`built-in-${index}`, builtIn:true })), ...customTemplates.map(template => ({ ...template, builtIn:false }))];
}

function render() {
  const list = $('exerciseList');
  list.innerHTML = exercises.length ? exercises.map((item, i) => `<li class="exercise"><input class="exercise-edit" type="text" list="exerciseNames" autocomplete="off" value="${escapeHTML(item.name)}" data-index="${i}" data-field="name" aria-label="Exercise name"><input class="exercise-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(item.weight || '')}" data-index="${i}" data-field="weight" aria-label="Exercise weight"><input class="exercise-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(item.reps)}" data-index="${i}" data-field="reps" aria-label="Exercise reps"><button class="remove" type="button" data-index="${i}">Remove</button></li>`).join('') : '<li class="empty">Your exercises will appear here.</li>';
  $('count').textContent = `${exercises.length} exercise${exercises.length === 1 ? '' : 's'}`;
}

// The Tracker lists the most recent workouts; the History page has every one.
const recentWorkoutLimit = 10;

function renderSavedWorkouts(workouts) {
  const list = $('savedWorkoutList');
  const recent = workouts.slice(0, recentWorkoutLimit);
  const more = workouts.length > recent.length ? `<li class="more-workouts"><a class="button-link secondary" href="history.html">See all ${workouts.length} workouts in History</a></li>` : '';
  // One row a workout: tapping its name shows what was done, Start is the one button, and everything else (copying,
  // editing, deleting) waits in its ⋯ menu, away from a thumb reaching for Start.
  list.innerHTML = recent.length ? recent.map(workout => `<li class="saved-workout" data-id="${escapeHTML(workout.id)}"><div class="saved-workout-summary saved-workout-row"><button class="saved-workout-toggle" type="button" data-action="view" aria-expanded="false"><strong>${escapeHTML(workout.name)}</strong><span>${escapeHTML(describeWorkoutDate(workout))}</span></button><div class="row-actions"><button class="primary" type="button" data-action="start">Start</button><details class="row-menu"><summary class="secondary" aria-label="More for ${escapeHTML(workout.name)}">&middot;&middot;&middot;</summary><div class="row-menu-items"><button type="button" data-action="repeat">Copy as new</button><button type="button" data-action="edit">Edit</button><button class="danger" type="button" data-action="delete">Delete</button></div></details></div></div><div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${inUnit(workout).exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(describeSavedExercise(item))}</span></li>`).join('')}</ul></div></li>`).join('') + more : '<li class="empty">No saved workouts yet.</li>';
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
  $('recentList').innerHTML = recent.map((workout, index) => `<li class="recent-workout"><div><strong>${escapeHTML(workout.name)}</strong><span>Last done ${new Date(workout.createdAt).toLocaleDateString(undefined, { month:'short', day:'numeric' })} &middot; ${workout.exercises.length} exercise${workout.exercises.length === 1 ? '' : 's'}</span></div><button class="${index === 0 ? 'primary' : 'secondary'}" type="button" data-recent-id="${escapeHTML(workout.id)}">Start</button></li>`).join('');
}

// Templates fold away once there is something else to start from (saved workouts or a program), so someone new sees
// them straight away and everyone else sees their own workouts first. The Show/Hide button's choice holds while the
// page is open. Until the first load says whether there is anything, they stay folded, so they never jump away.
let templatesChoice = null;

function syncTemplateArea() {
  const hasOwn = savedWorkouts.length > 0 || Object.keys(lastPerformance).length > 0 || Boolean(currentProgram);
  const open = templatesChoice ?? (!hasOwn && initialLoadDone);
  $('templateArea').hidden = !open;
  $('templatesToggle').textContent = open ? 'Hide templates' : `Show templates (${programDefinitions.length + getAllTemplates().length})`;
  $('templatesToggle').setAttribute('aria-expanded', String(open));
}

// Training programs (program.js) come first, then the single-workout templates. program.js calls this when the program
// changes, which also changes what Start again offers and whether the templates stay folded.
function renderTemplates() {
  $('templateList').innerHTML = programTemplateCards() + getAllTemplates().map(template => `<article class="template-card"><div><h3>${escapeHTML(template.name)}</h3><p>${template.exercises.map(item => `${escapeHTML(item.name)} (${escapeHTML(item.reps)} ${isTimed(item) ? 's' : 'reps'})`).join(' &middot; ')}</p></div><div class="template-actions"><button class="primary" type="button" data-template-action="start" data-template-id="${escapeHTML(template.id)}">Start workout</button><button class="secondary" type="button" data-template-action="duplicate" data-template-id="${escapeHTML(template.id)}">Duplicate</button>${template.builtIn ? '' : `<button class="secondary" type="button" data-template-action="edit" data-template-id="${escapeHTML(template.id)}">Edit</button><button class="danger" type="button" data-template-action="delete" data-template-id="${escapeHTML(template.id)}">Delete</button>`}</div></article>`).join('');
  renderRecentWorkouts();
  syncTemplateArea();
  renderExerciseSuggestions();
}

// Names suggested wherever an exercise is typed (the <datalist> every exercise field uses): everything logged, spelled
// the way it was most recently, then the templates' and the program's. Picking one keeps "Bench press" and "Bench
// Press" from becoming two exercises.
function renderExerciseSuggestions() {
  const names = new Map();
  const add = name => { const key = exerciseKey(name ?? ''); if (key && !names.has(key)) names.set(key, String(name).trim()); };
  [...savedWorkouts, ...readPendingWorkouts()].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => add(item.name)));
  Object.values(lastPerformance).sort((a, b) => b.date - a.date).forEach(entry => add(entry.name));
  getAllTemplates().forEach(template => template.exercises.forEach(item => add(item.name)));
  if (currentProgram) programDays(currentProgram).forEach((entry, day) => programDefinition(currentProgram).workout(currentProgram, 0, day).forEach(item => add(item.name)));
  $('exerciseNames').innerHTML = [...names.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity:'base' })).map(name => `<option value="${escapeHTML(name)}"></option>`).join('');
}

// Each exercise of a template: its name and whether it is timed, then its reps (or seconds), an optional rest after each
// set (blank for the default in Settings), and the buttons to move or remove it.
function renderTemplateExerciseEditor() {
  $('templateExerciseEditor').innerHTML = templateDraftExercises.map((exercise, index) => `<div class="template-exercise-row"><div class="template-exercise-name"><label for="templateExercise${index}">Exercise</label><input id="templateExercise${index}" type="text" list="exerciseNames" autocomplete="off" value="${escapeHTML(exercise.name)}" data-template-field="name" data-index="${index}" required /></div><label class="setting-check template-timed"><input type="checkbox" data-template-field="timed" data-index="${index}"${exercise.timed ? ' checked' : ''} /> Timed</label><div><label for="templateReps${index}" id="templateReps${index}Label">${exercise.timed ? 'Seconds' : 'Reps'}</label><input id="templateReps${index}" type="number" inputmode="numeric" min="1" value="${escapeHTML(exercise.reps)}" data-template-field="reps" data-index="${index}" required /></div><div><label for="templateRest${index}">Rest (s)</label><input id="templateRest${index}" type="number" inputmode="numeric" min="15" max="600" step="1" placeholder="${getWorkoutSettings().restDuration}" value="${escapeHTML(exercise.rest || '')}" data-template-field="rest" data-index="${index}" /></div><div class="template-row-actions"><button class="secondary" type="button" data-template-row-action="up" data-index="${index}" aria-label="Move exercise up">&#8593;</button><button class="secondary" type="button" data-template-row-action="down" data-index="${index}" aria-label="Move exercise down">&#8595;</button><button class="danger" type="button" data-template-row-action="remove" data-index="${index}" aria-label="Remove exercise">&times;</button></div></div>`).join('');
}

// What a template keeps of an exercise: its name and reps, and its rest and timing when it has them.
function templateExercise(item) {
  return { name:item.name, reps:item.reps, ...(item.rest ? { rest:item.rest } : {}), ...(isTimed(item) ? { timed:true } : {}) };
}

function openTemplateEditor(template = null) {
  editingTemplateId = template?.id || null;
  $('templateModalTitle').textContent = template ? 'Edit template' : 'Create template';
  $('templateName').value = template?.name || '';
  templateDraftExercises = template ? template.exercises.map(templateExercise) : [{ name:'', reps:'8' }];
  renderTemplateExerciseEditor();
  $('templateModal').hidden = false;
  $('templateName').focus();
}

function closeTemplateEditor() {
  $('templateModal').hidden = true;
  editingTemplateId = null;
}

function loadWorkoutIntoForm(stored, editMode) {
  // In the unit shown; saving it again stores it in that unit.
  const workout = inUnit(stored);
  showWorkoutBuilder(editMode);
  editingWorkout = editMode ? workout : null;
  $('workoutName').value = workout.name;
  $('workoutDate').value = editMode ? dateInputValue(workout.createdAt) : dateInputValue(Date.now());
  $('workoutNotes').value = workout.notes || '';
  exercises.splice(0, exercises.length, ...workout.exercises.map(item => {
    if (!editMode) { const { sets, ...plan } = item; return plan; }
    const copy = { ...item };
    if (item.sets?.length) setBaselines.set(copy, { weight:String(item.weight ?? ''), reps:String(item.reps ?? '') });
    return copy;
  }));
  $('saveBtn').textContent = editMode ? 'Update workout' : 'Save workout';
  render();
}

function updateRestTimer() {
  $('timerDisplay').textContent = clockTime(restRemaining);
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
  }
}

function runRestTimer() {
  clearInterval(restInterval);
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
  restRemaining = restDuration();
  $('restPanel').hidden = false;
  updateRestTimer();
  runRestTimer();
}

// Keeps the screen awake during a workout so the timer can alert you; the browser drops the lock whenever the page is hidden.
async function syncWakeLock() {
  const wanted = Boolean(activeSession) && !document.hidden && 'wakeLock' in navigator;
  if (wanted && !wakeLock && !wakeLockRequesting) {
    wakeLockRequesting = true;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (error) {
      console.error('Unable to keep the screen awake.', error);
    } finally {
      wakeLockRequesting = false;
    }
  } else if (!wanted && wakeLock) {
    await wakeLock.release();
  }
}

function normalizeSets(sets) {
  return sets.map(set => ({ weight:Number(set.weight) || 0, reps:Number(set.reps) || 0 }));
}

// The most recent real performance of each exercise (skipped exercises are ignored); shown and used to prefill the next session.
function buildLastPerformance(workouts) {
  const latest = {};
  [...workouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (latest[key]) return;
    // The name as it was typed, for suggesting it (the key is lowercased).
    const entry = { name:String(item.name).trim(), date:workout.createdAt, unit:recordUnit(workout) };
    if (item.sets && item.sets.length) latest[key] = { ...entry, sets:normalizeSets(item.sets) };
    else if (!item.sets) latest[key] = { ...entry, sets:normalizeSets([{ weight:item.weight, reps:item.reps }]) };
  }));
  return latest;
}

function saveLastPerformance() {
  writeLocal(localKey('lastperf'), lastPerformance);
}

// Updated as soon as a workout is finished, so the next session shows it even if the upload is still waiting.
function rememberLastPerformance(workout) {
  workout.exercises.forEach(item => { lastPerformance[exerciseKey(item.name)] = { name:String(item.name).trim(), date:workout.createdAt, unit:recordUnit(workout), sets:normalizeSets(item.sets) }; });
  saveLastPerformance();
  renderExerciseSuggestions();
}

// ---- Personal records -----------------------------------------------------
// The best each exercise has done in every saved workout (and any still uploading), kept on this device so a finished
// workout can be told its records at once, online or not. Weights are kept in pounds whatever they were logged in, so
// workouts in either unit compare. Per exercise: the heaviest weight, the best estimated one-rep max, the most reps in
// a set without weight, and for a timed exercise the longest hold. One-rep maxes come only from sets of up to 12 reps,
// beyond which the estimate stops meaning much.
const ONE_REP_MAX_REPS = 12;

// Epley's formula, as estimateOneRepMax in program.js, to 2 decimals so that close results still compare.
function exactOneRepMax(weight, reps) {
  return Math.round((reps <= 1 ? weight : weight * (1 + reps / 30)) * 100) / 100;
}

function bestsOf(workouts) {
  const bests = {};
  workouts.forEach(workout => workout.exercises.forEach(item => {
    // The workout form saves an exercise without sets: its weight and reps are its one set.
    const sets = item.sets || [{ weight:item.weight, reps:item.reps }];
    if (!sets.length) return;
    const key = exerciseKey(item.name);
    const best = bests[key] || (bests[key] = { weight:0, oneRepMax:0, reps:0, seconds:0 });
    sets.forEach(set => {
      const reps = Number(set.reps) || 0;
      const weight = convertWeight(Number(set.weight) || 0, recordUnit(workout), 'lbs');
      if (isTimed(item)) best.seconds = Math.max(best.seconds, reps);
      else if (weight > 0) {
        best.weight = Math.max(best.weight, weight);
        if (reps >= 1 && reps <= ONE_REP_MAX_REPS) best.oneRepMax = Math.max(best.oneRepMax, exactOneRepMax(weight, reps));
      } else best.reps = Math.max(best.reps, reps);
    });
  }));
  return bests;
}

function rememberBests(workout) {
  Object.entries(bestsOf([workout])).forEach(([key, best]) => {
    const had = personalBests[key];
    personalBests[key] = had ? Object.fromEntries(Object.keys(best).map(field => [field, Math.max(had[field] || 0, best[field])])) : best;
  });
  writeLocal(localKey('bests'), personalBests);
}

// What a finished workout did better than every workout before it, a sentence each. An exercise done for the first
// time has nothing to beat, so it sets no record, and each exercise names its best record only: a heavier weight, else
// a better estimated one-rep max (more reps at a weight), else more reps without weight; or a timed exercise's longer hold.
function newRecords(workout, before) {
  const from = recordUnit(workout), unit = weightUnit();
  const fromPounds = pounds => `${formatWeight(convertWeight(pounds, 'lbs', unit))} ${unit}`;
  const exercises = new Map();
  workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (!exercises.has(key)) exercises.set(key, { name:String(item.name).trim(), timed:isTimed(item), sets:[] });
    // Sets as done, with each weight in pounds too, to compare.
    exercises.get(key).sets.push(...(item.sets || []).map(set => ({ reps:Number(set.reps) || 0, weight:Number(set.weight) || 0, pounds:convertWeight(Number(set.weight) || 0, from, 'lbs') })));
  });
  const records = [];
  exercises.forEach(({ name, timed, sets }, key) => {
    const best = before[key];
    if (!best || !sets.length) return;
    const top = score => sets.reduce((a, b) => score(b) > score(a) ? b : a);
    const done = set => `${formatWeight(convertWeight(set.weight, from, unit))} ${unit} × ${set.reps}`;
    if (timed) {
      const longest = top(set => set.reps);
      if (best.seconds && longest.reps > best.seconds) records.push(`${name}: held ${longest.reps} s, your longest yet (was ${best.seconds} s)`);
      return;
    }
    const heaviest = top(set => set.pounds);
    if (best.weight && heaviest.pounds > best.weight) {
      records.push(`${name}: ${done(heaviest)}, your heaviest yet (was ${fromPounds(best.weight)})`);
      return;
    }
    const counted = sets.filter(set => set.pounds > 0 && set.reps >= 1 && set.reps <= ONE_REP_MAX_REPS);
    const strongest = counted.length ? counted.reduce((a, b) => exactOneRepMax(b.pounds, b.reps) > exactOneRepMax(a.pounds, a.reps) ? b : a) : null;
    if (strongest && best.oneRepMax && exactOneRepMax(strongest.pounds, strongest.reps) > best.oneRepMax) {
      const estimate = value => `${Math.round(convertWeight(value, 'lbs', unit))} ${unit}`;
      records.push(`${name}: ${done(strongest)}, an estimated one-rep max of ${estimate(exactOneRepMax(strongest.pounds, strongest.reps))}, your best yet (was ${estimate(best.oneRepMax)})`);
      return;
    }
    const most = top(set => set.pounds > 0 ? 0 : set.reps);
    if (best.reps && most.pounds === 0 && most.reps > best.reps) records.push(`${name}: ${most.reps} reps in a set, your most yet (was ${best.reps})`);
  });
  return records;
}

// ---- The summary of a finished workout -------------------------------------
// How long it took, how much was done, and any new personal records; it stays until Done or the next workout starts.
function showWorkoutSummary(workout, records) {
  const shown = inUnit(workout);
  const sets = shown.exercises.reduce((total, item) => total + item.sets.length, 0);
  // Weight × reps of every set with a weight; a hold's seconds are not reps, so timed exercises are left out.
  const volume = shown.exercises.filter(item => !isTimed(item)).reduce((total, item) => total + item.sets.reduce((sum, set) => sum + (Number(set.weight) || 0) * (Number(set.reps) || 0), 0), 0);
  const stats = [
    ...(workout.duration ? [[formatDuration(workout.duration), 'Time']] : []),
    [String(shown.exercises.length), shown.exercises.length === 1 ? 'Exercise' : 'Exercises'],
    [String(sets), sets === 1 ? 'Set' : 'Sets'],
    ...(volume ? [[`${Math.round(volume).toLocaleString()} ${weightUnit()}`, 'Volume']] : [])
  ];
  $('summaryName').textContent = workout.name;
  $('summaryStats').innerHTML = stats.map(([value, label]) => `<li><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></li>`).join('');
  $('summaryRecords').hidden = !records.length;
  $('summaryRecordList').innerHTML = records.map(record => `<li>${escapeHTML(record)}</li>`).join('');
  $('workoutSummary').hidden = false;
  $('workoutSummary').scrollIntoView({ behavior:'smooth', block:'start' });
}

// Last time's performance of an exercise in the unit shown, or null. `converted` says it was logged in the other unit,
// so its weights are exact conversions (102.06 kg) rather than weights anyone loads; see prefillWeight.
function lastTime(name) {
  const entry = lastPerformance[exerciseKey(name)];
  if (!entry) return null;
  const from = recordUnit(entry), to = weightUnit();
  return from === to ? entry : { ...entry, unit:to, converted:true, sets:entry.sets.map(set => ({ ...set, weight:convertWeight(set.weight, from, to) })) };
}

// A weight to fill in for the next set. One converted from the other unit is rounded to the nearest half, which the
// weight buttons then step from; one logged in this unit is used as it is.
function prefillWeight(weight, converted) {
  const number = Number(weight);
  return converted && weight !== '' && Number.isFinite(number) ? Math.round(number * 2) / 2 : weight;
}

// What to load on each side of the bar: a 45 lb bar and pound plates down to the 1.25s that a weight in 2.5 lb steps (as
// 5/3/1 can round to) needs, or a 20 kg bar and kilogram plates. Only for a lift done with a barbell, which the
// exercise's name has to tell (it is all a custom exercise has): Bench Press yes, Dumbbell Bench Press or Leg Press no.
const BARBELLS = { lbs:{ bar:45, plates:[45, 35, 25, 10, 5, 2.5, 1.25], name:'45 lb bar' }, kg:{ bar:20, plates:[25, 20, 15, 10, 5, 2.5, 1.25], name:'20 kg bar' } };
const barbellNames = /\b(barbell|bench|squat|deadlift|rdl|overhead press|military press|push press|ohp|pendlay|bent[- ]over row|power clean|hang clean|good morning|hip thrust)\b/i;
const notBarbellNames = /\b(dumbbells?|db|kettlebells?|machine|cable|smith|leg press|hack|goblet|split|bulgarian|trap bar|hex bar|landmine|band|dips?|pistol)\b/i;

function platesPerSide(weight, barbell = BARBELLS[weightUnit()]) {
  let left = (weight - barbell.bar) / 2;
  const plates = [];
  barbell.plates.forEach(plate => { while (left >= plate - 1e-9) { plates.push(plate); left -= plate; } });
  // A weight the plates cannot make exactly (187 lbs) gets the nearest lighter load, and says what that comes to.
  return { plates, makes: weight - Math.round(left * 2 * 100) / 100 };
}

function showPlates() {
  const exercise = activeSession ? activeSession.exercises[activeSession.currentIndex] : null;
  const weight = Number($('activeWeight').value);
  const barbell = BARBELLS[weightUnit()];
  const applies = Boolean(exercise) && barbellNames.test(exercise.name) && !notBarbellNames.test(exercise.name) && weight >= barbell.bar;
  $('plateHint').hidden = !applies;
  if (!applies) return;
  const { plates, makes } = platesPerSide(weight, barbell);
  $('plateHint').textContent = !plates.length ? `Just the ${barbell.name}`
    : `Each side of a ${barbell.name}: ${plates.join(' + ')}${makes !== weight ? ` (makes ${formatWeight(makes)} ${weightUnit()})` : ''}`;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

// "Exercise 2 of 6" opens a list of every exercise and how far each has got, to go straight to any of them: when a
// machine is taken, do one that is free and come back.
function renderActiveProgress() {
  const { exercises, currentIndex } = activeSession;
  $('activeWorkoutProgress').textContent = `Exercise ${currentIndex + 1} of ${exercises.length}`;
  $('prevExerciseBtn').hidden = currentIndex === 0;
  $('nextExerciseBtn').textContent = currentIndex === exercises.length - 1 ? 'Finish workout' : 'Next exercise';
  $('exerciseJump').innerHTML = exercises.map((exercise, index) => {
    const sets = (exercise.sets || []).length;
    const planned = Array.isArray(exercise.plan) ? exercise.plan.length : 0;
    const done = planned ? sets >= planned : sets > 0;
    const status = planned ? `${sets} of ${plural(planned, 'set')}` : sets ? plural(sets, 'set') : 'No sets yet';
    return `<li><button type="button" data-jump="${index}"${index === currentIndex ? ' aria-current="step"' : ''}${done ? ' class="done"' : ''}><span class="jump-name">${index + 1}. ${escapeHTML(exercise.name)}</span><span class="jump-sets">${escapeHTML(status)}</span></button></li>`;
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
  $('activeExerciseTarget').textContent = plan ? plannedTarget(exercise, previous) : `Target: ${exercise.reps} ${timed ? 'seconds' : 'reps'}${exercise.weight ? ` at ${formatWeight(exercise.weight)} ${weightUnit()}` : ''}`;
  $('activePlan').hidden = !plan;
  $('activePlan').innerHTML = plan ? plan.map((set, index) => `<li class="${index < exercise.sets.length ? 'done' : index === exercise.sets.length ? 'current' : 'upcoming'}">${escapeHTML(formatPlannedSet(set))}</li>`).join('') : '';
  $('activeExerciseLast').hidden = !previous;
  if (previous) $('activeExerciseLast').textContent = `Last time (${new Date(previous.date).toLocaleDateString(undefined, { month:'short', day:'numeric' })}): ${describeLoggedSets(previous.sets, timed)}`;
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
  const count = timed ? { unit:'s', label:'seconds' } : { unit:'reps', label:'reps' };
  $('completedSets').innerHTML = exercise.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}</span><div class="set-field"><input class="set-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(set.weight || '')}" data-set="${index}" data-field="weight" aria-label="Set ${index + 1} weight in ${weightUnit()}"><span>${weightUnit()}</span></div><div class="set-field"><input class="set-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(set.reps)}" data-set="${index}" data-field="reps" aria-label="Set ${index + 1} ${count.label}"><span>${count.unit}</span></div><button class="remove" type="button" data-remove-set="${index}" aria-label="Remove set ${index + 1}">Remove</button></li>`).join('');
  syncHoldDisplay();
  $('activeSyncNotice').hidden = !activeSyncFailed;
}

// Going to another exercise, ending a workout or starting one closes whatever was open for the exercise before.
function closeExercisePanels() {
  stopHold();
  showExerciseJump(false);
  showSwap(false);
}

function goToExercise(index) {
  closeExercisePanels();
  activeSession.currentIndex = index;
  stopRestTimer();
  restRemaining = restDuration();
  updateRestTimer();
  $('restPanel').hidden = true;
  renderActiveWorkout();
  persistActiveSession();
}

function closeActiveWorkout() {
  closeExercisePanels();
  activeSession = null;
  persistActiveSession();
  stopRestTimer();
  $('restPanel').hidden = true;
  $('activeWorkout').hidden = true;
  syncWakeLock();
}

// `template` is a template, a saved workout, or a day of a training program (program.js), whose exercises carry a
// set-by-set plan and whose programDay says which day of the program it is.
function startWorkout(stored) {
  if (activeSession && getWorkoutSettings().confirmEnd && !confirm(`Replace your in-progress “${activeSession.name}” workout? Sets you have logged so far will be lost.`)) return;
  closeExercisePanels();
  stopRestTimer();
  $('restPanel').hidden = true;
  $('workoutSummary').hidden = true;
  // In the unit shown, whatever unit a saved workout was logged in; the session says which, and so will the saved workout.
  // A weight converted from the other unit becomes one to load, to the nearest half (47.63 kg is 47.5).
  const template = inUnit(stored);
  const converted = template !== stored;
  // startedAt times the workout, for its summary and History.
  activeSession = { name:template.name, notes:template.notes || '', exercises:template.exercises.map(item => ({ ...item, weight:prefillWeight(item.weight, converted), sets:[] })), currentIndex:0, clientId:newClientId(), unit:weightUnit(), startedAt:Date.now() };
  if (template.programDay) activeSession.programDay = template.programDay;
  restRemaining = restDuration();
  updateRestTimer();
  persistActiveSession();
  renderActiveWorkout();
  // Notes fold away under the set entry, unless the workout brings some with it.
  $('activeNotesToggle').open = Boolean(activeSession.notes);
  $('activeWorkout').hidden = false;
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
  // Each exercise keeps whether it is timed and its own rest, so starting the workout again brings them back.
  const exercises = performed.map(item => ({ name:item.name, weight:Math.max(...item.sets.map(set => Number(set.weight) || 0)), reps:item.sets[item.sets.length - 1].reps, sets:item.sets,
    ...(isTimed(item) ? { timed:true } : {}), ...(Number(item.rest) > 0 ? { rest:Number(item.rest) } : {}) }));
  const finishedAt = Date.now();
  const workout = { name:activeSession.name, notes:activeSession.notes || '', exercises, createdAt:finishedAt, clientId:activeSession.clientId, unit:recordUnit(activeSession) };
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
  const note = (skipped ? ` ${skipped} exercise${skipped === 1 ? '' : 's'} with no sets ${skipped === 1 ? 'was' : 'were'} left out.` : '') + (programNote ? ` ${programNote}` : '');
  showFeedback(synced ? `“${workout.name}” saved successfully.${note}` : `“${workout.name}” is saved on this device and will sync when the server is reachable again.${note}`, 'success');
}

function renderStorageStatus() {
  const waiting = readPendingWorkouts().length;
  const parts = [workoutsReachable ? 'Saved to your account' : 'Server unreachable'];
  if (waiting) parts.push(`${waiting} workout${waiting === 1 ? '' : 's'} waiting to sync`);
  const refused = readRejectedWorkouts().length;
  if (refused) parts.push(`${refused} workout${refused === 1 ? '' : 's'} refused by the server (kept on this device)`);
  $('storageStatus').textContent = parts.join(' · ');
}

async function loadSavedWorkouts() {
  try {
    const workouts = await getSavedWorkouts();
    savedWorkouts = workouts;
    savedWorkoutsLoaded = true;
    renderSavedWorkouts(workouts);
    lastPerformance = buildLastPerformance([...workouts, ...readPendingWorkouts()]);
    saveLastPerformance();
    personalBests = bestsOf([...workouts, ...readPendingWorkouts()]);
    writeLocal(localKey('bests'), personalBests);
    renderExerciseSuggestions();
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

function takeRequestedWorkoutId() {
  const params = new URLSearchParams(location.search);
  if (!params.has('start')) return null;
  const requestedId = Number(params.get('start'));
  params.delete('start');
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  return requestedId;
}

// `workouts` is null when the server could not be reached; the in-progress workout is still restored from this device.
async function resumeOrStartWorkout(workouts) {
  const requestedId = workouts ? takeRequestedWorkoutId() : null;
  const local = readLocalActive();
  let savedSession = null;
  if (local && local.dirty) {
    // Changes made here that the server has not seen yet win over the server's copy.
    savedSession = local.session;
    syncActiveSession();
  } else {
    try {
      savedSession = await getActiveSession();
      mirrorActiveSession(savedSession);
    } catch (error) {
      console.error('Unable to load active workout.', error);
      savedSession = local ? local.session : null;
    }
  }
  if (savedSession) {
    activeSession = inUnit(savedSession);
    if (activeSession !== savedSession) persistActiveSession();
    stopRestTimer();
    restRemaining = restDuration();
    updateRestTimer();
    $('restPanel').hidden = true;
    renderActiveWorkout();
    $('activeNotesToggle').open = Boolean(activeSession.notes);
    $('activeWorkout').hidden = false;
    syncWakeLock();
  }
  const requestedWorkout = requestedId === null ? null : workouts.find(workout => workout.id === requestedId);
  if (requestedWorkout) startWorkout(requestedWorkout);
}

$('addBtn').onclick = () => {
  const name = $('exercise').value.trim(), weight = $('weight').value, reps = $('reps').value;
  markInvalid($('exercise'), !name);
  markInvalid($('reps'), !reps || Number(reps) < 1);
  markInvalid($('weight'), weight !== '' && Number(weight) < 0);
  if (!name) { showFeedback('Enter an exercise name before adding it.'); $('exercise').focus(); return; }
  if (!reps || Number(reps) < 1) { showFeedback('Enter at least 1 rep for this exercise.'); $('reps').focus(); return; }
  if (weight !== '' && Number(weight) < 0) { showFeedback('Weight cannot be negative.'); $('weight').focus(); return; }
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
$('exerciseList').onclick = e => { if (e.target.classList.contains('remove') && e.target.dataset.index !== undefined) { exercises.splice(+e.target.dataset.index, 1); render(); } };
$('activeNotes').oninput = () => { if (activeSession) { activeSession.notes = $('activeNotes').value; persistActiveSession(); } };
$('clearBtn').onclick = () => { editingWorkout = null; exercises.length = 0; $('workoutName').value = ''; $('workoutDate').value = dateInputValue(Date.now()); $('workoutNotes').value = ''; $('saveBtn').textContent = 'Save workout'; render(); $('workoutBuilderCard').hidden = true; };
$('templateList').onclick = e => {
  const action = e.target.dataset.templateAction;
  const templateId = e.target.dataset.templateId;
  if (!action || !templateId) return;
  const template = getAllTemplates().find(item => item.id === templateId);
  if (!template) return;
  if (action === 'start') startWorkout(template);
  if (action === 'edit') openTemplateEditor(template);
  if (action === 'duplicate') {
    customTemplates.push({ id:`custom-${Date.now()}`, name:`${template.name} Copy`, exercises:template.exercises.map(templateExercise) });
    saveCustomTemplates();
    renderTemplates();
    showFeedback(`Created a copy of “${template.name}”.`, 'success');
  }
  if (action === 'delete' && confirm(`Delete template “${template.name}”?`)) {
    customTemplates = customTemplates.filter(item => item.id !== template.id);
    saveCustomTemplates();
    renderTemplates();
  }
};
$('templateExerciseEditor').oninput = e => {
  const index = Number(e.target.dataset.index);
  const field = e.target.dataset.templateField;
  if (!field || !templateDraftExercises[index]) return;
  if (field !== 'timed') { templateDraftExercises[index][field] = e.target.value; return; }
  // A timed exercise's count is in seconds, which its label says.
  templateDraftExercises[index].timed = e.target.checked;
  $(`templateReps${index}Label`).textContent = e.target.checked ? 'Seconds' : 'Reps';
};
$('templateExerciseEditor').onclick = e => {
  const action = e.target.dataset.templateRowAction;
  const index = Number(e.target.dataset.index);
  if (!action || !templateDraftExercises[index]) return;
  if (action === 'remove' && templateDraftExercises.length > 1) templateDraftExercises.splice(index, 1);
  if (action === 'up' && index > 0) [templateDraftExercises[index - 1], templateDraftExercises[index]] = [templateDraftExercises[index], templateDraftExercises[index - 1]];
  if (action === 'down' && index < templateDraftExercises.length - 1) [templateDraftExercises[index + 1], templateDraftExercises[index]] = [templateDraftExercises[index], templateDraftExercises[index + 1]];
  renderTemplateExerciseEditor();
};
$('addTemplateExercise').onclick = () => { templateDraftExercises.push({ name:'', reps:'8' }); renderTemplateExerciseEditor(); };
$('createTemplateBtn').onclick = () => openTemplateEditor();
$('closeTemplate').onclick = closeTemplateEditor;
$('cancelTemplate').onclick = closeTemplateEditor;
$('templateModal').onclick = event => { if (event.target === $('templateModal')) closeTemplateEditor(); };
$('templateForm').onsubmit = event => {
  event.preventDefault();
  const name = $('templateName').value.trim();
  // A rest left blank uses the default in Settings; one given is kept within the range Settings allows.
  const restOf = value => value === '' || value === undefined || !(Number(value) > 0) ? null : Math.min(600, Math.max(15, Math.round(Number(value))));
  const validExercises = templateDraftExercises.filter(item => item.name.trim() && Number(item.reps) >= 1)
    .map(item => templateExercise({ name:item.name.trim(), reps:String(Math.floor(Number(item.reps))), rest:restOf(item.rest), timed:item.timed === true }));
  if (!name || !validExercises.length) return showFeedback('Add a template name and at least one valid exercise.');
  if (editingTemplateId) {
    const existing = customTemplates.find(item => item.id === editingTemplateId);
    if (existing) { existing.name = name; existing.exercises = validExercises; }
  } else customTemplates.push({ id:`custom-${Date.now()}`, name, exercises:validExercises });
  saveCustomTemplates();
  renderTemplates();
  closeTemplateEditor();
  showFeedback(`Template “${name}” saved.`, 'success');
};
function logSet() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  const timed = isTimed(exercise);
  // Complete set during a hold ends it there, logging the seconds held so far.
  if (holdInterval) stopHold(true);
  const reps = Number($('completedReps').value);
  const weightValue = $('activeWeight').value;
  markInvalid($('completedReps'), !reps || reps < 1);
  markInvalid($('activeWeight'), weightValue !== '' && Number(weightValue) < 0);
  if (!reps || reps < 1) { showFeedback(timed ? 'Enter the seconds held for this set.' : 'Enter the reps completed for this set.'); $('completedReps').focus(); return; }
  if (weightValue !== '' && Number(weightValue) < 0) { showFeedback('Weight cannot be negative.'); $('activeWeight').focus(); return; }
  clearFeedback();
  const weight = Number(weightValue) || 0;
  exercise.sets.push({ reps, weight });
  persistActiveSession();
  renderActiveWorkout();
  unlockAudio();
  if (getWorkoutSettings().autoRest) startRestTimer();
  else { stopRestTimer(); restRemaining = restDuration(); updateRestTimer(); $('restPanel').hidden = false; }
}

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
    logged ? `${loggedSetsStay(logged, exercise.name)}, and the new exercise gets ${planned ? `the ${plural(planned - logged, 'set')} left` : 'the sets from here on'}.`
      : `The new exercise keeps ${planned ? `the ${plural(planned, 'planned set')} and their reps` : `the target of ${exercise.reps} ${isTimed(exercise) ? 'seconds' : 'reps'}`}, with weights of your own.`,
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
    : { name, weight:'', reps:exercise.reps, sets:[], swappedFrom:original, ...(isTimed(exercise) ? { timed:true } : {}), ...(exercise.rest ? { rest:exercise.rest } : {}),
      ...(plan ? { plan:plan.slice(logged).map(set => ({ weight:'', reps:set.reps, ...(set.repsMax ? { repsMax:set.repsMax } : {}), ...(set.warmup ? { warmup:true } : {}) })) } : {}) };
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

$('completeSetBtn').onclick = logSet;
$('holdBtn').onclick = () => { if (holdInterval) stopHold(true); else startHold(); };
$('completedReps').oninput = () => { markInvalid($('completedReps'), false); syncHoldDisplay(); };
$('activeWorkoutProgress').onclick = () => showExerciseJump($('exerciseJump').hidden);
$('exerciseJump').onclick = e => {
  const button = e.target.closest('[data-jump]');
  if (!button || !activeSession) return;
  const index = Number(button.dataset.jump);
  showExerciseJump(false);
  if (index !== activeSession.currentIndex && activeSession.exercises[index]) goToExercise(index);
};
$('swapToggle').onclick = () => showSwap($('swapPanel').hidden);
$('swapCancel').onclick = () => showSwap(false);
$('swapBtn').onclick = swapExercise;
$('swapName').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); swapExercise(); } };
$('swapName').oninput = () => markInvalid($('swapName'), false);
$('summaryDone').onclick = () => { $('workoutSummary').hidden = true; };
// −5 and +5 beside the weight: a change of 2.5 lbs a side, the smallest most plate sets make. In kilograms, −2.5 and
// +2.5: 1.25 kg a side.
function applyWeightStepper() {
  const step = weightUnit() === 'kg' ? 2.5 : 5;
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
$('restToggleBtn').onclick = () => {
  unlockAudio();
  if (restInterval) { syncRestRemaining(); updateRestTimer(); stopRestTimer(); }
  else {
    if (restRemaining <= 0) restRemaining = restDuration();
    updateRestTimer();
    runRestTimer();
  }
};
$('restResetBtn').onclick = () => { stopRestTimer(); restRemaining = restDuration(); updateRestTimer(); };
$('restAdjust').onclick = e => {
  const button = e.target.closest('[data-rest-adjust]');
  if (!button) return;
  unlockAudio();
  adjustRest(Number(button.dataset.restAdjust));
};
$('nextExerciseBtn').onclick = () => {
  if (activeSession.currentIndex === activeSession.exercises.length - 1) finishWorkout();
  else goToExercise(activeSession.currentIndex + 1);
};
$('prevExerciseBtn').onclick = () => { if (activeSession.currentIndex > 0) goToExercise(activeSession.currentIndex - 1); };
$('endWorkoutBtn').onclick = () => { if (!getWorkoutSettings().confirmEnd || confirm('End this workout without saving it?')) closeActiveWorkout(); };
// Logged sets can be corrected in place; a value that is not valid snaps back to what was logged.
$('completedSets').onchange = e => {
  const index = Number(e.target.dataset.set);
  const field = e.target.dataset.field;
  if (!activeSession || !field || Number.isNaN(index)) return;
  const set = activeSession.exercises[activeSession.currentIndex].sets[index];
  if (!set) return;
  const value = e.target.value;
  if (field === 'reps' && (!value || Number(value) < 1)) { showFeedback(isTimed(activeSession.exercises[activeSession.currentIndex]) ? 'Seconds must be at least 1.' : 'Reps must be at least 1.'); e.target.value = set.reps; return; }
  if (field === 'weight' && value !== '' && Number(value) < 0) { showFeedback('Weight cannot be negative.'); e.target.value = set.weight || ''; return; }
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
  if (!reps || Number(reps) < 1) { showFeedback(timed ? 'Enter at least 1 target second for this exercise.' : 'Enter at least 1 target rep for this exercise.'); $('activeAddReps').focus(); return; }
  activeSession.exercises.splice(activeSession.currentIndex + 1, 0, { name, weight:'', reps:String(Math.floor(Number(reps))), ...(timed ? { timed:true } : {}), sets:[] });
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
// An open ⋯ menu closes when anything else is tapped (including another row's menu) or on Escape.
document.addEventListener('click', e => {
  document.querySelectorAll('.row-menu[open]').forEach(menu => { if (!menu.contains(e.target)) menu.open = false; });
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.row-menu[open]').forEach(menu => { menu.open = false; });
});
$('recentList').onclick = e => {
  const button = e.target.closest('[data-recent-id]');
  const workout = button && savedWorkouts.find(item => item.id === Number(button.dataset.recentId));
  if (workout) startWorkout(workout);
};
$('templatesToggle').onclick = () => {
  templatesChoice = $('templateArea').hidden;
  syncTemplateArea();
};
$('saveBtn').onclick = async () => {
  if (!exercises.length) { showFeedback('Add at least one exercise before saving the workout.'); return; }
  if (!$('workoutDate').value) { showFeedback('Choose a workout date before saving.'); $('workoutDate').focus(); return; }
  let replacedSets = 0;
  const savedExercises = exercises.map(item => {
    const baseline = setBaselines.get(item);
    if (!baseline || (String(item.weight ?? '') === baseline.weight && String(item.reps ?? '') === baseline.reps)) return { ...item };
    const { sets, ...plan } = item;
    replacedSets += 1;
    return plan;
  });
  const workout = { ...editingWorkout, name:$('workoutName').value.trim() || 'Untitled workout', notes:$('workoutNotes').value.trim(), exercises:savedExercises, createdAt:timestampFromDateInput($('workoutDate').value), unit:weightUnit() };
  try {
    await persistWorkout(workout);
    await loadSavedWorkouts();
    showFeedback(`“${workout.name}” saved successfully.${replacedSets ? ' Set-by-set details were replaced for exercises whose weight or reps you changed.' : ''}`, 'success');
    $('clearBtn').click();
  } catch (error) {
    showFeedback('This workout could not be saved. Check your connection and try again.');
    console.error('Unable to save workout.', error);
  }
};

renderTemplates();
window.serverStateReady.then(() => {
  customTemplates = loadCustomTemplates();
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
document.addEventListener('visibilitychange', () => { if (!document.hidden && restInterval) tickRest(); if (!document.hidden && holdInterval) tickHold(); syncWakeLock(); });
window.localReady.then(() => {
  lastPerformance = readLocal(localKey('lastperf')) || {};
  personalBests = readLocal(localKey('bests')) || {};
  syncTemplateArea();
  renderExerciseSuggestions();
}).then(flushPendingWorkouts).then(loadSavedWorkouts).then(resumeOrStartWorkout).finally(() => { initialLoadDone = true; syncTemplateArea(); });