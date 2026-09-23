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

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });
