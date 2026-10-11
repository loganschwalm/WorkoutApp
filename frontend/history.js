// ---- Every saved workout ---------------------------------------------------
// One line a workout (tap it for its sets), under a heading for its month with that month's workouts and time. A search
// narrows the list to workouts whose name, exercises or notes have every word typed. The latest few months show at
// first and Show older brings the rest; a search, or a day picked on the calendar, looks through all of them.
const monthsShownAtFirst = 3;
let showingAllMonths = false;
// Workouts opened to show their sets, kept open when the list is drawn again (a search, a deletion).
const openWorkouts = new Set();

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function searchWords() {
  return $('historySearch').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
}

function matchesSearch(workout, words) {
  const text = [workout.name, workout.notes || '', ...workout.exercises.map(item => item.name)].join(' ').toLowerCase();
  return words.every(word => text.includes(word));
}

// "12 workouts · 11 h 40 min": the time only counts workouts that were timed.
function describeMonth(workouts) {
  const seconds = workouts.reduce((sum, workout) => sum + (Number(workout.duration) > 0 ? Number(workout.duration) : 0), 0);
  return [plural(workouts.length, 'workout'), seconds ? formatDuration(seconds) : ''].filter(Boolean).join(' · ');
}

// What a row's details list: a strength workout's exercises and their sets, or a cardio session's numbers.
function workoutLines(workout) {
  if (isCardio(workout)) {
    return `<li><strong><a href="progress.html?exercise=${encodeURIComponent(cardioKey(workout))}">${escapeHTML(workout.name)}</a></strong>`
      + `<span>${escapeHTML(describeCardio(workout))}</span></li>`;
  }
  return inUnit(workout).exercises.map(item => `<li><strong><a href="progress.html?exercise=${encodeURIComponent(exerciseKey(item.name))}">`
    + `${escapeHTML(item.name)}</a></strong><span>${escapeHTML(describeSavedExercise(item))}</span></li>`).join('');
}

// The same row as the Strength page's: the name (tap for the sets), Start, and a ⋯ menu to copy, edit or delete it.
// Starting, copying and editing happen on the page the workout belongs to: the Strength page's workout form, or for a
// cardio session, the Cardio page.
function historyRow(workout) {
  const open = openWorkouts.has(workout.id);
  const page = isCardio(workout) ? 'cardio.html' : 'index.html';
  return `<li class="saved-workout history-workout" data-id="${escapeHTML(workout.id)}" data-date="${calendarDayKey(new Date(workout.createdAt))}">`
    + '<div class="saved-workout-summary saved-workout-row">'
    + `<button class="saved-workout-toggle" type="button" data-action="view" aria-expanded="${open}">`
    + `<strong>${escapeHTML(workout.name)}</strong><span>${escapeHTML(isCardio(workout) ? describeSessionDate(workout) : describeWorkoutDate(workout))}</span></button>`
    + `<div class="row-actions"><a class="button-link primary" href="${page}?start=${encodeURIComponent(workout.id)}">Start</a>`
    + `<details class="row-menu"><summary class="secondary" aria-label="More for ${escapeHTML(workout.name)}">&middot;&middot;&middot;</summary>`
    + '<div class="row-menu-items"><button type="button" data-action="copy">Copy as new</button><button type="button" data-action="edit">Edit</button>'
    + '<button class="danger" type="button" data-action="delete">Delete</button></div></details></div></div>'
    + `<div class="workout-details"${open ? '' : ' hidden'}>${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}`
    + `<ul>${workoutLines(workout)}</ul></div></li>`;
}

// The line under the page's name: how many sessions there are, over how long. This week is the calendar's line.
function renderHistoryStatus(workouts) {
  if (!workouts.length) { $('pageStatus').textContent = 'Nothing saved yet. Finish a workout and it shows up here.'; return; }
  const times = workouts.map(workout => workout.createdAt);
  const thisYear = new Date().getFullYear();
  const date = time => new Date(time).toLocaleDateString(undefined, { month:'short', day:'numeric', ...(new Date(time).getFullYear() === thisYear ? {} : { year:'numeric' }) });
  const first = Math.min(...times), latest = Math.max(...times);
  $('pageStatus').textContent = workouts.length === 1 ? `1 session, on ${date(latest)}.`
    : `${plural(workouts.length, 'session')} since ${date(first)}, the latest on ${date(latest)}.`;
}

