// The Cardio page: timing a session, logging one by hand, and the sessions so far with this week's totals. A session is
// saved as a workout (cardio-activities.js says how), so it waits on this device through a network drop and uploads as a
// strength workout does, and History and Progress show it. The session being timed is kept on this device: it is only
// when it started and how long it was paused, so it keeps time with the screen off or the page closed.

// Saved sessions, newest first, as the server last sent them.
let cardioSessions = [];
let cardioLoaded = false;
let cardioReachable = true;
// The session being timed: { activity, name, startedAt, pausedAt, pausedTotal }, times in milliseconds, or null.
let cardioActive = null;
let cardioTicker = null;
// What the form is doing: { mode, workout }. 'log' is a session by hand, 'finish' the one being timed, 'edit' a saved one
// and 'copy' a saved one again as a new session. distanceShown is the distance as the form first showed it, so an edit
// that leaves it alone keeps what was logged exactly, rather than as converted and rounded.
let cardioForm = null;
let showingAllCardio = false;
const cardioShownAtFirst = 5;
const cardioListLimit = 20;

function cardioActiveKey() {
  return localKey('cardio-active');
}

function readCardioActive() {
  const stored = readLocal(cardioActiveKey());
  return stored && typeof stored === 'object' && Number(stored.startedAt) > 0 ? stored : null;
}

function saveCardioActive() {
  writeLocal(cardioActiveKey(), cardioActive);
}

// Seconds the session has been going, its pauses left out.
function cardioElapsed(session = cardioActive, now = Date.now()) {
  return Math.max(0, ((session.pausedAt || now) - session.startedAt - (Number(session.pausedTotal) || 0)) / 1000);
}

// Every session there is: those saved, and those finished here that are still waiting to upload.
function allCardio() {
  const pending = readPendingWorkouts().filter(isCardio).filter(workout => !cardioSessions.some(saved => saved.clientId && saved.clientId === workout.clientId));
  return [...cardioSessions, ...pending].sort((a, b) => b.createdAt - a.createdAt);
}

// The latest session under a key (an activity, or Other's own name), for last time.
function lastCardio(key) {
  return allCardio().find(workout => cardioKey(workout) === key) || null;
}

function shortDate(time) {
  return new Date(time).toLocaleDateString(undefined, { month:'short', day:'numeric' });
}

function markCardioField(element, invalid) {
  element.setAttribute('aria-invalid', String(invalid));
}

// ---- The session being timed ------------------------------------------------

function tickCardio() {
  if (cardioActive) $('cardioClock').textContent = formatClock(Math.floor(cardioElapsed()));
}

function renderCardioLast() {
  const last = cardioActive ? lastCardio(cardioKey({ name:cardioActive.name, cardio:{ activity:cardioActive.activity } })) : null;
  $('cardioLast').hidden = !last;
  if (last) $('cardioLast').textContent = `Last time (${shortDate(last.createdAt)}): ${describeCardio(last)}`;
}

function renderCardioActive() {
  clearInterval(cardioTicker);
  const session = cardioActive;
  const finishing = Boolean(cardioForm) && cardioForm.mode === 'finish';
  $('cardioActive').hidden = !session || finishing;
  $('cardioStartCard').hidden = Boolean(session) || Boolean(cardioForm);
  if (!session) return;
  const paused = Boolean(session.pausedAt);
  $('cardioActive').classList.toggle('paused', paused);
  $('cardioActiveTitle').textContent = session.name;
  $('cardioActiveStarted').textContent = `Started ${new Date(session.startedAt).toLocaleTimeString(undefined, { hour:'numeric', minute:'2-digit' })}${paused ? ' · paused' : ''}`;
  $('cardioPauseBtn').textContent = paused ? 'Resume' : 'Pause';
  renderCardioLast();
  tickCardio();
  if (!paused) cardioTicker = setInterval(tickCardio, 500);
}

// One tap starts the timer. One already going is replaced, after asking (unless Settings says not to).
function startCardio(activityId, name = '') {
  const activity = cardioActivity(activityId);
  if (cardioActive && getWorkoutSettings().confirmEnd && !confirm(`Replace your ${cardioActive.name} in progress? Its time so far will not be saved.`)) return;
  cardioForm = null;
  $('cardioFormCard').hidden = true;
  $('cardioSummary').hidden = true;
  cardioActive = { activity:activity.id, name:name || activity.name, startedAt:Date.now(), pausedAt:null, pausedTotal:0 };
  saveCardioActive();
  renderCardioActive();
  $('cardioActive').scrollIntoView({ behavior:'smooth', block:'start' });
}

// A cancelled session is gone as if never started; nothing is saved. One timed for under a minute (started by mistake)
// goes at once, a longer one asks first (unless Settings says not to). Either way the banner offers it back.
function cancelCardio() {
  const session = cardioActive;
  if (!session) return;
  const seconds = cardioElapsed(session);
  if (seconds >= 60 && getWorkoutSettings().confirmEnd && !confirm(`Cancel this ${session.name}? Its ${formatClock(seconds)} will not be saved.`)) return;
  cardioActive = null;
  saveCardioActive();
  renderCardioActive();
  showFeedback(`“${session.name}” was cancelled. Nothing was saved.`, 'info', { label:'Undo', run:() => resumeCardio(session) });
}

// Puts a cancelled session back as it was, its time still counting from when it started, unless another has begun.
function resumeCardio(session) {
  if (cardioActive) {
    showFeedback(`“${session.name}” cannot come back: another session has started.`);
    return;
  }
  cardioActive = session;
  saveCardioActive();
  renderCardioActive();
  showFeedback(`“${session.name}” is back.`, 'success');
}

function toggleCardioPause() {
  if (!cardioActive) return;
  if (cardioActive.pausedAt) {
    cardioActive.pausedTotal = (Number(cardioActive.pausedTotal) || 0) + Date.now() - cardioActive.pausedAt;
    cardioActive.pausedAt = null;
  } else cardioActive.pausedAt = Date.now();
  saveCardioActive();
  renderCardioActive();
}

// Finish stops the clock and asks for the rest. Back to the timer leaves it paused, a tap from going on.
function finishCardio() {
  if (!cardioActive) return;
  if (!cardioActive.pausedAt) {
    cardioActive.pausedAt = Date.now();
    saveCardioActive();
  }
  openCardioForm('finish', { activity:cardioActive.activity, name:cardioActive.name, createdAt:Date.now(), duration:Math.floor(cardioElapsed()) });
}

// ---- The form -------------------------------------------------------------

// A saved session's numbers as the form takes them, in the units shown.
function cardioDraft(workout) {
  const cardio = workout.cardio || {};
  return { activity:activityOf(workout).id, name:workout.name, createdAt:workout.createdAt, duration:Number(workout.duration) || 0, distance:sessionDistance(workout),
    calories:cardio.calories, heartRate:cardio.heartRate, floors:cardio.floors, notes:workout.notes || '' };
}

// A number as a field shows it: up to two decimals, or whole metres.
function fieldNumber(value, unit) {
  return value > 0 ? String(unit === 'm' ? Math.round(value) : Math.round(value * 100) / 100) : '';
}

