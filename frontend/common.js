// Helpers shared by the Tracker, History and Progress pages. Loaded first, before any page script.
const $ = id => document.getElementById(id);

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

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });
