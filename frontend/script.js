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
let audioContext = null;
let wakeLock = null;
let wakeLockRequesting = false;
let workoutsReachable = true;
let initialLoadDone = false;
let restRemaining = getWorkoutSettings().restDuration;
const customTemplateStorageKey = 'workout-tracker-custom-templates';
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

function showFeedback(message, type = 'error') {
  const feedback = $('formFeedback');
  feedback.textContent = message;
  feedback.className = `form-feedback ${type}`;
  feedback.hidden = false;
}

function clearFeedback() {
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

function loadCustomTemplates() {
  try { return JSON.parse(localStorage.getItem(customTemplateStorageKey) || '[]'); }
  catch (error) { return []; }
}

function saveCustomTemplates() {
  localStorage.setItem(customTemplateStorageKey, JSON.stringify(customTemplates));
  fetch('/api/state', { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ templates:customTemplates }) }).catch(() => {});
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
  list.innerHTML = workouts.length ? workouts.map(workout => `<li class="saved-workout" data-id="${workout.id}"><div class="saved-workout-summary"><div><strong>${escapeHTML(workout.name)}</strong><span>${new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })}</span></div><div class="workout-actions"><button class="primary" type="button" data-action="start">Start</button><button class="secondary" type="button" data-action="view" aria-expanded="false">View</button><button class="secondary" type="button" data-action="repeat">Repeat</button><button class="secondary" type="button" data-action="edit">Edit</button><button class="danger" type="button" data-action="delete">Delete</button></div></div><div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${workout.exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${item.weight || 0} lbs &middot; ${item.reps} reps</span></li>`).join('')}</ul></div></li>`).join('') : '<li class="empty">No saved workouts yet.</li>';
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
    notifyRestDone();
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

// Browsers only allow sound after a tap, so the audio context is created from the buttons that start the rest timer.
function unlockAudio() {
  try {
    audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === 'suspended') audioContext.resume();
  } catch (error) {
    audioContext = null;
  }
}

function notifyRestDone() {
  if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  if (!audioContext) return;
  try {
    [0, 0.25].forEach(offset => {
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      const start = audioContext.currentTime + offset;
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.12, start);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.18);
      oscillator.connect(gain);
      gain.connect(audioContext.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.2);
    });
  } catch (error) {
    console.error('Unable to play the rest timer sound.', error);
  }
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

function renderActiveWorkout() {
  const exercise = activeSession.exercises[activeSession.currentIndex];
  $('activeWorkoutTitle').textContent = activeSession.name;
  $('activeWorkoutProgress').textContent = `Exercise ${activeSession.currentIndex + 1} of ${activeSession.exercises.length}`;
  $('activeExerciseName').textContent = exercise.name;
  $('activeExerciseTarget').textContent = `Target: ${exercise.reps} reps${exercise.weight ? ` at ${exercise.weight} lbs` : ''}`;
  $('activeNotes').value = activeSession.notes || '';
  $('activeWeight').value = exercise.weight || '';
  $('completedReps').value = '';
  $('completedSets').innerHTML = (exercise.sets || []).map((set, index) => `<li>Set ${index + 1}: ${set.reps} reps${set.weight ? ` at ${set.weight} lbs` : ''}</li>`).join('');
  $('nextExerciseBtn').textContent = activeSession.currentIndex === activeSession.exercises.length - 1 ? 'Finish workout' : 'Next exercise';
  $('activeSyncNotice').hidden = !activeSyncFailed;
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
  activeSession.clientId = activeSession.clientId || newClientId();
  const workout = { name:activeSession.name, notes:activeSession.notes || '', exercises:activeSession.exercises.map(item => ({ name:item.name, weight:item.weight, reps:item.sets.length ? item.sets[item.sets.length - 1].reps : item.reps, sets:item.sets })), createdAt:Date.now(), clientId:activeSession.clientId };
  queuePendingWorkout(workout);
  activeSession = null;
  persistActiveSession();
  stopRestTimer();
  $('restPanel').hidden = true;
  $('activeWorkout').hidden = true;
  syncWakeLock();
  const synced = await flushPendingWorkouts();
  showFeedback(synced ? `“${workout.name}” saved successfully.` : `“${workout.name}” is saved on this device and will sync when the server is reachable again.`, 'success');
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
  exercise.weight = Math.max(Number(exercise.weight) || 0, weight);
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
  else { activeSession.currentIndex += 1; stopRestTimer(); restRemaining = getWorkoutSettings().restDuration; updateRestTimer(); $('restPanel').hidden = true; renderActiveWorkout(); persistActiveSession(); }
};
$('endWorkoutBtn').onclick = () => { if (!getWorkoutSettings().confirmEnd || confirm('End this workout without saving it?')) { activeSession = null; persistActiveSession(); stopRestTimer(); $('activeWorkout').hidden = true; syncWakeLock(); } };
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
    showFeedback('This workout could not be saved on this device.');
    console.error('Unable to save workout.', error);
  }
};

renderTemplates();
window.serverStateReady?.then(state => {
  if (!state || !Array.isArray(state.templates)) return;
  customTemplates = state.templates;
  localStorage.setItem(customTemplateStorageKey, JSON.stringify(customTemplates));
  renderTemplates();
});
window.addEventListener('syncchange', event => {
  renderStorageStatus();
  $('activeSyncNotice').hidden = !(event.detail.activeOffline && activeSession);
  if (event.detail.uploaded && initialLoadDone) loadSavedWorkouts();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && restInterval) tickRest(); syncWakeLock(); });
window.localReady.then(flushPendingWorkouts).then(loadSavedWorkouts).then(resumeOrStartWorkout).finally(() => { initialLoadDone = true; });