function openCardioForm(mode, draft, workout = null) {
  const activity = cardioActivity(draft.activity);
  const titles = { log:'Log a session', finish:`Finish your ${activity.named ? 'session' : activity.name.toLowerCase()}`, edit:'Edit session', copy:'Log a session' };
  const intros = {
    log:'A session you did without the timer: what it was, when, and for how long.',
    finish:'The time is from the timer. Add the distance and anything else the machine or your watch shows.',
    edit:'Change anything about this session.',
    copy:'The same as before, as a new session for today. Change what was different.'
  };
  $('cardioActivity').innerHTML = cardioActivities.map(item => `<option value="${item.id}">${escapeHTML(item.name)}</option>`).join('');
  $('cardioActivity').value = activity.id;
  $('cardioName').value = activity.named && draft.name !== activity.name ? draft.name || '' : '';
  $('cardioDate').max = dateInputValue(Date.now());
  $('cardioDate').value = dateInputValue(draft.createdAt || Date.now());
  const seconds = Math.round(Number(draft.duration) || 0);
  $('cardioHours').value = seconds >= 3600 ? String(Math.floor(seconds / 3600)) : '';
  $('cardioMinutes').value = seconds ? String(Math.floor(seconds % 3600 / 60)) : '';
  $('cardioSeconds').value = seconds ? String(seconds % 60) : '';
  const unit = shownDistanceUnit(activity);
  $('cardioDistance').value = fieldNumber(Number(draft.distance) || 0, unit);
  $('cardioDistance').dataset.unit = unit;
  $('cardioCalories').value = Number(draft.calories) > 0 ? String(Math.round(draft.calories)) : '';
  $('cardioHeartRate').value = Number(draft.heartRate) > 0 ? String(Math.round(draft.heartRate)) : '';
  $('cardioFloors').value = Number(draft.floors) > 0 ? String(Math.round(draft.floors)) : '';
  $('cardioNotes').value = draft.notes || '';
  $('cardioForm').querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
  cardioForm = { mode, workout, distanceShown:$('cardioDistance').value };
  $('cardioFormTitle').textContent = titles[mode];
  $('cardioFormIntro').textContent = intros[mode];
  $('cardioSave').textContent = mode === 'edit' ? 'Save changes' : 'Save session';
  $('cardioFormCancel').textContent = mode === 'finish' ? 'Back to the timer' : 'Cancel';
  syncCardioForm();
  $('cardioSummary').hidden = true;
  $('cardioFormCard').hidden = false;
  renderCardioActive();
  $('cardioFormCard').scrollIntoView({ behavior:'smooth', block:'start' });
  // A timed session already has its time and activity: what is left to enter is the distance (or floors).
  const first = mode !== 'finish' ? $('cardioActivity') : activity.floors ? $('cardioFloors') : activity.distance ? $('cardioDistance') : $('cardioCalories');
  first.focus({ preventScroll:true });
}

function closeCardioForm() {
  cardioForm = null;
  $('cardioFormCard').hidden = true;
  renderCardioActive();
}

function formSeconds() {
  const part = id => Math.max(0, Number($(id).value) || 0);
  return part('cardioHours') * 3600 + part('cardioMinutes') * 60 + part('cardioSeconds');
}

// The fields an activity has (a distance in its unit, floors, a name for Other), and how fast the numbers so far work out.
function syncCardioForm() {
  const activity = cardioActivity($('cardioActivity').value);
  $('cardioNameField').hidden = !activity.named;
  $('cardioDistanceField').hidden = !activity.distance;
  $('cardioFloorsField').hidden = !activity.floors;
  const unit = shownDistanceUnit(activity);
  const field = $('cardioDistance');
  // A distance typed for one activity carries over to another, converted when their units differ (a rower's metres).
  if (field.dataset.unit && field.dataset.unit !== unit && field.value !== '' && Number(field.value) > 0) {
    field.value = fieldNumber(convertDistance(Number(field.value), field.dataset.unit, unit), unit);
  }
  field.dataset.unit = unit;
  field.step = unit === 'm' ? '1' : 'any';
  $('cardioDistanceUnit').textContent = unit;
  const distance = Number(field.value), seconds = formSeconds();
  const rate = activity.rate && activity.distance && distance > 0 && seconds > 0 ? rateOf(activity, distance, seconds, unit) : null;
  $('cardioRate').textContent = rate ? `${rateName(activity)}: ${rate.text}` : '';
}

// What is wrong with the form, as [message, field], or null.
function cardioFormProblem(values) {
  const today = dateInputValue(Date.now());
  if (!values.day || values.day > today) return ['Choose the day of the session, today or before.', $('cardioDate')];
  if (!(values.seconds > 0)) return ['Enter how long the session took.', $('cardioMinutes')];
  if (values.seconds >= 100 * 3600) return ['Enter a time under 100 hours.', $('cardioHours')];
  const longest = values.unit === 'm' ? 1000000 : 1000;
  if (!Number.isFinite(values.distance) || values.distance < 0 || values.distance > longest) return [`Enter a distance from 0 to ${longest.toLocaleString()} ${values.unit}, or leave it empty.`, $('cardioDistance')];
  if (!Number.isFinite(values.floors) || values.floors < 0 || values.floors > 10000) return ['Enter the floors climbed, up to 10,000, or leave it empty.', $('cardioFloors')];
  if (!Number.isFinite(values.calories) || values.calories < 0 || values.calories > 20000) return ['Enter calories from 0 to 20,000, or leave it empty.', $('cardioCalories')];
  if (!Number.isFinite(values.heartRate) || (values.heartRate !== 0 && (values.heartRate < 20 || values.heartRate > 250))) {
    return ['Enter an average heart rate from 20 to 250 bpm, or leave it empty.', $('cardioHeartRate')];
  }
  return null;
}

