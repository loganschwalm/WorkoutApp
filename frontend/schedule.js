// The training schedule: the days of the week the lifter trains, chosen in Settings (settings.schedule, see
// scheduleFrom in settings.js), and what is planned for each of them. A program is a queue of workouts that moves on when
// one is done, not when a date passes, so the schedule only says which days to train: the next scheduled day gets the
// next workout in the queue, the one after it the one after that, and a day that goes by untrained leaves the queue where
// it was. On the Tracker it nudges (today's workout, a missed day, the next one); on History it marks the planned days
// on the calendar and lists what is coming up. Loaded after settings.js and program-plan.js.

const weekdayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function scheduleStartOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function scheduleAddDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

// The day as the History calendar keys it: year-month-day by this device's calendar.
function scheduleDayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// The days of the workouts, as keys, for working out which days are done.
function trainedDayKeys(workouts) {
  return new Set(workouts.map(workout => scheduleDayKey(new Date(workout.createdAt))));
}

// The workouts of the program still to do, in order, as { week, day, label }: what is left of this block, then (when
// more are asked for than are left) the next block's, from the start. [] with no program, or one this build cannot read.
function programQueue(count) {
  const stored = readLocalState('program');
  const program = stored && stored.value;
  if (!program || typeof program !== 'object' || !findProgramDefinition(program.definition)) return [];
  try {
    const done = program.done && typeof program.done === 'object' ? program.done : {};
    const weeks = programWeeks(program).length, days = programDays(program).length;
    const queue = [];
    if (!weeks || !days) return queue;
    for (let pass = 0; queue.length < count && pass < 3; pass += 1) {
      for (let week = 0; week < weeks && queue.length < count; week += 1) {
        for (let day = 0; day < days && queue.length < count; day += 1) {
          // Only the block in progress has days done; the next one starts again from nothing.
          if (pass === 0 && done[dayKey(week, day)]) continue;
          queue.push({ week, day, label:dayLabel(program, week, day), current:pass === 0 });
        }
      }
    }
    return queue;
  } catch (error) {
    return [];
  }
}

// The training days from today on, for `span` days: { date, key, today, trained, entry }, where entry is the program's
// workout planned for that day (null on a day already trained, or with no program).
function plannedDays(trained, span, schedule = scheduleFrom(getWorkoutSettings())) {
  const today = scheduleStartOfDay(new Date());
  const queue = programQueue(span);
  let used = 0;
  const planned = [];
  for (let index = 0; index < span; index += 1) {
    const date = scheduleAddDays(today, index);
    if (!schedule.days.includes(date.getDay())) continue;
    const key = scheduleDayKey(date);
    const done = index === 0 && trained.has(key);
    planned.push({ date, key, today:index === 0, trained:done, entry:done ? null : queue[used++] || null });
  }
  return planned;
}

// "Thursday", "tomorrow" or "today", for a day coming up.
function dayWord(date) {
  const days = Math.round((scheduleStartOfDay(date) - scheduleStartOfDay(new Date())) / 86400000);
  return days === 0 ? 'today' : days === 1 ? 'tomorrow' : weekdayNames[date.getDay()];
}

// What to say on the Tracker, from the workouts saved: { text, start } or null when no days are chosen. `start` is the
// program's next workout when the lifter could begin it now (today is a day to train, or a missed one is still owed).
function scheduleNudge(workouts) {
  const schedule = scheduleFrom(getWorkoutSettings());
  if (!schedule.days.length) return null;
  const trained = trainedDayKeys(workouts);
  const today = scheduleStartOfDay(new Date());
  const planned = plannedDays(trained, 14, schedule);
  const todays = planned.find(day => day.today);
  const next = planned.find(day => !day.today);
  const queue = programQueue(1)[0] || null;
  const parts = [];
  // The latest training day before today, within a week, that was not trained and has not been made up for since. Only for
  // someone who was training just before it: a schedule only just chosen, or picked up again after months, has missed nothing.
  let missed = null;
  const lastTrained = workouts.reduce((latest, workout) => Math.max(latest, workout.createdAt), 0);
  const trainedBefore = date => workouts.some(workout => workout.createdAt < date.getTime() && workout.createdAt >= date.getTime() - 14 * 86400000);
  for (let back = 1; back <= 7 && !missed; back += 1) {
    const date = scheduleAddDays(today, -back);
    if (schedule.days.includes(date.getDay()) && !trained.has(scheduleDayKey(date)) && lastTrained < date.getTime() && trainedBefore(date)) missed = date;
  }
  const ahead = day => day ? `${dayWord(day.date)}${day.entry ? `, ${day.entry.label}` : ''}` : '';
  if (todays && !todays.trained) {
    if (missed) parts.push(`You missed ${weekdayNames[missed.getDay()]}.`);
    parts.push(`Today is a training day${todays.entry ? `: ${todays.entry.label}` : ''}.`);
    return { text:parts.join(' '), start:Boolean(queue) };
  }
  if (todays && todays.trained) return { text:`Done for today.${next ? ` Next up: ${ahead(next)}.` : ''}`, start:false };
  if (missed) {
    parts.push(`You missed ${weekdayNames[missed.getDay()]}'s workout.`);
    parts.push(next ? `Train today instead, or carry on ${ahead(next)}.` : 'Train today instead.');
    return { text:parts.join(' '), start:Boolean(queue) };
  }
  return { text:next ? `Rest day. Next up: ${ahead(next)}.` : 'Rest day.', start:false };
}

// ---- The Tracker's nudge ----------------------------------------------------

function renderScheduleNudge() {
  const card = document.getElementById('scheduleCard');
  if (!card) return;
  // Before the saved workouts have loaded there is no telling whether today has been trained.
  const loaded = typeof savedWorkoutsLoaded !== 'undefined' && savedWorkoutsLoaded;
  const nudge = loaded ? scheduleNudge([...savedWorkouts, ...readPendingWorkouts()]) : null;
  card.hidden = !nudge;
  if (!nudge) return;
  document.getElementById('scheduleText').textContent = nudge.text;
  const button = document.getElementById('scheduleStart');
  const next = typeof currentProgram !== 'undefined' && currentProgram ? nextProgramDay(currentProgram) : null;
  button.hidden = !(nudge.start && next);
  if (!button.hidden) button.textContent = `Start ${dayLabel(currentProgram, next.week, next.day)}`;
}

if (document.getElementById('scheduleCard')) {
  document.getElementById('scheduleStart').onclick = () => {
    const next = currentProgram ? nextProgramDay(currentProgram) : null;
    if (next) startWorkout(programWorkout(currentProgram, next.week, next.day));
  };
  document.getElementById('scheduleChange').onclick = () => document.getElementById('settingsButton').click();
  window.addEventListener('settingschange', renderScheduleNudge);
  window.addEventListener('syncchange', renderScheduleNudge);
  // The day turns over while the page is open on a phone left in a pocket.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) renderScheduleNudge(); });
}
