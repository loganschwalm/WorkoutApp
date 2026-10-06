// Add to calendar, in the program card's ⋯ menu: the workouts still to do in the program as an .ics file (RFC 5545), one event
// for each, on the days of the training schedule (Settings) at its time, for any calendar app to import. A program is a queue
// that moves on when a workout is finished, not when a day passes (see schedule.js), so the file is that queue laid on the
// schedule as it stands: the next workout on the next training day, the one after it on the day after, and so on to the end
// of the block. It is made on the device from the same plan the card shows, so it works offline. Loaded after schedule.js.

const calendarEventMinutes = 60;

// A text value: backslash, semicolon, comma and line breaks are written as the format says.
function icsEscape(text) {
  return String(text).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r\n|\r|\n/g, '\\n');
}

// A line is at most 75 octets (not characters); the rest goes on lines of their own that start with a space.
function icsFold(line) {
  const encoder = new TextEncoder();
  const lines = [];
  let current = '', size = 0;
  for (const character of line) {
    const bytes = encoder.encode(character).length;
    if (size + bytes > (lines.length ? 74 : 75)) {
      lines.push(current);
      current = '';
      size = 0;
    }
    current += character;
    size += bytes;
  }
  lines.push(current);
  return lines.join('\r\n ');
}

// A time on the wall clock, with no zone ("floating"), so an event is at 5 pm wherever the calendar is opened.
function icsLocal(date) {
  const pad = number => String(number).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}T${pad(date.getHours())}${pad(date.getMinutes())}00`;
}

// The program's remaining workouts on the days to train: [{ date, entry, workout }], the day's workout as the card plans it
// (what it will be, going by the weights today: they move as workouts are done). [] with no days chosen or nothing left.
function programCalendarEvents(program, trained = new Set(), schedule = scheduleFrom(getWorkoutSettings())) {
  if (!schedule.days.length) return [];
  const blockSize = programWeeks(program).length * programDays(program).length;
  const span = 7 * Math.ceil(blockSize / schedule.days.length) + 7;
  const [hours, minutes] = schedule.time.split(':').map(Number);
  return plannedDays(trained, span, schedule).filter(day => day.entry && day.entry.current).map(day => ({
    date:new Date(day.date.getFullYear(), day.date.getMonth(), day.date.getDate(), hours, minutes),
    entry:day.entry,
    workout:programWorkout(program, day.entry.week, day.entry.day)
  }));
}

// The calendar file. An event's UID is its day of this run of the program, so importing again after a change moves the
// events rather than doubling them.
function programCalendarText(program, events, now = new Date()) {
  const name = programDefinition(program).name;
  const stamp = `${now.toISOString().slice(0, 19).replace(/[-:]/g, '')}Z`;
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Workout Tracker//Program//EN', 'CALSCALE:GREGORIAN', `X-WR-CALNAME:${icsEscape(name)}`];
  events.forEach(({ date, entry, workout }) => {
    const plan = workout.exercises.map(describeExercisePlan);
    const description = [...plan, ...plan.length ? [''] : [], 'Planned from your numbers today; the weights move as you train.'].join('\n');
    lines.push('BEGIN:VEVENT', `UID:${program.startedAt}-${program.cycle}-${entry.week}-${entry.day}@workout-tracker`, `DTSTAMP:${stamp}`,
      `DTSTART:${icsLocal(date)}`, `DTEND:${icsLocal(new Date(date.getTime() + calendarEventMinutes * 60000))}`,
      `SUMMARY:${icsEscape(`${name}: ${entry.label}`)}`, `DESCRIPTION:${icsEscape(description)}`, 'END:VEVENT');
  });
  lines.push('END:VCALENDAR');
  return `${lines.map(icsFold).join('\r\n')}\r\n`;
}

function exportProgramCalendar() {
  if (!currentProgram) return;
  const schedule = scheduleFrom(getWorkoutSettings());
  if (!schedule.days.length) {
    showFeedback('Choose the days you train in Settings (Training schedule) first: the workouts are put on those days.', 'error');
    return;
  }
  // Until the saved workouts have loaded there is no telling whether today has been trained.
  const loaded = typeof savedWorkoutsLoaded !== 'undefined' && savedWorkoutsLoaded;
  const events = programCalendarEvents(currentProgram, loaded ? trainedDayKeys([...savedSessions, ...readPendingWorkouts()]) : new Set(), schedule);
  if (!events.length) {
    showFeedback('Every workout of this program is done or skipped, so there is nothing to add to a calendar.', 'error');
    return;
  }
  const file = `${programDefinition(currentProgram).name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'program'}.ics`;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([programCalendarText(currentProgram, events)], { type:'text/calendar;charset=utf-8' }));
  link.download = file;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  const day = date => date.toLocaleDateString(undefined, { month:'short', day:'numeric' });
  showFeedback(`Downloaded ${file}: ${plural(events.length, 'workout')}, ${day(events[0].date)} to ${day(events[events.length - 1].date)}. Open it to add them to your calendar.`, 'success');
}

if (document.getElementById('calendarProgramBtn')) document.getElementById('calendarProgramBtn').onclick = exportProgramCalendar;
