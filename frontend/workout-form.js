// The form for writing a workout down by hand, and for changing a saved one: its rows, adding an exercise, correcting a set, and
// saving it (a new one goes into the upload queue, a changed one straight to the server). Loaded before script.js, which starts the
// page and declares the state these use (exercises, editingWorkout, savedWorkouts); nothing here reads it until something is tapped.

// The form for writing a workout down by hand opens as its own card at the top, and closes again on Cancel or once saved.
function showWorkoutBuilder(editing = false) {
  $('workoutBuilderTitle').textContent = editing ? 'Edit workout' : 'Create a workout';
  $('workoutBuilderIntro').textContent = editing ? 'Change any set, add one you missed, or take one away, then update the workout.'
    : 'Add each exercise with its weight and reps, then save it to your history.';
  $('workoutBuilderCard').hidden = false;
  scrollToCard($('workoutBuilderCard'), 'start');
}

// The banner (showFeedback, clearFeedback) and markInvalid are common.js's, shared with the Cardio page.

// An exercise saved with its sets (done in a workout) is changed a set at a time, as it was logged: each set's weight and
// reps, a set added or taken away. One written down without them is changed by its weight and reps.
function exerciseRow(item, i) {
  const name = `<input class="exercise-edit" type="text" list="exerciseNames" autocomplete="off" value="${escapeHTML(item.name)}"`
    + ` data-index="${i}" data-field="name" aria-label="Exercise name">`;
  const remove = label => `<button class="remove" type="button" data-index="${i}">${label}</button>`;
  if (!item.sets?.length) {
    return `<li class="exercise">${name}`
      + `<input class="exercise-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(item.weight || '')}"`
      + ` data-index="${i}" data-field="weight" aria-label="Exercise weight">`
      + `<input class="exercise-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(item.reps)}"`
      + ` data-index="${i}" data-field="reps" aria-label="Exercise reps">${remove('Remove')}</li>`;
  }
  const count = isTimed(item) ? { unit:'s', label:'seconds' } : { unit:'reps', label:'reps' };
  const label = number => `${escapeHTML(item.name)} set ${number}`;
  // The last set stays: an exercise with none left is removed with Remove instead.
  const sets = item.sets.map((set, index) => `<li><span class="set-number">Set ${index + 1}</span>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="decimal" min="0" step="0.5" value="${escapeHTML(set.weight || '')}"`
    + ` data-exercise="${i}" data-set="${index}" data-field="weight" aria-label="${label(index + 1)} weight in ${weightUnit()}"><span>${weightUnit()}</span></div>`
    + `<div class="set-field"><input class="set-edit" type="number" inputmode="numeric" min="1" step="1" value="${escapeHTML(set.reps)}"`
    + ` data-exercise="${i}" data-set="${index}" data-field="reps" aria-label="${label(index + 1)} ${count.label}"><span>${count.unit}</span></div>`
    + (item.sets.length > 1 ? `<button class="remove" type="button" data-exercise="${i}" data-remove-set="${index}" aria-label="Remove ${label(index + 1)}" title="Remove">&times;</button>` : '<span></span>')
    + (isTimed(item) ? '' : setTypeSelectHtml(set, `data-exercise="${i}" data-set="${index}"`, label(index + 1))) + '</li>').join('');
  return `<li class="exercise has-sets">${name}<ol class="set-list">${sets}</ol>`
    + `<button class="secondary" type="button" data-exercise="${i}" data-add-set>Add set</button>${remove('Remove exercise')}</li>`;
}

function render() {
  const list = $('exerciseList');
  list.innerHTML = exercises.length ? exercises.map(exerciseRow).join('') : '<li class="empty">Your exercises will appear here.</li>';
  $('count').textContent = `${exercises.length} exercise${exercises.length === 1 ? '' : 's'}`;
}

