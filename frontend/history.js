// ---- Every saved workout ---------------------------------------------------
// One line a workout (tap it for its sets), in a month, in a year; each year and month is folded or open on its heading, with its
// workouts and time beside it. The latest year and month start open and the rest folded, so the list is not one long column. A
// search narrows the list to workouts whose name, exercises or notes have every word typed, with every year and month that has
// one open; a day picked on the calendar opens the year and month it is in.
// What was opened or closed by hand ("year:2026", "month:2026-10" to true or false), kept when the list is drawn again (a search,
// a deletion). A group with nothing said about it is open if it is the latest one.
const groupOpened = new Map();
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

// "12 workouts · 11 h 40 min", of a month or a year: the time only counts workouts that were timed.
function describeGroup(workouts) {
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
    + (canExportActivity(workout) ? '<button type="button" data-action="export">Download .tcx</button>' : '')
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
  // Newest first, as the server sends them, so each month's workouts arrive together, and the months of a year.
  const years = new Map();
  shown.forEach(workout => {
    const date = new Date(workout.createdAt);
    const months = years.get(date.getFullYear()) || new Map();
    months.set(monthKey(date), [...(months.get(monthKey(date)) || []), workout]);
    years.set(date.getFullYear(), months);
  });
  // A search opens everything it found; otherwise what was said by hand, and the latest year and month when nothing was.
  const isOpen = (key, latest) => words.length > 0 || (groupOpened.has(key) ? groupOpened.get(key) : latest);
  const group = (className, open, name, total, body) => `<details class="history-group ${className}"${open ? ' open' : ''}>`
    + `<summary class="history-group-summary"><h3 class="history-group-name">${escapeHTML(name)}</h3>`
    + `<span class="history-group-total">${escapeHTML(total)}</span></summary>${body}</details>`;
  const list = [...years].map(([year, months], yearIndex) => {
    const monthItems = [...months].map(([key, monthWorkouts], monthIndex) => {
      const name = new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1).toLocaleDateString(undefined, { month:'long' });
      return `<li class="history-month" data-month="${key}">`
        + group('history-month-group', isOpen(`month:${key}`, yearIndex === 0 && monthIndex === 0), name, describeGroup(monthWorkouts),
          `<ul class="history-month-list">${monthWorkouts.map(historyRow).join('')}</ul>`) + '</li>';
    }).join('');
    return `<li class="history-year" data-year="${year}">`
      + group('history-year-group', isOpen(`year:${year}`, yearIndex === 0), String(year), describeGroup([...months.values()].flat()),
        `<ul class="history-year-list">${monthItems}</ul>`) + '</li>';
  }).join('');
  $('historyList').innerHTML = shown.length ? list
    : `<li class="empty">${workouts.length ? 'No saved workouts match that search.' : 'No saved workouts yet.'}</li>`;
}

// A year or a month opened or closed by its heading. Drawn by hand, not left to the browser, so what was said is kept (groupOpened)
// when the list is drawn again; while a search has everything open, a heading only shows or hides, and nothing is kept.
function toggleHistoryGroup(summary) {
  const details = summary.parentElement;
  const item = details.parentElement;
  const open = !details.open;
  details.open = open;
  if (searchWords().length) return;
  groupOpened.set(item.dataset.month ? `month:${item.dataset.month}` : `year:${item.dataset.year}`, open);
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
  const heading = event.target.closest('.history-group-summary');
  if (heading) {
    event.preventDefault();
    toggleHistoryGroup(heading);
    return;
  }
  const button = event.target.closest('[data-action]');
  if (!button || !historyWorkouts) return;
  const action = button.dataset.action;
  const row = button.closest('.history-workout');
  const workout = historyWorkouts.find(item => String(item.id) === row.dataset.id);
  if (!workout) return;
  const menu = button.closest('.row-menu');
  if (menu) menu.open = false;
  if (action === 'view') showWorkoutDetails(row, row.querySelector('.workout-details').hidden);
  if (action === 'copy' || action === 'edit') location.href = `${isCardio(workout) ? 'cardio' : 'index'}.html?${action}=${encodeURIComponent(workout.id)}`;
  if (action === 'export') showHistoryFeedback(activitySavedMessage(saveActivityFile(workout)));
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

// The runs of weeks at the goal (weeklyStreaks, bestStreakBefore) are achievements.js's, which the Strength page uses too.

// Under the week's count: a run longer than any before it is said, with fireworks the first time it reaches each length (kept
// on this device, so a reload does not set them off again); otherwise a run this week has yet to keep says what it takes, while
// there are days enough left in the week to do it.
function renderStreakNote(weeks, goal, thisWeek, current, thisWeekCount) {
  const newBest = current >= 2 && current > bestStreakBefore(weeks, goal, thisWeek, current);
  const needed = goal - thisWeekCount;
  const daysLeft = 7 - ((new Date().getDay() + 6) % 7);
  const note = newBest ? `New best streak: ${plural(current, 'week')} in a row at your goal.`
    : current > 0 && needed > 0 && needed <= daysLeft ? `${plural(needed, 'more workout')} by Sunday keeps your ${current}-week streak going.` : '';
  $('streakNote').textContent = note;
  $('streakNote').hidden = !note;
  $('streakNote').classList.toggle('best', newBest);
  if (newBest && current > (Number(readLocal(localKey('streak-celebrated'))) || 0)) {
    writeLocal(localKey('streak-celebrated'), current);
    celebrate($('streakNote'), 'goal');
  }
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
  renderStreakNote(weeks, goal, thisWeek, current, thisWeekCount);

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
// a search is keeping out of the list, or a folded year or month is keeping out of sight, is brought back into it first.
function goToDay(key) {
  const rows = () => [...$('historyList').querySelectorAll(`.history-workout[data-date="${key}"]`)];
  let found = rows();
  if (!found.length || found.some(row => row.closest('details:not([open])'))) {
    $('historySearch').value = '';
    // A day is "2026-10-09" and its month "2026-10".
    groupOpened.set(`year:${key.slice(0, 4)}`, true);
    groupOpened.set(`month:${key.slice(0, 7)}`, true);
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