// When the session happened. A timed one finished now, as does one logged for today; one logged for another day is at
// noon on it. An edited one keeps its time unless its day changed, and then keeps its time of day on the new one.
function cardioTime(mode, day, workout) {
  if (mode === 'edit' && workout) {
    if (day === dateInputValue(workout.createdAt)) return workout.createdAt;
    const [year, month, date] = day.split('-').map(Number);
    const was = new Date(workout.createdAt);
    return new Date(year, month - 1, date, was.getHours(), was.getMinutes(), was.getSeconds()).getTime();
  }
  return day === dateInputValue(Date.now()) ? Date.now() : timestampFromDateInput(day);
}

async function saveCardioForm() {
  if (!cardioForm) return;
  const { mode, workout:editing, distanceShown } = cardioForm;
  const activity = cardioActivity($('cardioActivity').value);
  const number = id => ($(id).value === '' ? 0 : Number($(id).value));
  const values = { day:$('cardioDate').value, seconds:Math.round(formSeconds()), unit:shownDistanceUnit(activity),
    distance:activity.distance ? number('cardioDistance') : 0, floors:activity.floors ? number('cardioFloors') : 0,
    calories:number('cardioCalories'), heartRate:number('cardioHeartRate') };
  $('cardioForm').querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
  const problem = cardioFormProblem(values);
  if (problem) {
    markCardioField(problem[1], true);
    showFeedback(problem[0]);
    problem[1].focus();
    return;
  }
  clearFeedback();
  const name = activity.named ? $('cardioName').value.trim() || activity.name : activity.name;
  // An edit that leaves the distance as it was shown keeps what was logged, in its own unit, rather than converted.
  const kept = mode === 'edit' && editing && $('cardioDistance').value === distanceShown && editing.cardio && editing.cardio.distance > 0
    && activityOf(editing).distance === activity.distance;
  const distance = values.distance > 0 ? (kept ? { distance:editing.cardio.distance, distanceUnit:enteredDistanceUnit(editing) }
    : { distance:values.unit === 'm' ? Math.round(values.distance) : Math.round(values.distance * 100) / 100, distanceUnit:values.unit }) : {};
  const cardio = { activity:activity.id, ...distance, ...(values.calories > 0 ? { calories:Math.round(values.calories) } : {}),
    ...(values.heartRate > 0 ? { heartRate:Math.round(values.heartRate) } : {}), ...(values.floors > 0 ? { floors:Math.round(values.floors) } : {}) };
  const workout = { ...(mode === 'edit' ? editing : {}), kind:'cardio', name, notes:$('cardioNotes').value.trim(), exercises:[],
    createdAt:cardioTime(mode, values.day, editing), duration:values.seconds, cardio, clientId:mode === 'edit' ? editing.clientId : newClientId() };
  if (!workout.clientId) delete workout.clientId;
  if (mode === 'edit') {
    $('cardioSave').disabled = true;
    try {
      const response = await syncFetch(`/api/workouts/${encodeURIComponent(editing.id)}`, { method:'PUT', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(workout) });
      if (!response.ok) throw new Error(`Saving the session failed (${response.status}).`);
    } catch (error) {
      console.error('Unable to save the session.', error);
      showFeedback('This session could not be saved. Check your connection and try again.');
      return;
    } finally {
      $('cardioSave').disabled = false;
    }
    closeCardioForm();
    showFeedback(`Saved your changes to “${name}”.`, 'success');
    await loadCardioSessions();
    return;
  }
  // Records are against every session before this one, so they are worked out before it joins them. Then it goes into
  // the upload queue, where nothing can lose it.
  const records = newCardioRecords(workout, allCardio());
  queuePendingWorkout(workout);
  if (mode === 'finish') {
    cardioActive = null;
    saveCardioActive();
  }
  closeCardioForm();
  renderCardio();
  showCardioSummary(workout, records);
  const synced = await flushPendingWorkouts();
  showFeedback(synced ? `“${name}” saved.` : `“${name}” is saved on this device and will sync when the server is reachable again.`, 'success');
  if (synced) await loadCardioSessions();
}