function loadWorkoutIntoForm(stored, editMode) {
  // In the unit shown. An edit is saved in the unit the workout was kept in (see backToUnit); a copy is a new workout, in this one.
  const workout = inUnit(stored);
  showWorkoutBuilder(editMode);
  editingWorkout = editMode ? workout : null;
  editingStored = editMode ? stored : null;
  $('workoutName').value = workout.name;
  $('workoutDate').value = editMode ? dateInputValue(workout.createdAt) : dateInputValue(Date.now());
  $('workoutNotes').value = workout.notes || '';
  // The sets are copied, so a change abandoned with Cancel leaves the saved workout as it was.
  exercises.splice(0, exercises.length, ...workout.exercises.map(item => {
    if (!editMode) { const { sets, ...plan } = item; return plan; }
    return { ...item, ...(Array.isArray(item.sets) ? { sets:item.sets.map(set => ({ ...set })) } : {}) };
  }));
  $('saveBtn').textContent = editMode ? 'Update workout' : 'Save workout';
  render();
}

// What is wrong with an exercise written down by hand: [the field, what to tell the person], or null. `when` ends the sentence
// about the name ("before adding it"). An exercise with sets takes its weight and reps from them, so those two are not asked of it.
function exerciseFault(name, weight, reps, when) {
  if (!name.trim()) return ['name', `Enter an exercise name before ${when}.`];
  if (reps === null) return null;
  if (reps === '' || Number(reps) < 1) return ['reps', 'Enter at least 1 rep for this exercise.'];
  if (!Number.isInteger(Number(reps))) return ['reps', 'Reps must be a whole number.'];
  if (weight !== '' && Number(weight) < 0) return ['weight', 'Weight cannot be negative.'];
  return null;
}

$('addBtn').onclick = () => {
  const name = $('exercise').value.trim(), weight = $('weight').value, reps = $('reps').value;
  markInvalid($('exercise'), !name);
  markInvalid($('reps'), !reps || Number(reps) < 1);
  markInvalid($('weight'), weight !== '' && Number(weight) < 0);
  const fault = exerciseFault(name, weight, reps, 'adding it');
  if (fault) {
    const input = $({ name:'exercise', reps:'reps', weight:'weight' }[fault[0]]);
    markInvalid(input, true);
    showFeedback(fault[1]);
    input.focus();
    return;
  }
  const doubt = implausibleSet({ name }, { weight:Number(weight) || 0, reps:Number(reps) });
  if (doubt && !confirm(doubt.message)) { markInvalid($(doubt.field), true); $(doubt.field).focus(); return; }
  clearFeedback();
  exercises.push({ name, weight, reps }); $('exercise').value = ''; $('weight').value = ''; $('reps').value = ''; render(); $('exercise').focus();
};
$('createWorkoutBtn').onclick = () => { showWorkoutBuilder(Boolean(editingWorkout)); $('workoutName').focus({ preventScroll:true }); };
$('exercise').oninput = () => markInvalid($('exercise'), false);
$('weight').oninput = () => markInvalid($('weight'), false);
$('reps').oninput = () => markInvalid($('reps'), false);
$('exerciseList').oninput = e => {
  const index = e.target.dataset.index;
  const field = e.target.dataset.field;
  if (index !== undefined && field) { exercises[+index][field] = e.target.value; markInvalid(e.target, false); }
};
// A set's weight or reps is taken once it is changed; one that is not valid snaps back, as during a workout.
$('exerciseList').onchange = e => {
  const item = exercises[Number(e.target.dataset.exercise)];
  const set = item?.sets?.[Number(e.target.dataset.set)];
  const field = e.target.dataset.field;
  if (!set || !field) return;
  const value = e.target.value;
  if (field === 'type') {
    applySetType(set, value);
    return;
  }
  const problem = setChangeProblem(field, value, isTimed(item));
  if (problem) {
    showFeedback(problem);
    e.target.value = field === 'weight' ? set.weight || '' : set.reps;
    return;
  }
  if (!confirmSetChange(item, Number(e.target.dataset.set), field, Number(value) || 0, e.target)) return;
  set[field] = Number(value) || 0;
  clearFeedback();
};
$('exerciseList').onclick = e => {
  const button = e.target.closest('button');
  if (!button) return;
  const item = exercises[Number(button.dataset.exercise)];
  if (item && button.dataset.removeSet !== undefined) {
    item.sets.splice(Number(button.dataset.removeSet), 1);
    render();
  } else if (item && button.hasAttribute('data-add-set')) {
    // A set forgotten at the time: another like the last, its reps ready to change.
    const last = item.sets[item.sets.length - 1];
    item.sets.push({ weight:last.weight, reps:last.reps });
    render();
    document.querySelector(`#exerciseList [data-exercise="${exercises.indexOf(item)}"][data-set="${item.sets.length - 1}"][data-field=reps]`)?.focus();
  } else if (button.classList.contains('remove') && button.dataset.index !== undefined) {
    exercises.splice(Number(button.dataset.index), 1);
    render();
  }
};
$('clearBtn').onclick = () => {
  editingWorkout = null;
  editingStored = null;
  exercises.length = 0;
  $('workoutName').value = '';
  $('workoutDate').value = dateInputValue(Date.now());
  $('workoutNotes').value = '';
  $('saveBtn').textContent = 'Save workout';
  render();
  $('workoutBuilderCard').hidden = true;
};
// The form has a date and no time. A workout being changed keeps the time of day it was done at: with the date left alone it is
// exactly as it was, and moved to another day it keeps its time on that day. A new one has the middle of the day.
function workoutFormTime() {
  const day = $('workoutDate').value;
  if (!editingWorkout || !(editingWorkout.createdAt > 0)) return timestampFromDateInput(day);
  const was = new Date(editingWorkout.createdAt);
  if (dateInputValue(was.getTime()) === day) return editingWorkout.createdAt;
  const [year, month, date] = day.split('-').map(Number);
  return new Date(year, month - 1, date, was.getHours(), was.getMinutes(), was.getSeconds(), was.getMilliseconds()).getTime();
}

