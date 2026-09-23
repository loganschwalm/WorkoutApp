const $ = id => document.getElementById(id);
const exercises = [];
const databaseName = 'workout-tracker';
const databaseVersion = 2;
const workoutStore = 'workouts';
const activeWorkoutStore = 'activeWorkout';
let editingWorkout = null;
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
let restRemaining = getWorkoutSettings().restDuration;
let customTemplates = loadCustomTemplates();
let editingTemplateId = null;
let templateDraftExercises = [];
const templates = [
  { name:'Push Day', exercises:[{ name:'Bench Press', weight:'', reps:'8' }, { name:'Overhead Press', weight:'', reps:'8' }, { name:'Tricep Pushdown', weight:'', reps:'12' }] },
  { name:'Pull Day', exercises:[{ name:'Deadlift', weight:'', reps:'5' }, { name:'Barbell Row', weight:'', reps:'8' }, { name:'Lat Pulldown', weight:'', reps:'10' }, { name:'Bicep Curl', weight:'', reps:'12' }] },
  { name:'Leg Day', exercises:[{ name:'Back Squat', weight:'', reps:'8' }, { name:'Romanian Deadlift', weight:'', reps:'10' }, { name:'Leg Press', weight:'', reps:'10' }, { name:'Calf Raise', weight:'', reps:'15' }] },
  { name:'Upper Body', exercises:[{ name:'Bench Press', weight:'', reps:'8' }, { name:'Pull-up', weight:'', reps:'8' }, { name:'Dumbbell Row', weight:'', reps:'10' }, { name:'Lateral Raise', weight:'', reps:'12' }] },
  { name:'Full Body', exercises:[{ name:'Goblet Squat', weight:'', reps:'10' }, { name:'Push-up', weight:'', reps:'10' }, { name:'Dumbbell Row', weight:'', reps:'10' }, { name:'Plank', weight:'', reps:'30' }] }
];
$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });

function dateInputValue(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function timestampFromDateInput(value) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, 12).getTime();
}

$('workoutDate').value = dateInputValue(Date.now());

function showWorkoutBuilder() {
  $('newWorkoutIntro').hidden = true;
  $('workoutBuilder').hidden = false;
}

// The banner sticks to the top of the screen so a message is seen wherever the page is scrolled; successes dismiss themselves.
function showFeedback(message, type = 'error') {
  const feedback = $('formFeedback');
  feedback.textContent = message;
  feedback.className = `form-feedback ${type}`;
  feedback.hidden = false;
  clearTimeout(feedbackTimer);
  if (type === 'success') feedbackTimer = setTimeout(clearFeedback, 6000);
}

function clearFeedback() {
  clearTimeout(feedbackTimer);
  $('formFeedback').hidden = true;
  $('formFeedback').textContent = '';
}

