// Sets per muscle and the Exercises card, on the Progress page. A week's sets are counted for the muscle each exercise
// works most (exercise-library.js: the account's choice, else a guess from the name), beside the weekly average of the
// weeks before, so a muscle that is being left behind shows. The Exercises card is where those muscles, and each
// exercise's equipment, are chosen, and where exercises of your own are added. Loaded after progress.js, whose workouts
// it counts and whose date helpers it shares.

// How many weeks before the one shown make its average, where there are workouts that far back.
const averageWeeks = 4;
// The Monday (as a time) of the week shown: this week's until the arrows move it.
let shownWeek = null;

// Midnight on the Monday of the week a time is in, where this device is, as the History calendar counts weeks.
function mondayOf(time) {
  return startOfWeek(new Date(time)).getTime();
}

function weeksAfter(monday, weeks) {
  return addDays(new Date(monday), 7 * weeks).getTime();
}

// The sets an exercise of a saved workout had: those logged, none if it was skipped, and one for an exercise saved by the
// workout form, whose weight and reps are its one set.
function setCount(item) {
  return Array.isArray(item.sets) ? item.sets.length : 1;
}

// Sets per muscle in the workouts from one time up to another, and the exercises done then that have no muscle to count for.
function setsByMuscle(from, to) {
  const counts = new Map(), uncounted = new Map();
  allWorkouts.forEach(workout => {
    if (workout.createdAt < from || workout.createdAt >= to) return;
    workout.exercises.forEach(item => {
      const key = exerciseKey(item.name ?? ''), sets = setCount(item);
      if (!key || !sets) return;
      const { muscle } = exerciseDetails(item.name);
      if (muscle) counts.set(muscle, (counts.get(muscle) || 0) + sets);
      else uncounted.set(key, String(item.name).trim());
    });
  });
  return { counts, uncounted };
}

// An average to a tenth, with no trailing zero: 9.5, 10, 0.3.
function formatAverage(value) {
  return String(Math.round(value * 10) / 10);
}

function renderMuscles() {
  const thisWeek = mondayOf(Date.now());
  const first = allWorkouts.length ? Math.min(thisWeek, mondayOf(Math.min(...allWorkouts.map(workout => workout.createdAt)))) : thisWeek;
  shownWeek = Math.min(thisWeek, Math.max(first, shownWeek ?? thisWeek));
  const end = weeksAfter(shownWeek, 1);
  const { counts, uncounted } = setsByMuscle(shownWeek, end);
  // Only weeks since the first workout make the average, so a new account is not measured against weeks it never had.
  const before = Math.min(averageWeeks, Math.round((shownWeek - first) / (7 * 86400000)));
  const usual = before ? setsByMuscle(weeksAfter(shownWeek, -before), shownWeek).counts : new Map();
  const average = muscle => before ? (usual.get(muscle) || 0) / before : 0;
  // Always in the same order, so a muscle is in the same place from one week to the next; one with no sets that week and
  // none before is left out.
  const rows = muscleGroups.filter(([muscle]) => counts.get(muscle) || average(muscle));
  const total = [...counts.values()].reduce((sum, sets) => sum + sets, 0);
  const scale = Math.max(1, ...rows.map(([muscle]) => Math.max(counts.get(muscle) || 0, average(muscle))));

  const which = shownWeek === thisWeek ? 'This week' : shownWeek === weeksAfter(thisWeek, -1) ? 'Last week' : 'Week';
  $('musclesSummary').textContent = allWorkouts.length
    ? `${which}, ${formatDate(shownWeek)} – ${formatDate(weeksAfter(shownWeek, 1) - 1)} · ${plural(total, 'set')}`
    : 'Every set you log, counted for the muscle its exercise works most.';
  $('musclesEarlier').disabled = shownWeek <= first;
  $('musclesLater').disabled = shownWeek >= thisWeek;
  $('muscleList').innerHTML = rows.length ? rows.map(([muscle, label]) => {
    const sets = counts.get(muscle) || 0;
    return `<li data-muscle="${muscle}"><span class="muscle-name">${label}</span>`
      + `<span class="muscle-bar" aria-hidden="true"><span class="muscle-fill"></span>${before ? '<span class="muscle-average"></span>' : ''}</span>`
      + `<span class="muscle-count">${plural(sets, 'set')}${before ? `<span class="muscle-usual"> · avg ${formatAverage(average(muscle))}</span>` : ''}</span></li>`;
  }).join('') : `<li class="empty">${!allWorkouts.length ? 'Log a workout to see the sets each muscle gets.' : shownWeek === thisWeek ? 'No sets logged this week yet.' : 'No sets logged that week.'}</li>`;
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup.
  $('muscleList').querySelectorAll('[data-muscle]').forEach(row => {
    const muscle = row.dataset.muscle;
    row.querySelector('.muscle-fill').style.width = `${(counts.get(muscle) || 0) / scale * 100}%`;
    const mark = row.querySelector('.muscle-average');
    if (mark) mark.style.left = `${average(muscle) / scale * 100}%`;
  });
  $('musclesKey').hidden = !(before && rows.length);
  $('musclesKey').textContent = `The mark on each bar, and avg, is the sets a week over the ${before === 1 ? 'week' : `${before} weeks`} before.`;
  const names = [...uncounted.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity:'base' }));
  $('musclesUncounted').hidden = !names.length;
  $('musclesUncountedNames').textContent = `Not counted, with no muscle yet: ${names.join(', ')}.`;
}

