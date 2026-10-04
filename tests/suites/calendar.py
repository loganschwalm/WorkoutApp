"""How the pages count days and weeks, on any day: the shared helpers (common.js), the History calendar's week and streak sums,
Cardio's and Progress's weeks, and the schedule's planned days and nudge, with the page's clock pinned to each of the seven
weekdays, to days either side of a clock change, to midnight and a second before it, and to a leap day, in time zones that
change their clocks, are half an hour out and a day apart. Nothing is seeded by date, so what day the suite runs on cannot matter.
What is expected is worked out apart from the helpers, from the browser's own formatting of dates in the time zone."""

import datetime
import json

INTERCEPT = False

UTC = datetime.timezone.utc

# (when, as an instant; the time zone the page is in)
CASES = [(datetime.datetime(2026, 3, day, 12, 0, tzinfo=UTC), 'America/Chicago') for day in range(2, 9)] + [
    (datetime.datetime(2026, 3, 8, 7, 30, tzinfo=UTC), 'America/Chicago'),       # 1:30 on the morning the clocks go forward
    (datetime.datetime(2026, 11, 1, 6, 30, tzinfo=UTC), 'America/Chicago'),      # 1:30, the first time, on the night they go back
    (datetime.datetime(2026, 11, 1, 7, 30, tzinfo=UTC), 'America/Chicago'),      # and the second
    (datetime.datetime(2026, 3, 29, 0, 30, tzinfo=UTC), 'Europe/London'),
    (datetime.datetime(2026, 4, 4, 13, 30, tzinfo=UTC), 'Pacific/Auckland'),
    (datetime.datetime(2026, 12, 31, 18, 30, tzinfo=UTC), 'Asia/Kolkata'),       # exactly midnight, and half an hour from UTC
    (datetime.datetime(2026, 12, 31, 18, 29, 59, tzinfo=UTC), 'Asia/Kolkata'),   # and a second before it, on New Year's Eve
    (datetime.datetime(2028, 2, 29, 0, 10, tzinfo=UTC), 'UTC'),                  # a leap day
    (datetime.datetime(2026, 10, 4, 5, 5, tzinfo=UTC), 'America/Los_Angeles'),   # the evening before, there
    (datetime.datetime(2026, 6, 15, 23, 59, tzinfo=UTC), 'Pacific/Kiritimati'),  # a day ahead of UTC
    (datetime.datetime(2026, 6, 15, 0, 30, tzinfo=UTC), 'Pacific/Pago_Pago'),    # and most of one behind
]

# What the browser itself says a date is in the page's time zone, to hold the helpers to.
ORACLE = """
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const shortNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const formatter = new Intl.DateTimeFormat('en-US', { timeZone: zone, weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const parts = date => Object.fromEntries(formatter.formatToParts(date).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
const key = date => { const p = parts(date); return `${p.year}-${p.month}-${p.day}`; };
const weekday = date => shortNames.indexOf(parts(date).weekday);
const midnight = date => { const p = parts(date); return p.hour === '00' && p.minute === '00'; };
const utc = k => { const [y, m, d] = k.split('-').map(Number); return Date.UTC(y, m - 1, d); };
const between = (a, b) => (utc(b) - utc(a)) / 86400000;
const problems = [];
const expect = (name, ok, detail) => { if (!ok) problems.push([name, detail === undefined ? null : detail]); };
"""

