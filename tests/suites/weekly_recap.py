"""The week in review: last week's recap worked out from the history (its totals, records, achievements, streak and how it
compares), and the Tracker's Last week card that shows it, put away by Done until the next week."""

INTERCEPT = False

DAY_MS = 86400000


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    ex = t.ex

    def account(name):
        cookie = api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    def ev(expression):
        return cdp.ev(expression)

    # ------------------------------------------------------------------ E the recap, from a history
    print('E   a week is worked out from the history: its totals, records, achievements and streak')
    t.open_tracker()
    ev("""window.R = {
      // Noon on a day counted from Monday 12 January 2026, so every session is in the week it is meant for.
      at: (day, hour = 12) => new Date(2026, 0, 12 + day, hour).getTime(),
      lift: (at, name, sets, extra = {}) => ({ name: 'Lift', createdAt: at, unit: 'lbs', duration: 1800, ...extra,
        exercises: [{ name, weight: sets[0][0], reps: sets[0][1], sets: sets.map(([weight, reps]) => ({ weight, reps })) }] }),
      run: (at, miles, extra = {}) => ({ kind: 'cardio', name: 'Run', createdAt: at, exercises: [], duration: 1500, cardio: { activity: 'run', distance: miles, distanceUnit: 'mi' }, ...extra }),
      monday: new Date(2026, 0, 12),
      options: { unit: 'lbs', distanceUnit: 'mi', goal: 3 }
    };
    // Three weeks of three at the goal before it, then the week: four sessions, one of them a run, one still in the queue as well.
    window.history3 = [-21, -20, -19, -14, -13, -12, -7, -6, -5].map(day => R.lift(R.at(day), 'Bench Press', [[100 + day + 21, 5]]));
    window.week = [R.lift(R.at(0), 'Bench Press', [[130, 5], [130, 5]], { clientId: 'twice' }), R.lift(R.at(2), 'Squat', [[225, 3]]),
      R.run(R.at(4), 3), R.lift(R.at(6, 20), 'Bench Press', [[135, 5]])];
    true""")
    recap = ev("weekRecapOf([...history3, ...week, { ...week[0] }, R.lift(R.at(7, 0) + 30000, 'Curl', [[20, 10]]), R.lift(R.at(-1, 23), 'Curl', [[20, 10]])], R.monday, R.options)")
    check('a workout uploaded and still in the queue counts once, and a session just past midnight on either side is not in the week',
          recap['sessions'] == 4 and recap['strength'] == 3 and recap['cardio'] == 1, [recap['sessions'], recap['strength'], recap['cardio']])
    check('its time, sets, volume and distance are the week’s',
          recap['seconds'] == 3 * 1800 + 1500 and recap['sets'] == 4 and recap['volume'] == 130 * 5 * 2 + 225 * 3 + 135 * 5 and recap['distance'] == 3,
          [recap['seconds'], recap['sets'], recap['volume'], recap['distance']])
    told = ev("""(() => { const all = uniqueSessions([...history3, ...week]).sort((a, b) => a.createdAt - b.createdAt); let told = 0;
      all.forEach((workout, index) => { if (workout.createdAt < R.monday.getTime()) return; const earlier = all.slice(0, index);
        told += isCardio(workout) ? newCardioRecords(workout, earlier.filter(isCardio)).length : newRecords(workout, bestsOf(earlier.filter(other => !isCardio(other)))).length; });
      return told; })()""")
    check('the records counted are those each of the week’s workouts was told', recap['recordCount'] == told and told >= 2, [recap['recordCount'], told])
    check('and each exercise is listed once, at its latest', len(recap['records']) == len({line.split(':')[0] for line in recap['records']}) and recap['records'][0].startswith('Bench Press: 135 lbs'),
          recap['records'])
    # The tenth workout is the Sunday night one, the week before's; the week itself earned the plates and the streak.
    check('the achievements are those earned in the week: two plates on the squat, one on the bench, a 4-week streak',
          {'squat:2', 'bench:1', 'streak:4'} <= {item['id'] for item in recap['earned']} and 'workouts:10' not in {item['id'] for item in recap['earned']} and all(item['at'] >= ev('R.monday.getTime()') for item in recap['earned']),
          [item['id'] for item in recap['earned']])
    check('four weeks running at the goal, this one included, is a 4-week streak', recap['reached'] is True and recap['streak'] == 4, [recap['reached'], recap['streak']])
    # The Sunday night session just before the week is the week before's.
    check('the week before, to compare with: its workouts and its volume', recap['previous']['sessions'] == 4 and recap['previous']['volume'] == (114 + 115 + 116) * 5 + 200,
          recap['previous'])
    check('said as a person would: one more workout, and how much more volume',
          ev("recapComparison(weekRecapOf([...history3, ...week], R.monday, R.options))") == '1 workout more than the week before, and 54% more volume.',
          ev("recapComparison(weekRecapOf([...history3, ...week], R.monday, R.options))"))
    check('the biggest week of lifting yet, against three weeks of it', recap['biggest'] is True)
    check('but not against two, so a first week is not called one', ev("weekRecapOf([...history3.slice(3), ...week], R.monday, R.options).biggest") is False)
    missed = ev("weekRecapOf([...history3, R.lift(R.at(1), 'Curl', [[20, 10]])], R.monday, R.options)")
    check('a week short of the goal has no streak to claim, however long the run before it', missed['reached'] is False and missed['streak'] == 0, [missed['reached'], missed['streak']])
    check('and says so looking forward', ev("recapHeadline(weekRecapOf([...history3, R.lift(R.at(1), 'Curl', [[20, 10]])], R.monday, R.options))") == '1 workout. A new streak can start this week.')
    check('a week reached is said with its streak', ev("recapHeadline(weekRecapOf([...history3, ...week], R.monday, R.options))") == '4 workouts, your goal of 3 reached: a 4-week streak.')
    check('a week with nothing in it has no recap', ev("weekRecapOf(history3, R.monday, R.options)") is None)

    # ------------------------------------------------------------------ U the Tracker's card
    print('U   the Tracker has a Last week card, until Done, back the week after')
    lifter = account('recapper')
    last_monday = ev("addDays(startOfWeek(new Date()), -7).getTime()")
    for n in range(3):
        api('POST', '/api/workouts', {'name': 'Push Day', 'notes': '', 'createdAt': last_monday + n * DAY_MS + 12 * 3600000, 'duration': 2400,
                                      'exercises': [ex('Bench Press', 135 + 5 * n, 5, [(5, 135 + 5 * n)] * 3)]}, lifter)
    t.set_cookie(lifter)
    t.open_tracker()
    cdp.wait("!document.getElementById('recapCard').hidden", timeout=10)
    shown = ev("""({ title: document.getElementById('recapTitle').textContent, range: document.getElementById('recapRange').textContent,
        headline: document.getElementById('recapHeadline').textContent, stats: [...document.querySelectorAll('#recapStats li')].map(li => li.textContent),
        achievements: [...document.querySelectorAll('#recapAchievementList li strong')].map(e => e.textContent),
        records: document.getElementById('recapRecords').hidden ? '' : document.getElementById('recapRecordsTitle').textContent,
        recordsFolded: !document.getElementById('recapRecords').open })""")
    day = lambda offset: ev(f"new Date({last_monday} + {offset} * 86400000).toLocaleDateString(undefined, {{ month: 'short', day: 'numeric' }})")
    check('it shows last week, Monday to Sunday', shown['title'] == 'Last week' and shown['range'] == f'{day(0)} – {day(6)}', shown['range'])
    check('saying its workouts against the goal', shown['headline'] == '3 workouts, your goal of 3 reached.', shown['headline'])
    two_hours = ev('formatDuration(7200)')
    check('its totals on a line: workouts, time, sets and volume', shown['stats'][:4] == ['3Workouts', f'{two_hours}Time', '9Sets', '6,300 lbsVolume'], shown['stats'])
    check('the achievements it earned, to share', 'First workout' in shown['achievements']
          and ev("document.querySelectorAll('#recapAchievementList [data-share]').length") == len(shown['achievements']), shown['achievements'])
    check('and its records, folded under their count', shown['records'] == '2 personal records' and shown['recordsFolded'] is True, shown['records'])
    check('it starts as a line saying how the week went, under the heading that opens it', ev("document.getElementById('recapBody').hidden") is True
          and ev("document.getElementById('recapLine').textContent").endswith(shown['headline']) and ev("document.getElementById('recapToggle').getAttribute('aria-expanded')") == 'false')
    tall = """[...document.querySelectorAll('#recapCard button, #recapCard summary')].filter(e => e.offsetParent).every(e => { const box = e.getBoundingClientRect();
        return box.height >= 44 && box.width >= 44; })"""
    check('its heading and Dismiss are 44px to press', ev(tall) is True)
    ev("document.getElementById('recapToggle').click()")
    check('pressing the heading opens the week, in place of the line', ev("document.getElementById('recapBody').hidden") is False and ev("document.getElementById('recapLine').hidden") is True)
    check('nothing to press is under 44px', ev(tall) is True)
    ev("document.getElementById('recapToggle').click()")
    check('and pressing it again puts the line back', ev("document.getElementById('recapBody').hidden") is True and ev("document.getElementById('recapLine').hidden") is False)
    check('nothing is shown before the whole history is in hand',
          ev("(() => { savedWorkoutsLoaded = false; renderRecap(); const hidden = document.getElementById('recapCard').hidden; savedWorkoutsLoaded = true; renderRecap(); return hidden; })()") is True)
    t.start(0)
    cdp.pause(0.4)
    check('a workout puts it away with the rest of the Tracker', ev("getComputedStyle(document.getElementById('recapCard')).display") == 'none')
    t.end_workout()
    cdp.pause(0.3)
    check('and it is back after', ev("getComputedStyle(document.getElementById('recapCard')).display") != 'none')
    ev("document.getElementById('recapDone').click()")
    cdp.pause(0.2)
    check('Dismiss puts it away, and the keyboard carries on from the templates', ev("document.getElementById('recapCard').hidden") is True
          and ev('document.activeElement.id') == 'templatesToggle', ev('document.activeElement.id'))
    t.open_tracker()
    check('for the rest of the week', ev("document.getElementById('recapCard').hidden") is True)
    ev("writeLocal(localKey('recap-dismissed'), calendarDayKey(addDays(startOfWeek(new Date()), -14)))")
    t.open_tracker()
    cdp.wait("!document.getElementById('recapCard').hidden", timeout=10)
    check('and the next week’s comes by itself', ev("document.getElementById('recapCard').hidden") is False)

    quiet = account('quietweek')
    api('POST', '/api/workouts', {'name': 'Old', 'notes': '', 'createdAt': last_monday - 10 * DAY_MS, 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, quiet)
    t.set_cookie(quiet)
    t.open_tracker()
    cdp.pause(0.5)
    check('a week with nothing in it has no card, rather than a reminder of it', ev("document.getElementById('recapCard').hidden") is True)
    t.set_cookie(t.token)