function renderHistory(workouts) {
  renderHistoryStatus(workouts);
  const words = searchWords();
  const shown = words.length ? workouts.filter(workout => matchesSearch(workout, words)) : workouts;
  $('historySummary').textContent = words.length ? `${shown.length} of ${plural(workouts.length, 'saved workout')}` : plural(workouts.length, 'saved workout');
  // Newest first, as the server sends them, so each month's workouts arrive together.
  const months = new Map();
  shown.forEach(workout => {
    const key = monthKey(new Date(workout.createdAt));
    months.set(key, [...(months.get(key) || []), workout]);
  });
  const everyMonth = showingAllMonths || words.length > 0;
  const folded = everyMonth ? [] : [...months.values()].slice(monthsShownAtFirst).flat();
  const list = [...months].map(([key, monthWorkouts], index) => {
    const [year, month] = key.split('-').map(Number);
    const name = new Date(year, month - 1, 1).toLocaleDateString(undefined, { month:'long', year:'numeric' });
    return `<li class="history-month" data-month="${key}"${!everyMonth && index >= monthsShownAtFirst ? ' hidden' : ''}>`
      + `<h3 class="history-month-heading"><span>${escapeHTML(name)}</span><span class="history-month-total">${escapeHTML(describeMonth(monthWorkouts))}</span></h3>`
      + `<ul class="history-month-list">${monthWorkouts.map(historyRow).join('')}</ul></li>`;
  }).join('');
  const older = folded.length ? `<li class="more-workouts"><button class="secondary" type="button" data-action="older">Show ${plural(folded.length, 'older workout')}</button></li>` : '';
  $('historyList').innerHTML = shown.length ? list + older
    : `<li class="empty">${workouts.length ? 'No saved workouts match that search.' : 'No saved workouts yet.'}</li>`;
}

function showHistoryFeedback(message, failed = false) {
  const feedback = $('historyFeedback');
  feedback.textContent = message;
  feedback.className = `${failed ? 'auth-feedback' : 'subtitle'} history-feedback`;
  feedback.hidden = false;
}

async function deleteHistoryWorkout(workout) {
  if (!confirm(`Delete “${workout.name}”?`)) return;
  try {
    const response = await syncFetch(`/api/workouts/${encodeURIComponent(workout.id)}`, { method:'DELETE' });
    if (!response.ok) throw new Error(`Delete failed (${response.status}).`);
  } catch (error) {
    console.error('Unable to delete workout.', error);
    showHistoryFeedback('This workout could not be deleted. Check your connection and try again.', true);
    return;
  }
  openWorkouts.delete(workout.id);
  showHistory(historyWorkouts.filter(item => item.id !== workout.id));
  showHistoryFeedback(`Deleted “${workout.name}”.`);
}

function showWorkoutDetails(row, open) {
  row.querySelector('.workout-details').hidden = !open;
  row.querySelector('[data-action=view]').setAttribute('aria-expanded', String(open));
  const id = Number(row.dataset.id);
  if (open) openWorkouts.add(id);
  else openWorkouts.delete(id);
}

$('historyList').onclick = event => {
  const button = event.target.closest('[data-action]');
  if (!button || !historyWorkouts) return;
  const action = button.dataset.action;
  if (action === 'older') {
    const first = $('historyList').querySelector('.history-month[hidden]');
    showingAllMonths = true;
    renderHistory(historyWorkouts);
    // Focus goes to the first workout that was folded away, where reading carries on.
    if (first) $('historyList').querySelector(`.history-month[data-month="${first.dataset.month}"] .saved-workout-toggle`)?.focus();
    return;
  }
  const row = button.closest('.history-workout');
  const workout = historyWorkouts.find(item => String(item.id) === row.dataset.id);
  if (!workout) return;
  const menu = button.closest('.row-menu');
  if (menu) menu.open = false;
  if (action === 'view') showWorkoutDetails(row, row.querySelector('.workout-details').hidden);
  if (action === 'copy' || action === 'edit') location.href = `${isCardio(workout) ? 'cardio' : 'index'}.html?${action}=${encodeURIComponent(workout.id)}`;
  if (action === 'delete') deleteHistoryWorkout(workout);
};
$('historySearch').oninput = () => { if (historyWorkouts) renderHistory(historyWorkouts); };

// ---- Training calendar ----------------------------------------------------
// The last 12 weeks as a grid of days, weeks running left to right from Monday, and how many weeks in a row reached the
// weekly goal from Settings. Days are the device's own: a workout at 11pm counts on that day wherever the server is.

const calendarWeeks = 12;
let historyWorkouts = null;  // null until they have loaded