$('musclesEarlier').onclick = () => { shownWeek = weeksAfter(shownWeek, -1); renderMuscles(); };
$('musclesLater').onclick = () => { shownWeek = weeksAfter(shownWeek, 1); renderMuscles(); };
// To the Exercises card, at the first exercise with no muscle.
$('musclesUncountedLink').onclick = () => {
  $('libraryDetails').open = true;
  $('librarySearch').value = '';
  renderLibrary();
  $('exercisesCard').scrollIntoView({ behavior:'smooth', block:'start' });
  [...$('libraryList').querySelectorAll('select[data-field="muscle"]')].find(select => !select.value)?.focus({ preventScroll:true });
};

// ---- Exercises ----------------------------------------------------------------
// Every exercise logged, under its most recent spelling, and every one added here, A to Z, each with a choice of muscle
// and of equipment. Choosing one keeps it for that exercise in every workout, past and to come.

// Every exercise logged and every one in the library, with whether it has been logged.
function libraryExercises() {
  const exercises = new Map();
  [...allWorkouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => {
    const key = exerciseKey(item.name ?? '');
    if (key && !exercises.has(key)) exercises.set(key, { key, name:String(item.name).trim(), logged:true });
  }));
  Object.entries(exerciseLibrary).forEach(([key, entry]) => {
    if (!exercises.has(key)) exercises.set(key, { key, name:entry.name, logged:false });
  });
  return [...exercises.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity:'base' }));
}

// The options of a muscle or equipment choice, with a blank one first when there is a label for it.
function libraryOptions(kinds, chosen, blank) {
  return (blank ? `<option value="">${escapeHTML(blank)}</option>` : '')
    + kinds.map(([value, label]) => `<option value="${value}"${value === chosen ? ' selected' : ''}>${label}</option>`).join('');
}

function renderLibrary() {
  const exercises = libraryExercises();
  const missing = exercises.filter(exercise => !exerciseDetails(exercise.name).muscle).length;
  $('librarySummary').textContent = exercises.length
    ? `Show your ${plural(exercises.length, 'exercise')}${missing ? ` · ${missing} with no muscle` : ''}`
    : 'Show your exercises';
  // Every word typed has to be in the name, as History's search works.
  const words = $('librarySearch').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = exercises.filter(exercise => words.every(word => exercise.name.toLowerCase().includes(word)));
  $('libraryList').innerHTML = shown.length ? shown.map(exercise => {
    const details = exerciseDetails(exercise.name);
    const notes = [];
    if (!exercise.logged) notes.push('Your own, not logged yet');
    if (details.muscleGuessed && details.equipmentGuessed) notes.push('Guessed from its name');
    else if (details.muscleGuessed) notes.push('Muscle guessed from its name');
    else if (details.equipmentGuessed) notes.push('Equipment guessed from its name');
    if (!details.muscle) notes.push('Its sets are not counted until it has a muscle');
    const name = escapeHTML(exercise.name);
    return `<li data-key="${escapeHTML(exercise.key)}" data-name="${name}"><div class="library-name"><strong>${name}</strong>${notes.length ? `<span>${escapeHTML(notes.join(' · '))}</span>` : ''}</div>`
      + `<select data-field="muscle" aria-label="Muscle for ${name}">${libraryOptions(muscleGroups, details.muscle, details.muscle ? '' : 'Not set')}</select>`
      + `<select data-field="equipment" aria-label="Equipment for ${name}">${libraryOptions(equipmentKinds, details.equipment, details.equipment ? '' : 'Not set')}</select>`
      + (exercise.logged ? '' : `<button class="link-button" type="button" data-library-remove aria-label="Remove ${name}">Remove</button>`) + '</li>';
  }).join('') : `<li class="empty">${exercises.length ? 'No exercise has those words in its name.' : 'The exercises you log or add appear here.'}</li>`;
}