// ---- After a session ------------------------------------------------------

function showCardioSummary(workout, records) {
  const activity = activityOf(workout);
  const cardio = workout.cardio || {};
  const distance = sessionDistance(workout), rate = sessionRate(workout);
  const stats = [[formatClock(workout.duration), 'Time'],
    ...(distance ? [[formatDistance(distance, shownDistanceUnit(activity)), 'Distance']] : []),
    ...(rate ? [[rate.text, rateName(activity)]] : []),
    ...(cardio.floors ? [[String(cardio.floors), 'Floors']] : []),
    ...(cardio.heartRate ? [[`${cardio.heartRate} bpm`, 'Heart rate']] : []),
    ...(cardio.calories ? [[String(cardio.calories), 'Calories']] : [])];
  $('cardioSummaryName').textContent = `${workout.name} · ${new Date(workout.createdAt).toLocaleDateString(undefined, { weekday:'short', month:'short', day:'numeric' })}`;
  $('cardioSummaryStats').innerHTML = stats.map(([value, label]) => `<li><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></li>`).join('');
  $('cardioSummaryRecords').hidden = !records.length;
  $('cardioSummaryRecordList').innerHTML = records.map(record => `<li>${escapeHTML(record)}</li>`).join('');
  $('cardioSummaryProgress').href = `progress.html?exercise=${encodeURIComponent(cardioKey(workout))}`;
  $('cardioSummary').hidden = false;
  $('cardioSummary').scrollIntoView({ behavior:'smooth', block:'start' });
  if (records.length) celebrate($('cardioSummaryTitle'), 40, 1.2);
}

// ---- The sessions so far --------------------------------------------------

// Midnight on this week's Monday, as the History calendar counts weeks.
function cardioWeekStart() {
  const today = new Date();
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - (today.getDay() + 6) % 7).getTime();
}

// "This week: 3 sessions · 1 h 35 min · 8.3 mi": the distance is the walking, running and riding, in miles or kilometres,
// its number and unit kept on one line.
function renderCardioWeek() {
  const week = allCardio().filter(workout => workout.createdAt >= cardioWeekStart());
  if (!week.length) {
    $('cardioWeek').textContent = cardioLoaded ? 'Nothing yet this week.' : '';
    return;
  }
  const seconds = week.reduce((sum, workout) => sum + (Number(workout.duration) || 0), 0);
  const distance = week.filter(workout => activityOf(workout).distance === 'road').reduce((sum, workout) => sum + (sessionDistance(workout) || 0), 0);
  const far = distance ? formatDistance(distance, distanceUnitOf()).replace(' ', '\u00a0') : '';
  $('cardioWeek').textContent = [`This week: ${plural(week.length, 'session')}`, formatDuration(seconds), far].filter(Boolean).join(' · ');
}

// A button for each activity, saying when it was last done and how far (or for how long). A number keeps its unit on its
// line, where a narrow button would break "5,000 m" in two.
function renderCardioStart() {
  const sessions = allCardio();
  $('cardioActivityGrid').innerHTML = cardioActivities.map(activity => {
    const last = activity.named ? null : sessions.find(workout => activityOf(workout).id === activity.id);
    const distance = last ? sessionDistance(last) : null;
    const line = activity.named ? 'Anything else; name it when you finish'
      : last ? `Last ${shortDate(last.createdAt)} · ${distance ? formatDistance(distance, shownDistanceUnit(activity)).replace(' ', '\u00a0') : formatClock(last.duration)}`
        : 'Start the timer';
    return `<button class="cardio-activity" type="button" data-activity="${activity.id}"><strong>${escapeHTML(activity.name)}</strong><span>${escapeHTML(line)}</span></button>`;
  }).join('');
}

