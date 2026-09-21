const $ = id => document.getElementById(id);
const databaseName = 'workout-tracker';
const databaseVersion = 2;
const workoutStore = 'workouts';
const activeWorkoutStore = 'activeWorkout';

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });

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

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
}

function exerciseDetails(exercise) {
  if (!exercise.sets || !exercise.sets.length) return `${exercise.weight || 0} lbs &middot; ${exercise.reps} reps`;
  return exercise.sets.map(set => `${set.weight || 0} lbs x ${set.reps}`).join(' &middot; ');
}

function renderHistory(workouts) {
  $('historySummary').textContent = `${workouts.length} saved workout${workouts.length === 1 ? '' : 's'}`;
  $('historyList').innerHTML = workouts.length ? workouts.map(workout => `<li class="saved-workout history-workout"><div class="saved-workout-summary"><div><strong>${escapeHTML(workout.name)}</strong><span>${new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })}</span></div><a class="button-link primary" href="index.html?start=${workout.id}">Start workout</a></div><div class="workout-details">${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${workout.exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${exerciseDetails(item)}</span></li>`).join('')}</ul></div></li>`).join('') : '<li class="empty">No saved workouts yet.</li>';
}

window.localReady.then(flushPendingWorkouts).then(getSavedWorkouts).then(renderHistory).catch(error => {
  $('historySummary').textContent = 'Local storage unavailable';
  console.error('Unable to load workout history.', error);
});