HISTORY = "(() => {" + ORACLE + """
const now = new Date();
const sod = startOfDay(now);
expect('the clock is the one pinned', Math.abs(now.getTime() - %(pinned)d) < 30000, [now.toISOString(), %(pinned)d]);
expect('a day is keyed as the browser writes its date', calendarDayKey(now) === key(now), [calendarDayKey(now), key(now)]);
expect('the start of a day is midnight of that day', midnight(sod) && key(sod) === key(now), [parts(sod), key(now)]);
const sow = startOfWeek(now);
expect('the start of a week is a Monday midnight, in the last seven days', weekday(sow) === 1 && midnight(sow) && between(key(sow), key(now)) >= 0 && between(key(sow), key(now)) <= 6,
  [parts(sow), key(sow), key(now)]);
for (let n = -21; n <= 21; n += 1) {
  const day = addDays(sod, n);
  expect(`${n} days on is a midnight, ${n} days on`, midnight(day) && between(key(sod), key(day)) === n, [n, parts(day), key(day)]);
}
for (let n = 0; n <= 6; n += 1) expect(`day ${n} of the week is in the week`, startOfWeek(addDays(sow, n)).getTime() === sow.getTime(), n);
expect('the next Monday starts the next week, and the Sunday before it the last', startOfWeek(addDays(sow, 7)).getTime() === addDays(sow, 7).getTime()
  && between(key(sow), key(addDays(sow, 7))) === 7 && startOfWeek(addDays(sow, -1)).getTime() === addDays(sow, -7).getTime());
for (let n = -3; n <= 3; n += 1) {
  const k = key(addDays(sod, n));
  expect(`a day's start comes back as its key (${n})`, calendarDayKey(new Date(dayStart(k))) === k && midnight(new Date(dayStart(k))), [k, calendarDayKey(new Date(dayStart(k)))]);
}

// The calendar's sums: a week runs from Monday's first minute to Sunday's last.
const at = (date, hours, minutes) => new Date(date.getFullYear(), date.getMonth(), date.getDate(), hours, minutes).getTime();
const workout = (time, name = 'W') => ({ createdAt: time, name });
const { weeks, days } = trainingByDate([workout(at(sow, 0, 30)), workout(at(addDays(sow, 6), 23, 30)), workout(at(addDays(sow, 7), 0, 10))]);
expect('Monday just after midnight and Sunday just before it are one week, and the next Monday the next',
  weeks.get(key(sow)) === 2 && weeks.get(key(addDays(sow, 7))) === 1, [...weeks]);
expect('and each is on its own day', days.get(key(sow)).length === 1 && days.get(key(addDays(sow, 6))).length === 1 && days.get(key(addDays(sow, 7))).length === 1);
const perWeek = (weeksAgo, count) => Array.from({ length: count }, (_, index) => workout(at(addDays(sow, -7 * weeksAgo + index), 12, 0)));
const streak = (...counts) => weeklyStreaks(trainingByDate(counts.flatMap((count, weeksAgo) => perWeek(weeksAgo, count))).weeks, 3, sow);
expect('three weeks at the goal, this one included, are a streak of three', JSON.stringify(streak(3, 3, 3)) === JSON.stringify({ current: 3, best: 3 }), streak(3, 3, 3));
expect('a week still in progress does not break it', JSON.stringify(streak(2, 3, 3)) === JSON.stringify({ current: 2, best: 2 }), streak(2, 3, 3));
expect('a week missed does', JSON.stringify(streak(3, 0, 3)) === JSON.stringify({ current: 1, best: 1 }), streak(3, 0, 3));

// The schedule: the days to come, and what the Tracker says.
const everyDay = { days: [0, 1, 2, 3, 4, 5, 6], time: '17:00' };
const planned = plannedDays(new Set(), 14, everyDay);
expect('every day is planned for a fortnight, from today', planned.length === 14 && planned.every((day, index) => day.key === key(addDays(sod, index))) && planned[0].today === true,
  planned.map(day => day.key));
const today = weekday(now);
const weekly = plannedDays(new Set(), 14, { days: [today], time: '17:00' });
expect('one training day a week is today and a week on', weekly.length === 2 && weekly[0].key === key(sod) && weekly[1].key === key(addDays(sod, 7)), weekly.map(day => day.key));
const done = plannedDays(new Set([key(now)]), 14, everyDay);
expect('a day already trained is marked, with no workout', done[0].trained === true && done[0].entry === null && done[1].trained === false);
expect('days are said as the schedule says them', dayWord(now) === 'today' && dayWord(addDays(sod, 1)) === 'tomorrow' && dayWord(addDays(sod, 2)) === weekdayNames[(today + 2) %% 7],
  [dayWord(addDays(sod, 2)), weekdayNames[(today + 2) %% 7]]);
const withSchedule = (daysChosen, trained) => {
  saveLocalState('settings', { ...getWorkoutSettings(), schedule: { days: daysChosen, time: '17:00' } });
  return scheduleNudge(trained).text;
};
expect('on a training day, the nudge says so', withSchedule([today], []) === 'Today is a training day.');
expect('the day before one, it says tomorrow', withSchedule([(today + 1) %% 7], []) === 'Rest day. Next up: tomorrow.');
expect('two days before one, it names it', withSchedule([(today + 2) %% 7], []) === `Rest day. Next up: ${weekdayNames[(today + 2) %% 7]}.`);
expect('once trained, it says done, and the next is a week on', withSchedule([today], [workout(now.getTime())]) === `Done for today. Next up: ${weekdayNames[today]}.`);
expect('a training day missed by someone who was training is said',
  withSchedule([(today + 5) %% 7], [workout(at(addDays(sod, -3), 12, 0))]) === `You missed ${weekdayNames[(today + 5) %% 7]}'s workout. Train today instead, or carry on ${weekdayNames[(today + 5) %% 7]}.`);
return JSON.stringify(problems);
})()"""