// The latest sessions, a line each like the Strength page's saved workouts: the name (tap it for everything the session
// did), Start to do it again, and a ⋯ menu to copy, edit or delete it. Five show, then Show more, then History for the rest.
function renderCardioList() {
  const list = $('cardioList');
  if (!cardioLoaded) return;
  const recent = cardioSessions.slice(0, cardioListLimit);
  const folded = showingAllCardio ? 0 : Math.max(0, recent.length - cardioShownAtFirst);
  const moreButton = folded ? `<button class="secondary" type="button" data-action="more">Show ${folded} more</button>` : '';
  const historyLink = cardioSessions.length > cardioShownAtFirst ? '<a class="button-link secondary" href="history.html">See them all in History</a>' : '';
  const more = moreButton || historyLink ? `<li class="more-workouts">${moreButton}${historyLink}</li>` : '';
  list.innerHTML = recent.length ? recent.map((workout, index) => `<li class="saved-workout" data-id="${escapeHTML(workout.id)}"${index >= recent.length - folded ? ' hidden' : ''}>`
    + '<div class="saved-workout-summary saved-workout-row">'
    + '<button class="saved-workout-toggle" type="button" data-action="view" aria-expanded="false">'
    + `<strong>${escapeHTML(workout.name)}</strong><span>${escapeHTML(describeSessionDate(workout))}</span></button>`
    + '<div class="row-actions"><button class="primary" type="button" data-action="start">Start</button>'
    + `<details class="row-menu"><summary class="secondary" aria-label="More for ${escapeHTML(workout.name)}">&middot;&middot;&middot;</summary>`
    + '<div class="row-menu-items"><button type="button" data-action="copy">Copy as new</button><button type="button" data-action="edit">Edit</button>'
    + '<button class="danger" type="button" data-action="delete">Delete</button></div></details></div></div>'
    + `<div class="workout-details" hidden>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}`
    + `<ul><li><strong><a href="progress.html?exercise=${encodeURIComponent(cardioKey(workout))}">${escapeHTML(workout.name)}</a></strong>`
    + `<span>${escapeHTML(describeCardio(workout))}</span></li></ul></div></li>`).join('') + more
    : '<li class="empty">No sessions yet. Start one above, or log one you did.</li>';
}

// Nothing to say while everything is saved to the account; the line only speaks up when something is not.
function renderCardioStatus() {
  const waiting = readPendingWorkouts().length, refused = readRejectedWorkouts().length;
  const parts = cardioReachable ? [] : ['Server unreachable'];
  if (waiting) parts.push(`${plural(waiting, 'workout')} waiting to sync`);
  if (refused) parts.push(`${plural(refused, 'workout')} refused by the server (kept on this device)`);
  $('cardioStatus').textContent = parts.join(' · ');
}

function renderCardio() {
  renderCardioList();
  renderCardioWeek();
  renderCardioStart();
  renderCardioStatus();
  renderCardioLast();
}

async function loadCardioSessions() {
  try {
    cardioSessions = (await getSavedWorkouts()).filter(isCardio).sort((a, b) => b.createdAt - a.createdAt);
    cardioLoaded = true;
    cardioReachable = true;
  } catch (error) {
    cardioReachable = false;
    console.error('Unable to load cardio sessions.', error);
    if (!cardioLoaded) $('cardioList').innerHTML = '<li class="empty">Your sessions could not be loaded. They show once the server can be reached.</li>';
  }
  renderCardio();
  return cardioLoaded ? cardioSessions : null;
}

async function deleteCardio(workout) {
  if (!confirm(`Delete “${workout.name}” of ${shortDate(workout.createdAt)}?`)) return;
  try {
    const response = await syncFetch(`/api/workouts/${encodeURIComponent(workout.id)}`, { method:'DELETE' });
    if (!response.ok) throw new Error(`Delete failed (${response.status}).`);
  } catch (error) {
    console.error('Unable to delete the session.', error);
    showFeedback('This session could not be deleted. Check your connection and try again.');
    return;
  }
  if (cardioForm && cardioForm.workout && cardioForm.workout.id === workout.id) closeCardioForm();
  showFeedback(`Deleted “${workout.name}”.`, 'success');
  await loadCardioSessions();
}

