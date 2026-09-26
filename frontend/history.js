function renderHistory(workouts) {
  $('historySummary').textContent = `${workouts.length} saved workout${workouts.length === 1 ? '' : 's'}`;
  $('historyList').innerHTML = workouts.length ? workouts.map(workout => `<li class="saved-workout history-workout"><div class="saved-workout-summary"><div><strong>${escapeHTML(workout.name)}</strong><span>${new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })}${workoutProgramLabel(workout) ? ` &middot; ${escapeHTML(workoutProgramLabel(workout))}` : ''}</span></div><a class="button-link primary" href="index.html?start=${encodeURIComponent(workout.id)}">Start workout</a></div><div class="workout-details">${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${inUnit(workout).exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(describeSavedExercise(item))}</span></li>`).join('')}</ul></div></li>`).join('') : '<li class="empty">No saved workouts yet.</li>';
}

// ---- Training calendar ----------------------------------------------------
// The last 12 weeks as a grid of days, weeks running left to right from Monday, and how many weeks in a row reached the
// weekly goal from Settings. Days are the device's own: a workout at 11pm counts on that day wherever the server is.

const calendarWeeks = 12;
let historyWorkouts = null;  // null until they have loaded

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

// Monday of the week a date is in.
function startOfWeek(date) {
  return addDays(startOfDay(date), -((date.getDay() + 6) % 7));
}

function calendarDayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// Workouts per day and per week (keyed by the week's Monday).
function trainingByDate(workouts) {
  const days = new Map(), weeks = new Map();
  workouts.forEach(workout => {
    const date = new Date(workout.createdAt);
    const day = calendarDayKey(date), week = calendarDayKey(startOfWeek(date));
    days.set(day, [...(days.get(day) || []), workout.name]);
    weeks.set(week, (weeks.get(week) || 0) + 1);
  });
  return { days, weeks };
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

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

function renderCalendar() {
  // Nothing is drawn before the workouts load: an unreachable server must not look like an empty week.
  if (!historyWorkouts) return;
  const goal = weeklyGoalFrom(getWorkoutSettings().weeklyGoal);
  const today = startOfDay(new Date());
  const thisWeek = startOfWeek(today);
  const first = addDays(thisWeek, -7 * (calendarWeeks - 1));
  const { days, weeks } = trainingByDate(historyWorkouts);
  const thisWeekCount = weeks.get(calendarDayKey(thisWeek)) || 0;
  $('calendarSummary').textContent = thisWeekCount >= goal
    ? `This week: ${plural(thisWeekCount, 'workout')} · goal of ${goal} reached`
    : `This week: ${thisWeekCount} of ${plural(goal, 'workout')}`;
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
    const description = names.length ? `${when}: ${names.join(', ')}` : `${when}: rest`;
    const classes = ['calendar-day', names.length ? 'trained' : '', names.length > 1 ? 'many' : '', date > today ? 'future' : '', date.getTime() === today.getTime() ? 'today' : ''].filter(Boolean).join(' ');
    return `<span class="${classes}" data-date="${calendarDayKey(date)}"${date > today ? ' aria-hidden="true"' : ` title="${escapeHTML(description)}" aria-label="${escapeHTML(description)}"`}></span>`;
  }).join('')}`).join('');
  $('trainingCalendar').innerHTML = `<span class="calendar-corner"></span>${months}${rows}`;
}

function showHistory(workouts) {
  historyWorkouts = workouts;
  renderHistory(workouts);
  renderCalendar();
}

// A day's label is its tooltip, which only a mouse shows, so tapping a day writes it under the calendar too.
$('trainingCalendar').onclick = event => {
  const day = event.target.closest('.calendar-day[title]');
  if (day) $('calendarDetail').textContent = day.title;
};

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