function showLibraryFeedback(message, isError = false) {
  $('libraryFeedback').textContent = message;
  $('libraryFeedback').classList.toggle('error', isError);
}

// The new exercise's choices start blank, which is the guess from its name, and say what that guess is as it is typed.
function renderLibraryForm() {
  const name = $('libraryName').value;
  const muscle = muscleLabel(guessMuscle(name)), equipment = equipmentLabel(guessEquipment(name));
  $('libraryMuscle').innerHTML = libraryOptions(muscleGroups, $('libraryMuscle').value, muscle ? `Guess: ${muscle}` : 'Guess');
  $('libraryEquipment').innerHTML = libraryOptions(equipmentKinds, $('libraryEquipment').value, equipment ? `Guess: ${equipment}` : 'Guess');
}

$('libraryList').addEventListener('change', event => {
  const select = event.target.closest('select[data-field]');
  const row = select && select.closest('li[data-key]');
  if (!row || !select.value) return;
  const { field } = select.dataset, { key, name } = row.dataset;
  setExerciseDetails(name, { [field]:select.value });
  renderLibrary();
  renderMuscles();
  // The list is drawn again, so the keyboard carries on from the same choice.
  $('libraryList').querySelector(`li[data-key="${CSS.escape(key)}"] select[data-field="${field}"]`)?.focus();
  showLibraryFeedback(field === 'muscle' ? `${name} counts for ${muscleLabel(select.value)}.` : `${name} is done with: ${equipmentLabel(select.value)}.`);
});

$('libraryList').addEventListener('click', event => {
  const row = event.target.closest('[data-library-remove]')?.closest('li[data-key]');
  if (!row) return;
  removeFromLibrary(row.dataset.name);
  renderLibrary();
  showLibraryFeedback(`Removed ${row.dataset.name}.`);
});

$('librarySearch').addEventListener('input', renderLibrary);
$('libraryName').addEventListener('input', renderLibraryForm);

$('libraryForm').onsubmit = event => {
  event.preventDefault();
  const typed = $('libraryName').value.trim();
  if (!typed) {
    showLibraryFeedback("Enter the new exercise's name.", true);
    $('libraryName').focus();
    return;
  }
  // An exercise already here keeps its spelling, and only what was chosen changes: a blank choice leaves its own alone.
  const known = libraryExercises().find(exercise => exercise.key === exerciseKey(typed));
  const name = known ? known.name : typed;
  const changes = Object.fromEntries([['muscle', $('libraryMuscle').value], ['equipment', $('libraryEquipment').value]].filter(([, value]) => value || !known));
  setExerciseDetails(name, changes);
  $('libraryForm').reset();
  renderLibraryForm();
  renderLibrary();
  renderMuscles();
  const { muscle } = exerciseDetails(name);
  showLibraryFeedback(known ? `Updated ${name}.` : `Added ${name}${muscle ? `, for ${muscleLabel(muscle)}` : ''}. It is suggested wherever you type an exercise.`);
};

renderLibraryForm();
// The library on the server replaces this device's once it answers, unless a choice made here is still uploading.
window.serverStateReady.then(() => {
  exerciseLibrary = loadExerciseLibrary();
  renderLibrary();
  if (allWorkouts.length) renderMuscles();
});