PROGRESS = "(() => {" + ORACLE + """
const monday = mondayOf(Date.now());
const now = new Date();
expect('Progress’s week starts on a Monday midnight, and is the same one the calendar counts', weekday(new Date(monday)) === 1 && midnight(new Date(monday)) && monday === startOfWeek(now).getTime(), [parts(new Date(monday))]);
expect('the week after is the next Monday, and the week before the last', weeksAfter(monday, 1) === addDays(new Date(monday), 7).getTime() && weekday(new Date(weeksAfter(monday, 1))) === 1
  && midnight(new Date(weeksAfter(monday, 1))) && weekday(new Date(weeksAfter(monday, -1))) === 1 && midnight(new Date(weeksAfter(monday, -1))), [parts(new Date(weeksAfter(monday, 1)))]);
expect('and a time in the middle of a week is in it', mondayOf(weeksAfter(monday, 1) - 1) === monday && mondayOf(weeksAfter(monday, 1)) === weeksAfter(monday, 1));
return JSON.stringify(problems);
})()"""

CARDIO = "(() => {" + ORACLE + """
const start = cardioWeekStart();
expect('Cardio’s week starts on a Monday midnight, the one the calendar counts', weekday(new Date(start)) === 1 && midnight(new Date(start)) && start === startOfWeek(new Date()).getTime(), [parts(new Date(start))]);
return JSON.stringify(problems);
})()"""


def run(t):
    cdp, check = t.cdp, t.check

    def examine(path, script, ready, when, zone):
        """The script run on a page (one of its own scripts having run, and the account's state having arrived) when the page's clock
        says it is `when` in `zone`: what it found wrong."""
        cdp.set_time_zone(zone)
        t.pin_clock(when)
        cdp.goto(path)
        cdp.wait(ready)
        cdp.ev('window.serverStateReady.then(() => { window.__ready = true; })')
        cdp.wait('window.__ready === true')
        return json.loads(cdp.ev(script))

    for when, zone in CASES:
        name = f'{when.strftime("%Y-%m-%d %H:%M:%S")}Z in {zone}'
        pinned = int(when.timestamp() * 1000)
        problems = examine('/history.html', HISTORY % {'pinned': pinned}, "typeof trainingByDate === 'function' && typeof plannedDays === 'function'", when, zone)
        check(f'History, Tracker and the schedule count days and weeks right: {name}', not problems, problems[:3])
    print('P   Progress and Cardio count the week the same way')
    for when, zone in CASES[::3]:
        name = f'{when.strftime("%Y-%m-%d %H:%M:%S")}Z in {zone}'
        problems = examine('/progress.html', PROGRESS, "typeof mondayOf === 'function'", when, zone)
        check(f'Progress: {name}', not problems, problems[:3])
        problems = examine('/cardio.html', CARDIO, "typeof cardioWeekStart === 'function'", when, zone)
        check(f'Cardio: {name}', not problems, problems[:3])
    cdp.set_time_zone(None)
    cdp.unpin_clock()
