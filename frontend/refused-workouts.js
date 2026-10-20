// Settings, Your data, "Refused by the server": the finished workouts the server will never accept as they are (too big, or over
// the account's limit), which offline.js keeps on the device rather than lose or send again and again. Each can be tried once
// more, saved to a file, or discarded. Loaded after settings.js, whose dialog it adds to.

// The workouts as they were when the list was drawn, so a button acts on the workout in its row even if the list has changed
// meanwhile (another tab); offline.js finds it again by its clientId.
let shownRefused = [];

function refusedReason(workout, refusals) {
  const refusal = workout.clientId ? refusals[workout.clientId] : null;
  if (refusal && refusal.error) return refusal.error;
  return refusal && refusal.status === 413 ? 'It is too big for the server to keep.' : 'The server will not accept it.';
}

function showRefusedFeedback(message) {
  const feedback = getSettingElement('refusedFeedback');
  if (feedback) setStatusLine(feedback, message);
}

// One row per workout, built with text nodes: its name, and what the server said, are never read as markup.
function renderRefusedWorkouts() {
  const box = getSettingElement('refusedWorkouts');
  // A page from the cache may be a version behind offline.js or the dialog.
  if (!box || typeof readRejectedWorkouts !== 'function' || typeof readRefusals !== 'function') return;
  shownRefused = readRejectedWorkouts();
  const refusals = readRefusals();
  box.hidden = shownRefused.length === 0;
  getSettingElement('settings-data-state').textContent = shownRefused.length ? `${shownRefused.length} refused` : 'Export or import';
  getSettingElement('refusedList').replaceChildren(...shownRefused.map((workout, index) => {
    const row = document.createElement('li');
    row.className = 'device refused';
    const about = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = workout.name || 'Untitled workout';
    const details = document.createElement('span');
    details.className = 'subtitle';
    const day = workout.createdAt ? new Date(workout.createdAt).toLocaleDateString(undefined, { month:'short', day:'numeric', year:'numeric' }) : '';
    details.textContent = [day, refusedReason(workout, refusals)].filter(Boolean).join(' · ');
    about.append(name, details);
    const actions = document.createElement('div');
    actions.className = 'refused-actions';
    [['retry', 'Retry'], ['download', 'Download'], ['discard', 'Discard']].forEach(([action, label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = label;
      button.setAttribute('aria-label', `${label} ${workout.name || 'Untitled workout'}${day ? `, ${day}` : ''}`);
      button.dataset.refusedAction = action;
      button.dataset.index = index;
      actions.append(button);
    });
    row.append(about, actions);
    return row;
  }));
}

// The workout as a file Import takes, without the clientId the server told it apart by or an id of the server it came from, so that
// importing it into an account that has the original (or this one, once there is room) cannot be mistaken for it.
function refusedWorkoutFile(workout) {
  const { clientId, id, ...plain } = workout;
  return JSON.stringify({ format:'workout-tracker-export', version:1, exportedAt:Date.now(), workouts:[plain] }, null, 2);
}

function downloadRefusedWorkout(workout) {
  const day = workout.createdAt ? new Date(workout.createdAt).toISOString().slice(0, 10) : 'undated';
  const name = `${(workout.name || 'workout').replace(/[^\w-]+/g, '-').replace(/^-+|-+$/g, '') || 'workout'}-${day}.json`;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([refusedWorkoutFile(workout)], { type:'application/json' }));
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  return name;
}

async function refusedAction(button) {
  const workout = shownRefused[Number(button.dataset.index)];
  if (!workout) return;
  const name = `“${workout.name || 'Untitled workout'}”`;
  if (button.dataset.refusedAction === 'download') {
    showRefusedFeedback(`Downloaded ${downloadRefusedWorkout(workout)}.`);
  } else if (button.dataset.refusedAction === 'discard') {
    if (!confirm(`Discard ${name}? It is deleted from this device and was never saved to your account. Download it first to keep a copy.`)) return;
    removeRefusedWorkout(workout);
    showRefusedFeedback(`Discarded ${name}.`);
  } else {
    const buttons = getSettingElement('refusedList').querySelectorAll('button');
    buttons.forEach(other => { other.disabled = true; });
    showRefusedFeedback(`Trying ${name}…`);
    const { outcome } = await retryRefusedWorkout(workout);
    buttons.forEach(other => { other.disabled = false; });
    showRefusedFeedback({
      saved:`Saved ${name} to your account.`,
      refused:`The server still refuses ${name}: ${refusedReason(workout, readRefusals())}`,
      signedout:'Sign in again to try it.',
      unreachable:'Could not reach the server. Try again when you are back online.'
    }[outcome]);
  }
  renderRefusedWorkouts();
}

if (getSettingElement('refusedList')) {
  getSettingElement('refusedList').onclick = event => {
    const button = event.target.closest('button[data-refused-action]');
    if (button && !button.disabled) refusedAction(button);
  };
  window.addEventListener('settingsopen', () => { showRefusedFeedback(''); renderRefusedWorkouts(); });
  window.addEventListener('syncchange', renderRefusedWorkouts);
  window.localReady.then(renderRefusedWorkouts);
}
