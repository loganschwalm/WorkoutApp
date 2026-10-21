// The saved workouts on the Tracker: the list of the latest few and which is due, the line that says what is waiting or refused,
// loading the list (and the copy kept for offline), and what a tap on a row does. Loaded before script.js, which starts the page and
// declares the state these use (savedWorkouts, savedWorkoutsLoaded, workoutsReachable); nothing here reads it until it runs.

// Changes to a saved workout go straight to the server. A new one goes into the upload queue instead (see the form's Save).
function updateSavedWorkout(workout) {
  return syncFetch(`/api/workouts/${encodeURIComponent(workout.id)}`, { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(workout) })
    .then(response => response.ok ? response.json() : Promise.reject(new Error(`Unable to save workout (${response.status}).`)));
}

function deleteWorkout(id) {
  return syncFetch(`/api/workouts/${id}`, { method:'DELETE' })
    .then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to delete workout.')));
}

// The Tracker lists the most recent workouts, the first three showing and the rest of them a tap away (Show more), since
// this list is where a workout is edited or deleted. The History page has every one.
const recentWorkoutLimit = 10;
const savedWorkoutsShown = 3;
let showingAllSaved = false;

// The workout that is due, to lead the list: of the recent ones (up to three different ones), the one done longest ago, since
// someone going round a rotation (push, pull, legs) is most likely due for it next. There has to be a rotation to be due in, two
// different workouts or more, and while a program is being followed its panel says what is next, so its workouts are left out.
function dueWorkout(workouts) {
  const picked = new Map();
  for (const workout of workouts.slice(0, recentWorkoutLimit)) {
    if (picked.size === 3) break;
    if (currentProgram && workout.program) continue;
    if (!picked.has(exerciseKey(workout.name))) picked.set(exerciseKey(workout.name), workout);
  }
  return picked.size > 1 ? [...picked.values()].sort((a, b) => a.createdAt - b.createdAt)[0] : null;
}