function markInvalid(element, invalid) {
  element.setAttribute('aria-invalid', String(invalid));
}

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, databaseVersion);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(workoutStore)) database.createObjectStore(workoutStore, { keyPath:'id', autoIncrement:true });
      if (!database.objectStoreNames.contains(activeWorkoutStore)) database.createObjectStore(activeWorkoutStore, { keyPath:'id' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function getSavedWorkouts() {
  return fetch('/api/workouts').then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load workouts.'))).then(result => result.workouts);
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

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
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
  list.innerHTML = exercises.length ? exercises.map((item, i) => `<li class="exercise"><input class="exercise-edit" type="text" value="${escapeHTML(item.name)}" data-index="${i}" data-field="name" aria-label="Exercise name"><input class="exercise-edit" type="number" min="0" step="0.5" value="${escapeHTML(item.weight || '')}" data-index="${i}" data-field="weight" aria-label="Exercise weight"><input class="exercise-edit" type="number" min="1" step="1" value="${escapeHTML(item.reps)}" data-index="${i}" data-field="reps" aria-label="Exercise reps"><button class="remove" type="button" data-index="${i}">Remove</button></li>`).join('') : '<li class="empty">Your exercises will appear here.</li>';
  $('count').textContent = `${exercises.length} exercise${exercises.length === 1 ? '' : 's'}`;
}

function renderSavedWorkouts(workouts) {
  const list = $('savedWorkoutList');
  list.innerHTML = workouts.length ? workouts.map(workout => `<li class="saved-workout" data-id="${workout.id}"><div class="saved-workout-summary"><div><strong>${escapeHTML(workout.name)}</strong><span>${new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })}</span></div><div class="workout-actions"><button class="primary" type="button" data-action="start">Start</button><button class="secondary" type="button" data-action="view" aria-expanded="false">View</button><button class="secondary" type="button" data-action="repeat">Repeat</button><button class="secondary" type="button" data-action="edit">Edit</button><button class="danger" type="button" data-action="delete">Delete</button></div></div><div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${workout.exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${item.sets && !item.sets.length ? 'Skipped' : `${item.weight || 0} lbs &middot; ${item.reps} reps`}</span></li>`).join('')}</ul></div></li>`).join('') : '<li class="empty">No saved workouts yet.</li>';
}

function renderTemplates() {
  $('templateList').innerHTML = getAllTemplates().map(template => `<article class="template-card"><div><h3>${escapeHTML(template.name)}</h3><p>${template.exercises.map(item => `${escapeHTML(item.name)} (${escapeHTML(item.reps)} reps)`).join(' &middot; ')}</p></div><div class="template-actions"><button class="primary" type="button" data-template-action="start" data-template-id="${escapeHTML(template.id)}">Start workout</button><button class="secondary" type="button" data-template-action="duplicate" data-template-id="${escapeHTML(template.id)}">Duplicate</button>${template.builtIn ? '' : `<button class="secondary" type="button" data-template-action="edit" data-template-id="${escapeHTML(template.id)}">Edit</button><button class="danger" type="button" data-template-action="delete" data-template-id="${escapeHTML(template.id)}">Delete</button>`}</div></article>`).join('');
}

function renderTemplateExerciseEditor() {
  $('templateExerciseEditor').innerHTML = templateDraftExercises.map((exercise, index) => `<div class="template-exercise-row"><div><label for="templateExercise${index}">Exercise</label><input id="templateExercise${index}" type="text" value="${escapeHTML(exercise.name)}" data-template-field="name" data-index="${index}" required /></div><div><label for="templateReps${index}">Reps</label><input id="templateReps${index}" type="number" min="1" value="${escapeHTML(exercise.reps)}" data-template-field="reps" data-index="${index}" required /></div><div class="template-row-actions"><button class="secondary" type="button" data-template-row-action="up" data-index="${index}" aria-label="Move exercise up">&#8593;</button><button class="secondary" type="button" data-template-row-action="down" data-index="${index}" aria-label="Move exercise down">&#8595;</button><button class="danger" type="button" data-template-row-action="remove" data-index="${index}" aria-label="Remove exercise">&times;</button></div></div>`).join('');
}

function openTemplateEditor(template = null) {
  editingTemplateId = template?.id || null;
  $('templateModalTitle').textContent = template ? 'Edit template' : 'Create template';
  $('templateName').value = template?.name || '';
  templateDraftExercises = template ? template.exercises.map(item => ({ name:item.name, reps:item.reps })) : [{ name:'', reps:'8' }];
  renderTemplateExerciseEditor();
  $('templateModal').hidden = false;
  $('templateName').focus();
}

function closeTemplateEditor() {
  $('templateModal').hidden = true;
  editingTemplateId = null;
}

function loadWorkoutIntoForm(workout, editMode) {
  showWorkoutBuilder();
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
  window.scrollTo({ top:0, behavior:'smooth' });
}

function updateRestTimer() {
  const minutes = Math.floor(restRemaining / 60);
  const seconds = String(restRemaining % 60).padStart(2, '0');
  $('timerDisplay').textContent = `${minutes}:${seconds}`;
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

function startRestTimer() {
  restRemaining = getWorkoutSettings().restDuration;
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

function exerciseKey(name) {
  return String(name).trim().toLowerCase();
}

function formatSet(set) {
  return set.weight ? `${set.weight} lbs × ${set.reps}` : `${set.reps} reps`;
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
    if (item.sets && item.sets.length) latest[key] = { date:workout.createdAt, sets:normalizeSets(item.sets) };
    else if (!item.sets) latest[key] = { date:workout.createdAt, sets:normalizeSets([{ weight:item.weight, reps:item.reps }]) };
  }));
  return latest;
}

function saveLastPerformance() {
  writeLocal(localKey('lastperf'), lastPerformance);
}

// Updated as soon as a workout is finished, so the next session shows it even if the upload is still waiting.
function rememberLastPerformance(workout) {
  workout.exercises.forEach(item => { lastPerformance[exerciseKey(item.name)] = { date:workout.createdAt, sets:normalizeSets(item.sets) }; });
  saveLastPerformance();
}

function renderActiveProgress() {
  $('activeWorkoutProgress').textContent = `Exercise ${activeSession.currentIndex + 1} of ${activeSession.exercises.length}`;
  $('prevExerciseBtn').hidden = activeSession.currentIndex === 0;
  $('nextExerciseBtn').textContent = activeSession.currentIndex === activeSession.exercises.length - 1 ? 'Finish workout' : 'Next exercise';
}

function renderActiveWorkout() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  exercise.sets = exercise.sets || [];
  const previous = lastPerformance[exerciseKey(exercise.name)];
  const previousFirst = previous ? previous.sets[0] : null;
  const lastSet = exercise.sets[exercise.sets.length - 1];
  $('activeWorkoutTitle').textContent = activeSession.name;
  renderActiveProgress();
  $('activeExerciseName').textContent = exercise.name;
  $('activeExerciseTarget').textContent = `Target: ${exercise.reps} reps${exercise.weight ? ` at ${exercise.weight} lbs` : ''}`;
  $('activeExerciseLast').hidden = !previous;
  if (previous) $('activeExerciseLast').textContent = `Last time (${new Date(previous.date).toLocaleDateString(undefined, { month:'short', day:'numeric' })}): ${previous.sets.map(formatSet).join(' · ')}`;
  $('activeNotes').value = activeSession.notes || '';
  // Next set defaults to the set just logged, or to last time's first set, so repeating a set is one tap.
  $('activeWeight').value = lastSet ? lastSet.weight || '' : exercise.weight || (previousFirst && previousFirst.weight) || '';
  $('completedReps').value = (lastSet || previousFirst || {}).reps || '';
  $('completedSets').innerHTML = exercise.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}</span><div class="set-field"><input class="set-edit" type="number" min="0" step="0.5" value="${escapeHTML(set.weight || '')}" data-set="${index}" data-field="weight" aria-label="Set ${index + 1} weight in lbs"><span>lbs</span></div><div class="set-field"><input class="set-edit" type="number" min="1" step="1" value="${escapeHTML(set.reps)}" data-set="${index}" data-field="reps" aria-label="Set ${index + 1} reps"><span>reps</span></div><button class="remove" type="button" data-remove-set="${index}" aria-label="Remove set ${index + 1}">Remove</button></li>`).join('');
  $('activeSyncNotice').hidden = !activeSyncFailed;
}

function goToExercise(index) {
  activeSession.currentIndex = index;
  stopRestTimer();
  restRemaining = getWorkoutSettings().restDuration;
  updateRestTimer();
  $('restPanel').hidden = true;
  renderActiveWorkout();
  persistActiveSession();
}

function closeActiveWorkout() {
  activeSession = null;
  persistActiveSession();
  stopRestTimer();
  $('restPanel').hidden = true;
  $('activeWorkout').hidden = true;
  syncWakeLock();
}

function startWorkout(template) {
  if (activeSession && getWorkoutSettings().confirmEnd && !confirm(`Replace your in-progress “${activeSession.name}” workout? Sets you have logged so far will be lost.`)) return;
  stopRestTimer();
  restRemaining = getWorkoutSettings().restDuration;
  $('restPanel').hidden = true;
  activeSession = { name:template.name, notes:template.notes || '', exercises:template.exercises.map(item => ({ ...item, sets:[] })), currentIndex:0, clientId:newClientId() };
  persistActiveSession();
  renderActiveWorkout();
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
  const workout = { name:activeSession.name, notes:activeSession.notes || '', exercises:performed.map(item => ({ name:item.name, weight:Math.max(...item.sets.map(set => Number(set.weight) || 0)), reps:item.sets[item.sets.length - 1].reps, sets:item.sets })), createdAt:Date.now(), clientId:activeSession.clientId };
  rememberLastPerformance(workout);
  queuePendingWorkout(workout);
  closeActiveWorkout();
  const synced = await flushPendingWorkouts();
  const note = skipped ? ` ${skipped} exercise${skipped === 1 ? '' : 's'} with no sets ${skipped === 1 ? 'was' : 'were'} left out.` : '';
  showFeedback(synced ? `“${workout.name}” saved successfully.${note}` : `“${workout.name}” is saved on this device and will sync when the server is reachable again.${note}`, 'success');
}

function renderStorageStatus() {
  const waiting = readPendingWorkouts().length;
  const parts = [workoutsReachable ? 'Saved to your account' : 'Server unreachable'];
  if (waiting) parts.push(`${waiting} workout${waiting === 1 ? '' : 's'} waiting to sync`);
  $('storageStatus').textContent = parts.join(' · ');
}

async function loadSavedWorkouts() {
  try {
    const workouts = await getSavedWorkouts();
    renderSavedWorkouts(workouts);
    lastPerformance = buildLastPerformance([...workouts, ...readPendingWorkouts()]);
    saveLastPerformance();
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
    activeSession = savedSession;
    stopRestTimer();
    restRemaining = getWorkoutSettings().restDuration;
    updateRestTimer();
    $('restPanel').hidden = true;
    renderActiveWorkout();
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
$('createWorkoutBtn').onclick = () => { showWorkoutBuilder(); $('workoutName').focus(); };
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
$('clearBtn').onclick = () => { editingWorkout = null; exercises.length = 0; $('workoutName').value = ''; $('workoutDate').value = dateInputValue(Date.now()); $('workoutNotes').value = ''; $('saveBtn').textContent = 'Save workout'; render(); };
$('templateList').onclick = e => {
  const action = e.target.dataset.templateAction;
  const templateId = e.target.dataset.templateId;
  if (!action || !templateId) return;
  const template = getAllTemplates().find(item => item.id === templateId);
  if (!template) return;
  if (action === 'start') startWorkout(template);
  if (action === 'edit') openTemplateEditor(template);
  if (action === 'duplicate') {
    customTemplates.push({ id:`custom-${Date.now()}`, name:`${template.name} Copy`, exercises:template.exercises.map(item => ({ name:item.name, reps:item.reps })) });
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
  if (field && templateDraftExercises[index]) templateDraftExercises[index][field] = e.target.value;
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
  const validExercises = templateDraftExercises.filter(item => item.name.trim() && Number(item.reps) >= 1).map(item => ({ name:item.name.trim(), reps:String(Math.floor(Number(item.reps))) }));
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
$('completeSetBtn').onclick = () => {
  const reps = Number($('completedReps').value);
  const weightValue = $('activeWeight').value;
  markInvalid($('completedReps'), !reps || reps < 1);
  markInvalid($('activeWeight'), weightValue !== '' && Number(weightValue) < 0);
  if (!reps || reps < 1) { showFeedback('Enter the reps completed for this set.'); $('completedReps').focus(); return; }
  if (weightValue !== '' && Number(weightValue) < 0) { showFeedback('Weight cannot be negative.'); $('activeWeight').focus(); return; }
  clearFeedback();
  const weight = Number(weightValue) || 0;
  const exercise = activeSession.exercises[activeSession.currentIndex];
  exercise.sets.push({ reps, weight });
  persistActiveSession();
  renderActiveWorkout();
  unlockAudio();
  if (getWorkoutSettings().autoRest) startRestTimer();
  else { stopRestTimer(); restRemaining = getWorkoutSettings().restDuration; updateRestTimer(); $('restPanel').hidden = false; }
};
$('restToggleBtn').onclick = () => {
  unlockAudio();
  if (restInterval) { syncRestRemaining(); updateRestTimer(); stopRestTimer(); }
  else {
    if (restRemaining <= 0) restRemaining = getWorkoutSettings().restDuration;
    updateRestTimer();
    runRestTimer();
  }
};
$('restResetBtn').onclick = () => { stopRestTimer(); restRemaining = getWorkoutSettings().restDuration; updateRestTimer(); };
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
  if (field === 'reps' && (!value || Number(value) < 1)) { showFeedback('Reps must be at least 1.'); e.target.value = set.reps; return; }
  if (field === 'weight' && value !== '' && Number(value) < 0) { showFeedback('Weight cannot be negative.'); e.target.value = set.weight || ''; return; }
  set[field] = Number(value) || 0;
  clearFeedback();
  persistActiveSession();
};
$('completedSets').onclick = e => {
  const button = e.target.closest('[data-remove-set]');
  if (!button || !activeSession) return;
  activeSession.exercises[activeSession.currentIndex].sets.splice(Number(button.dataset.removeSet), 1);
  persistActiveSession();
  renderActiveWorkout();
};
$('activeAddName').oninput = () => markInvalid($('activeAddName'), false);
$('activeAddReps').oninput = () => markInvalid($('activeAddReps'), false);
// The new exercise goes right after the current one so Next reaches it; the current exercise is not re-rendered, keeping anything typed.
$('activeAddBtn').onclick = () => {
  const name = $('activeAddName').value.trim(), reps = $('activeAddReps').value;
  markInvalid($('activeAddName'), !name);
  markInvalid($('activeAddReps'), !reps || Number(reps) < 1);
  if (!name) { showFeedback('Enter an exercise name before adding it.'); $('activeAddName').focus(); return; }
  if (!reps || Number(reps) < 1) { showFeedback('Enter at least 1 target rep for this exercise.'); $('activeAddReps').focus(); return; }
  activeSession.exercises.splice(activeSession.currentIndex + 1, 0, { name, weight:'', reps:String(Math.floor(Number(reps))), sets:[] });
  persistActiveSession();
  renderActiveProgress();
  $('activeAddName').value = '';
  $('activeAddReps').value = '';
  $('addActiveExercise').open = false;
  showFeedback(`Added “${name}” as your next exercise.`, 'success');
};
$('savedWorkoutList').onclick = async e => {
  const action = e.target.dataset.action;
  if (!action) return;
  const workoutElement = e.target.closest('.saved-workout');
  const workoutId = Number(workoutElement.dataset.id);
  const workouts = await getSavedWorkouts();
  const workout = workouts.find(item => item.id === workoutId);
  if (!workout) return;

  if (action === 'start') startWorkout(workout);
  if (action === 'view') {
    const details = workoutElement.querySelector('.workout-details');
    const isHidden = details.hasAttribute('hidden');
    details.toggleAttribute('hidden', !isHidden);
    e.target.textContent = isHidden ? 'Hide' : 'View';
    e.target.setAttribute('aria-expanded', String(isHidden));
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
  const workout = { ...editingWorkout, name:$('workoutName').value.trim() || 'Untitled workout', notes:$('workoutNotes').value.trim(), exercises:savedExercises, createdAt:timestampFromDateInput($('workoutDate').value) };
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
  renderTemplates();
});
window.addEventListener('syncchange', event => {
  renderStorageStatus();
  $('activeSyncNotice').hidden = !(event.detail.activeOffline && activeSession);
  if (event.detail.uploaded && initialLoadDone) loadSavedWorkouts();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && restInterval) tickRest(); syncWakeLock(); });
window.localReady.then(() => { lastPerformance = readLocal(localKey('lastperf')) || {}; }).then(flushPendingWorkouts).then(loadSavedWorkouts).then(resumeOrStartWorkout).finally(() => { initialLoadDone = true; });