// Workouts per day and per week (keyed by the week's Monday): strength and cardio alike, which both count toward the
// weekly goal. The days whose workouts were all cardio are kept too, as the calendar marks them apart.
function trainingByDate(workouts) {
  const days = new Map(), weeks = new Map(), cardioOnly = new Set();
  const lifted = new Set();
  workouts.forEach(workout => {
    const date = new Date(workout.createdAt);
    const day = calendarDayKey(date), week = calendarDayKey(startOfWeek(date));
    days.set(day, [...(days.get(day) || []), workout.name]);
    weeks.set(week, (weeks.get(week) || 0) + 1);
    if (!isCardio(workout)) lifted.add(day);
  });
  workouts.filter(isCardio).forEach(workout => {
    const day = calendarDayKey(new Date(workout.createdAt));
    if (!lifted.has(day)) cardioOnly.add(day);
  });
  return { days, weeks, cardioOnly };
}

// The current run of weeks at the goal, and the longest. This week counts once it reaches the goal; until then it is
// still in progress, so the run is counted from last week and nothing is lost yet.
function weeklyStreaks(weeks, goal, thisWeek) {
  const reached = monday => (weeks.get(calendarDayKey(monday)) || 0) >= goal;
  let current = reached(thisWeek) ? 1 : 0;
  for (let monday = addDays(thisWeek, -7); reached(monday); monday = addDays(monday, -7)) current += 1;
  const mondays = [...weeks.keys()].sort();
  let best = current, run = 0;
  if (mondays.length) {
    const [year, month, day] = mondays[0].split('-').map(Number);
    for (let monday = new Date(year, month - 1, day); monday <= thisWeek; monday = addDays(monday, 7)) {
      run = reached(monday) ? run + 1 : 0;
      best = Math.max(best, run);
    }
  }
  return { current, best };
}

function renderCalendar() {
  // Nothing is drawn before the workouts load: an unreachable server must not look like an empty week.
  if (!historyWorkouts) return;
  const goal = weeklyGoalFrom(getWorkoutSettings().weeklyGoal);
  const today = startOfDay(new Date());
  const thisWeek = startOfWeek(today);
  const first = addDays(thisWeek, -7 * (calendarWeeks - 1));
  const { days, weeks, cardioOnly } = trainingByDate(historyWorkouts);
  // The training days still to come, and today's if it has not been trained: planned, with the program's workout for each.
  const schedule = scheduleFrom(getWorkoutSettings());
  const planned = plannedDays(trainedDayKeys(historyWorkouts), 21, schedule);
  const plans = new Map(planned.filter(day => !day.trained).map(day => [day.key, day]));
  const thisWeekCount = weeks.get(calendarDayKey(thisWeek)) || 0;
  $('calendarSummary').textContent = weekGoalLine(thisWeekCount, goal);
  const { current, best } = weeklyStreaks(weeks, goal, thisWeek);
  $('streakSummary').textContent = current
    ? `${current}-week streak${best > current ? ` · best ${best}` : ''}`
    : best ? `No streak right now · best ${plural(best, 'week')}` : `Reach ${goal} in a week to start a streak`;

  // A header row of month names over the week they start in, then a row per weekday.
  const columns = Array.from({ length:calendarWeeks }, (entry, index) => addDays(first, 7 * index));
  const months = columns.map((monday, index) => {
    const startsMonth = index === 0 || addDays(monday, 6).getMonth() !== addDays(monday, -1).getMonth();
    const shown = index === 0 ? monday : addDays(monday, 6);
    return `<span class="calendar-month">${startsMonth ? escapeHTML(shown.toLocaleDateString(undefined, { month:'short' })) : ''}</span>`;
  }).join('');
  const weekdays = ['Mon', '', 'Wed', '', 'Fri', '', 'Sun'];
  const rows = weekdays.map((label, weekday) => `<span class="calendar-weekday">${label}</span>${columns.map(monday => {
    const date = addDays(monday, weekday);
    const names = days.get(calendarDayKey(date)) || [];
    const when = date.toLocaleDateString(undefined, { weekday:'short', month:'short', day:'numeric' });
    const key = calendarDayKey(date);
    const plan = plans.get(key);
    const planText = plan ? `planned${plan.entry ? `: ${plan.entry.label}` : ''}` : '';
    const description = names.length ? `${when}: ${names.join(', ')}` : `${when}: ${planText || 'rest'}`;
    const classes = ['calendar-day', names.length ? 'trained' : '', names.length > 1 ? 'many' : '', cardioOnly.has(key) ? 'cardio' : '', plan ? 'planned' : '',
      date > today ? 'future' : '', date.getTime() === today.getTime() ? 'today' : ''].filter(Boolean).join(' ');
    // A day to come that is planned is a button, so its workout can be read; the others are only squares.
    if (date > today && !plan) return `<span class="${classes}" data-date="${calendarDayKey(date)}" aria-hidden="true"></span>`;
    // Today is where the keyboard comes in; the arrow keys go from there (see moveCalendarFocus).
    return `<button class="${classes}" type="button" data-date="${calendarDayKey(date)}" tabindex="${date.getTime() === today.getTime() ? 0 : -1}"`
      + ` title="${escapeHTML(description)}" aria-label="${escapeHTML(description)}"></button>`;
  }).join('')}`).join('');
  $('trainingCalendar').innerHTML = `<span class="calendar-corner"></span>${months}${rows}`;
  renderComingUp(planned, schedule);
}