$('saveBtn').onclick = async () => {
  if (!exercises.length) { showFeedback('Add at least one exercise before saving the workout.'); return; }
  if (!$('workoutDate').value) { showFeedback('Choose a workout date before saving.'); $('workoutDate').focus(); return; }
  // The rows can be changed after they were added, to nothing: a nameless exercise or one with no reps is not a workout to keep.
  for (const [index, item] of exercises.entries()) {
    const fault = exerciseFault(String(item.name ?? ''), String(item.weight ?? ''), item.sets?.length ? null : String(item.reps ?? ''), 'saving');
    if (!fault) continue;
    const input = document.querySelector(`#exerciseList [data-index="${index}"][data-field=${fault[0]}]`);
    if (input) { markInvalid(input, true); input.focus(); }
    showFeedback(fault[1]);
    return;
  }
  // An exercise with sets takes its weight and reps from them, as finishing a workout gives them: the heaviest set, and
  // the last set's reps (or the reps a template planned, which it progresses from).
  const savedExercises = exercises.map(item => item.sets?.length
    ? { ...item, weight:Math.max(...item.sets.map(set => Number(set.weight) || 0)), reps:item.setCount ? item.reps : item.sets[item.sets.length - 1].reps }
    : { ...item });
  let workout = {
    ...editingWorkout, name:$('workoutName').value.trim() || 'Untitled workout', notes:$('workoutNotes').value.trim(), exercises:savedExercises,
    createdAt:workoutFormTime(), unit:weightUnit()
  };
  if (editingStored) workout = backToUnit(workout, editingStored);
  if (!workout.id) {
    // A new workout goes into the upload queue like a finished one, so it survives a dropped connection, and its clientId
    // lets the server ignore a retried upload. The form is cleared first, so a second tap has nothing left to save twice.
    // Once it uploads, the syncchange it reports lists it with the rest.
    workout.clientId = newClientId();
    queuePendingWorkout(workout);
    $('clearBtn').click();
    const synced = await flushPendingWorkouts();
    showFeedback(synced ? `“${workout.name}” saved successfully.`
      : `“${workout.name}” is saved on this device and will sync when the server is reachable again.`, 'success');
    return;
  }
  $('saveBtn').disabled = true;
  try {
    await updateSavedWorkout(workout);
  } catch (error) {
    showFeedback('This workout could not be saved. Check your connection and try again.');
    console.error('Unable to save workout.', error);
    return;
  } finally {
    $('saveBtn').disabled = false;
  }
  showFeedback(`“${workout.name}” saved successfully.`, 'success');
  $('clearBtn').click();
  await loadSavedWorkouts();
};