function renderSavedWorkouts(workouts) {
  const list = $('savedWorkoutList');
  const recent = workouts.slice(0, recentWorkoutLimit);
  // The due one leads, marked, and is not listed again where it was done, so the list is as long as it was.
  const due = dueWorkout(workouts);
  const ordered = due ? [due, ...recent.filter(workout => workout !== due)] : recent;
  const folded = showingAllSaved ? 0 : Math.max(0, recent.length - savedWorkoutsShown);
  const moreButton = folded ? `<button class="secondary" type="button" data-action="more">Show ${folded} more</button>` : '';
  const historyLink = workouts.length > savedWorkoutsShown
    ? `<a class="button-link secondary" href="history.html">See all ${workouts.length} workouts in History</a>` : '';
  const more = moreButton || historyLink ? `<li class="more-workouts">${moreButton}${historyLink}</li>` : '';
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  const focusedId = focused?.closest('.saved-workout')?.dataset.id;
  const focusedAction = focused?.dataset.action;
  // One row a workout: tapping its name shows what was done, Start is the one button, and everything else (copying,
  // editing, deleting) waits in its ⋯ menu, away from a thumb reaching for Start.
  list.innerHTML = ordered.length ? ordered.map((workout, index) => `<li class="saved-workout${workout === due ? ' is-due' : ''}" data-id="${escapeHTML(workout.id)}"`
    + `${index >= ordered.length - folded ? ' hidden' : ''}>`
    + '<div class="saved-workout-summary saved-workout-row">'
    + '<button class="saved-workout-toggle" type="button" data-action="view" aria-expanded="false">'
    + `<strong>${escapeHTML(workout.name)}</strong><span>${workout === due ? '<em class="due-tag">Due next</em> ' : ''}`
    + `${escapeHTML(describeWorkoutDate(workout))}</span></button>`
    + '<div class="row-actions"><button class="primary" type="button" data-action="start">Start</button>'
    + `<details class="row-menu"><summary class="secondary" aria-label="More for ${escapeHTML(workout.name)}">&middot;&middot;&middot;</summary>`
    + '<div class="row-menu-items"><button type="button" data-action="repeat">Copy as new</button><button type="button" data-action="edit">Edit</button>'
    + '<button class="danger" type="button" data-action="delete">Delete</button></div></details></div></div>'
    + `<div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}`
    + `<ul>${inUnit(workout).exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong>`
      + `<span>${escapeHTML(describeSavedExercise(item))}</span></li>`).join('')}</ul>`
    + '</div></li>').join('') + more
    : '<li class="empty">No saved workouts yet.</li>';
  // Drawn again (after a sync, say) while a button in the list has the focus, the same button gets it back.
  if (focusedId) list.querySelector(`.saved-workout[data-id="${focusedId}"] [data-action="${focusedAction}"]`)?.focus({ preventScroll:true });
  renderTrackerStatus(workouts);
}

// "Today", "yesterday", "3 days ago", and the date from two weeks on: by calendar day, so a workout late last night is
// yesterday even when it was only hours ago. Here and not in common.js, so a page cached from before this change cannot be
// left calling something the cached common.js lacks.
function describeDaysAgo(when, now = new Date()) {
  const startOfDayOf = value => { const date = new Date(value); return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime(); };
  const days = Math.round((startOfDayOf(now) - startOfDayOf(when)) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  return days < 14 ? `${days} days ago` : new Date(when).toLocaleDateString(undefined, { month:'short', day:'numeric' });
}

// The line under the page's name: when you last trained. What is next is the panel just below it, so the header does not say it again.
function renderTrackerStatus(workouts) {
  const last = workouts[0];
  $('pageStatus').textContent = last ? `Last workout: ${last.name}, ${describeDaysAgo(last.createdAt)}.` : 'Nothing logged yet. Start one from a template below.';
}

// What the status line calls each part of the account's state.
const STATE_PART_NAMES = { settings:'settings', templates:'templates', program:'program', exerciseNotes:'exercise notes', goals:'goals', bodyweight:'weigh-ins', exerciseLibrary:'exercise library' };

function renderStorageStatus() {
  const waiting = readPendingWorkouts().length;
  // Nothing to say while everything is saved to the account; the line only speaks up when something is not.
  const parts = workoutsReachable ? [] : ['Server unreachable'];
  if (waiting) parts.push(`${waiting} workout${waiting === 1 ? '' : 's'} waiting to sync`);
  const refused = readRejectedWorkouts().length;
  if (refused) parts.push(`${refused} workout${refused === 1 ? '' : 's'} refused by the server (kept on this device; see Settings, Your data)`);
  // A stale offline.js from the cache may not have it yet.
  const refusedParts = typeof refusedStateParts === 'function' ? refusedStateParts() : [];
  if (refusedParts.length) parts.push(`${refusedParts.map(part => STATE_PART_NAMES[part] || part).join(', ')} refused by the server (kept on this device)`);
  $('storageStatus').textContent = parts.join(' · ');
}

async function loadSavedWorkouts() {
  try {
    // Offline, the copy kept on this device from the last load stands in (see getSavedWorkouts), and the line under the
    // list still says the server is out of reach.
    let reached = true;
    const everything = await getSavedWorkouts().catch(error => {
      if (!error.copy) throw error;
      console.error('Unable to load saved workouts; showing the copy on this device.', error);
      reached = false;
      return error.copy;
    });
    // Strength workouts only: cardio sessions have the Cardio page, and no exercises for last time or the records.
    const workouts = everything.filter(workout => !isCardio(workout));
    savedWorkouts = workouts;
    savedSessions = everything;
    savedWorkoutsLoaded = true;
    renderSavedWorkouts(workouts);
    lastPerformance = buildLastPerformance([...workouts, ...readPendingWorkouts()]);
    saveLastPerformance();
    personalBests = bestsOf([...workouts, ...readPendingWorkouts()]);
    writeLocal(localKey('bests'), personalBests);
    renderExerciseSuggestions();
    // The program card's Progress is drawn from the workouts, which have only now arrived.
    renderProgram();
    renderScheduleNudge();
    // A workout already under way can say what finishing it earns, and last week can be looked back on, now the whole
    // history is here.
    if (activeSession) renderReach();
    renderRecap();
    renderWhatsNew();
    workoutsReachable = reached;
    renderStorageStatus();
    return workouts;
  } catch (error) {
    workoutsReachable = false;
    renderStorageStatus();
    console.error('Unable to load saved workouts.', error);
    return null;
  }
}

// A link from History says what to do with one of the saved workouts once they have loaded: ?start= starts it, ?edit=
// opens it in the form to change, and ?copy= opens it there as a new workout. It is taken off the address, so a reload
// does not do it again.
function takeRequestedWorkout() {
  const params = new URLSearchParams(location.search);
  const action = ['start', 'edit', 'copy'].find(name => params.has(name));
  if (!action) return null;
  const id = Number(params.get(action));
  params.delete(action);
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  return { action, id };
}

$('savedWorkoutList').onclick = async e => {
  const button = e.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'more') {
    showingAllSaved = true;
    renderSavedWorkouts(savedWorkouts);
    // Focus goes to the first of the workouts that were folded away, where reading carries on.
    $('savedWorkoutList').querySelectorAll('.saved-workout-toggle')[savedWorkoutsShown]?.focus({ preventScroll:true });
    return;
  }
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
  if (action === 'delete') {
    try {
      await deleteWorkout(workout.id);
      if (editingWorkout && editingWorkout.id === workout.id) $('clearBtn').click();
      await loadSavedWorkouts();
      // No question first: it can be taken back.
      offerUndo(`Deleted “${workout.name}”.`, async () => {
        const synced = await restoreDeletedWorkout(workout);
        showFeedback(synced ? `“${workout.name}” is back.` : `“${workout.name}” is back on this device and will sync when the server is reachable again.`, 'success');
        await loadSavedWorkouts();
      });
    } catch (error) {
      showFeedback('This workout could not be deleted.');
      console.error('Unable to delete workout.', error);
    }
  }
};