// The next few training days, written out: "Thu, Oct 9 · Pull". Nothing, and a pointer to Settings, until days are chosen.
function renderComingUp(planned, schedule) {
  $('comingUpBlock').hidden = !planned.length;
  $('scheduleHint').hidden = schedule.days.length > 0;
  $('comingUp').innerHTML = planned.slice(0, 6).map(day => {
    const when = day.today ? 'Today' : day.date.toLocaleDateString(undefined, { weekday:'short', month:'short', day:'numeric' });
    const what = day.trained ? 'Done' : day.entry ? day.entry.label : 'Training day';
    return `<li${day.trained ? ' class="done"' : ''}><strong>${escapeHTML(when)}</strong><span>${escapeHTML(what)}</span></li>`;
  }).join('');
}

// One day of the calendar is in the tab order at a time; the arrow keys move between them, a day up or down and a week
// left or right, as the grid is drawn.
const calendarMoves = { ArrowUp:-1, ArrowDown:1, ArrowLeft:-7, ArrowRight:7 };

function moveCalendarFocus(event) {
  const day = event.target.closest('button.calendar-day');
  if (!day || !(event.key in calendarMoves)) return;
  event.preventDefault();
  const [year, month, date] = day.dataset.date.split('-').map(Number);
  const target = calendarDayKey(addDays(new Date(year, month - 1, date), calendarMoves[event.key]));
  const next = $('trainingCalendar').querySelector(`button.calendar-day[data-date="${target}"]`);
  if (!next) return;
  day.tabIndex = -1;
  next.tabIndex = 0;
  next.focus();
}

function showHistory(workouts) {
  historyWorkouts = workouts;
  renderHistory(workouts);
  renderCalendar();
}

// A day's label is its tooltip, which only a mouse shows, so tapping a day, or reaching it from the keyboard, writes it
// under the calendar too.
function showCalendarDay(event) {
  const day = event.target.closest('.calendar-day[title]');
  if (day) $('calendarDetail').textContent = day.title;
}

// Tapping a day you trained (or Enter on it) goes to its workouts in the list, opened and marked for a moment. One that
// a search or Show older is keeping out of sight is brought back into it first.
function goToDay(key) {
  const rows = () => [...$('historyList').querySelectorAll(`.history-workout[data-date="${key}"]`)];
  let found = rows();
  if (!found.length || found.some(row => row.closest('.history-month[hidden]'))) {
    $('historySearch').value = '';
    showingAllMonths = true;
    renderHistory(historyWorkouts);
    found = rows();
  }
  if (!found.length) return;
  found.forEach(row => {
    showWorkoutDetails(row, true);
    row.classList.remove('picked');
    // Read once so the mark starts again on a second tap of the same day.
    void row.offsetWidth;
    row.classList.add('picked');
  });
  found[0].querySelector('.saved-workout-toggle').focus({ preventScroll:true });
  found[0].scrollIntoView({ behavior:'smooth', block:'center' });
}

$('trainingCalendar').onclick = event => {
  showCalendarDay(event);
  const day = event.target.closest('.calendar-day.trained');
  if (day) goToDay(day.dataset.date);
};
$('trainingCalendar').addEventListener('focusin', showCalendarDay);
$('trainingCalendar').onkeydown = moveCalendarFocus;

// A new weekly goal from Settings counts at once, and a new unit shows every weight in it.
window.addEventListener('settingschange', () => {
  if (historyWorkouts) renderHistory(historyWorkouts);
  renderCalendar();
});

window.localReady.then(flushPendingWorkouts).then(getSavedWorkouts).then(showHistory).catch(error => {
  $('historySummary').textContent = 'Unable to load workouts.';
  $('calendarSummary').textContent = 'The calendar shows once your workouts load.';
  console.error('Unable to load workout history.', error);
});