// A link from History says what to do with one of the sessions once they have loaded: ?start= times it again, ?edit=
// opens it in the form, and ?copy= opens it there as a new session. It is taken off the address, so a reload does not
// do it again.
function takeCardioRequest() {
  const params = new URLSearchParams(location.search);
  const action = ['start', 'edit', 'copy'].find(name => params.has(name));
  if (!action) return null;
  const id = Number(params.get(action));
  params.delete(action);
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  return { action, id };
}

function actOnCardio(action, workout) {
  if (action === 'start') startCardio(activityOf(workout).id, workout.name);
  if (action === 'edit') openCardioForm('edit', cardioDraft(workout), workout);
  if (action === 'copy') openCardioForm('copy', { ...cardioDraft(workout), createdAt:Date.now() });
}

// ---- Wiring -----------------------------------------------------------------

$('cardioActivityGrid').onclick = event => {
  const button = event.target.closest('[data-activity]');
  if (button) startCardio(button.dataset.activity);
};
// Logging by hand starts from the activity done last.
$('cardioLogBtn').onclick = () => {
  const last = allCardio()[0];
  openCardioForm('log', { activity:last ? activityOf(last).id : 'walk', name:last && activityOf(last).named ? last.name : '', createdAt:Date.now() });
};
$('cardioPauseBtn').onclick = toggleCardioPause;
$('cardioFinishBtn').onclick = finishCardio;
$('cardioCancelBtn').onclick = cancelCardio;
$('cardioForm').onsubmit = event => { event.preventDefault(); saveCardioForm(); };
['input', 'change'].forEach(type => $('cardioForm').addEventListener(type, event => {
  if (event.target.hasAttribute('aria-invalid')) event.target.removeAttribute('aria-invalid');
  syncCardioForm();
}));
$('cardioFormCancel').onclick = closeCardioForm;
$('cardioSummaryDone').onclick = () => { $('cardioSummary').hidden = true; };
$('formFeedback').onclick = clearFeedback;
$('settingsButton').addEventListener('click', clearFeedback);
$('cardioList').onclick = event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  if (button.dataset.action === 'more') {
    showingAllCardio = true;
    renderCardioList();
    $('cardioList').querySelectorAll('.saved-workout-toggle')[cardioShownAtFirst]?.focus({ preventScroll:true });
    return;
  }
  const row = button.closest('.saved-workout');
  const workout = row && cardioSessions.find(item => String(item.id) === row.dataset.id);
  if (!workout) return;
  const menu = button.closest('.row-menu');
  if (menu) menu.open = false;
  if (button.dataset.action === 'view') {
    const details = row.querySelector('.workout-details');
    details.hidden = !details.hidden;
    button.setAttribute('aria-expanded', String(!details.hidden));
  } else if (button.dataset.action === 'delete') deleteCardio(workout);
  else actOnCardio(button.dataset.action, workout);
};
// The clock catches up at once when the page is looked at again; a hidden page's timers run late.
document.addEventListener('visibilitychange', () => { if (!document.hidden) tickCardio(); });
// Miles or kilometres from Settings change every distance shown, and the one being typed.
window.addEventListener('settingschange', () => {
  renderCardio();
  if (cardioForm) syncCardioForm();
});
window.addEventListener('syncchange', event => {
  renderCardioStatus();
  if (event.detail.uploaded && cardioLoaded) loadCardioSessions();
});

renderCardioStart();
window.localReady.then(() => {
  cardioActive = readCardioActive();
  renderCardioActive();
  renderCardio();
}).then(flushPendingWorkouts).then(loadCardioSessions).then(sessions => {
  const request = takeCardioRequest();
  const workout = request && sessions && sessions.find(item => item.id === request.id);
  if (workout) actOnCardio(request.action, workout);
});
