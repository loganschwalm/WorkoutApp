"""Achievements, streaks and encouragement: the achievements worked out from the history, what a finished workout or session
earned, the Progress row of them, History's streak lines, and the lines picked to cheer."""

import time

INTERCEPT = False

DAY_MS = 86400000


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    text, ex = t.text, t.ex

    def account(name):
        cookie = api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    def ev(expression):
        return cdp.ev(expression)

    now = int(time.time() * 1000)

    # ------------------------------------------------------------------ A the catalogue, worked out from a history
    print('A   achievements are worked out from the workouts, each earned by the one that first got there')
    cdp.goto('/progress.html')
    cdp.wait("typeof achievementsOf === 'function' && typeof newRecords === 'function'")
    cdp.pause(0.4)
    # Helpers in the page: a strength workout of one exercise, a cardio session, and the ids earned from a list of them.
    ev("""window.T = {
      lift: (at, name, sets, extra = {}) => ({ name: 'Lift', createdAt: at, unit: 'lbs', ...extra,
        exercises: [{ name, weight: sets[0][0], reps: sets[0][1], sets: sets.map(([weight, reps]) => ({ weight, reps })) }] }),
      cardio: (at, activity, duration, cardio = {}, extra = {}) => ({ kind: 'cardio', name: 'Session', createdAt: at, exercises: [], duration, ...extra,
        cardio: { activity, ...cardio } }),
      ids: (list, options = { unit: 'lbs', distanceUnit: 'mi', goal: 3 }) => achievementsOf(list, options).earned.map(item => item.id),
      day: n => new Date(2026, 0, 5 + n, 12).getTime()
    }; true""")
    check('no workouts earn nothing', ev("T.ids([])") == [])
    tenth = ev("(() => { const list = Array.from({ length: 10 }, (_, n) => T.lift(T.day(n * 3), 'Curl', [[20, 10]])); window.ten = list;"
               "return achievementsOf(list, { unit: 'lbs', distanceUnit: 'mi', goal: 3 }).earned.filter(item => item.family === 'workouts'); })()")
    check('the first workout and the tenth are milestones, each earned on the day it was done',
          [item['name'] for item in tenth] == ['First workout', '10 workouts'] and tenth[1]['at'] == ev('ten[9].createdAt'), tenth)
    check('a workout uploaded and still in the queue counts once',
          ev("(() => { const one = { ...T.lift(T.day(0), 'Curl', [[20, 10]]), clientId: 'same' }; return achievementsOf([one, { ...one, id: 7 }, one]).families.find(f => f.id === 'workouts').value; })()") == 1)

    plates = ev("""(() => {
      const plate = (name, weight, reps, unit = 'lbs') => achievementsOf([T.lift(T.day(0), name, [[weight, reps]], { unit })], { unit: 'lbs', distanceUnit: 'mi', goal: 3 })
        .families.find(f => ['bench', 'squat', 'deadlift'].includes(f.id) && f.value > 0)?.value ?? 0;
      return { twoLbs: plate('Bench Press', 225, 1), justShort: plate('Bench Press', 220, 3), twoKg: plate('Bench Press', 100, 1, 'kg'),
        fourSquat: plate('Back Squat', 405, 1), dumbbell: plate('Dumbbell Bench Press', 300, 5), noReps: plate('Deadlift', 405, 0), sumo: plate('Sumo Deadlift', 315, 1) };
    })()""")
    check('plates a side count in the unit the set was logged in: 225 lbs is two, and so is 100 kg; 220 lbs is one',
          plates['twoLbs'] == 2 and plates['twoKg'] == 2 and plates['justShort'] == 1, plates)
    check('a squat of 405 is four, a sumo deadlift of 315 is three', plates['fourSquat'] == 4 and plates['sumo'] == 3, plates)
    check('a dumbbell bench is not the bench, and a set of no reps lifts nothing', plates['dumbbell'] == 0 and plates['noReps'] == 0, plates)
    jumped = ev("T.ids([T.lift(T.day(0), 'Deadlift', [[315, 1]])]).filter(id => id.startsWith('deadlift:'))")
    check('one heavy set earns every tier it passes at once', jumped == ['deadlift:1', 'deadlift:2', 'deadlift:3'], jumped)

    # Records are counted as each workout was told them: newRecords and the cardio records against the bests before it.
    agreement = ev("""(() => {
      const list = [T.lift(T.day(0), 'Bench Press', [[100, 5]]), T.lift(T.day(1), 'Bench Press', [[105, 5], [110, 3]]), T.lift(T.day(2), 'Bench Press', [[105, 5]]),
        T.lift(T.day(3), 'Bench Press', [[50, 8]], { unit: 'kg' }), T.lift(T.day(4), 'Squat', [[200, 5]]), T.lift(T.day(5), 'Squat', [[200, 8]]),
        T.cardio(T.day(6), 'run', 1800, { distance: 3, distanceUnit: 'mi' }), T.cardio(T.day(7), 'run', 2400, { distance: 4, distanceUnit: 'mi' }),
        T.cardio(T.day(8), 'run', 1500, { distance: 3.5, distanceUnit: 'mi' })];
      let told = 0;
      list.forEach((workout, index) => {
        const earlier = list.slice(0, index);
        told += isCardio(workout) ? newCardioRecords(workout, earlier.filter(isCardio)).length
          : newRecords(workout, bestsOf(earlier.filter(other => !isCardio(other)))).length;
      });
      return { told, counted: achievementsOf(list).families.find(f => f.id === 'records').value };
    })()""")
    check('the records counted are the records each workout was told, strength and cardio', agreement['told'] == agreement['counted'] and agreement['told'] >= 4, agreement)

    streak = ev("""(() => {
      // Three workouts in each of two weeks running, the goal three a week: a 2-week streak, earned by the sixth.
      const monday = new Date(2026, 0, 5).getTime();
      const list = [0, 1, 2, 7, 8, 9].map(n => T.lift(monday + n * 86400000 + 43200000, 'Curl', [[20, 10]]));
      const got = achievementsOf(list, { unit: 'lbs', distanceUnit: 'mi', goal: 3 }).earned.find(item => item.id === 'streak:2');
      const short = achievementsOf(list.slice(0, 5), { unit: 'lbs', distanceUnit: 'mi', goal: 3 }).earned.some(item => item.family === 'streak');
      const gap = achievementsOf([...list.slice(0, 3), ...list.slice(3).map(w => ({ ...w, createdAt: w.createdAt + 7 * 86400000 }))], { unit: 'lbs', distanceUnit: 'mi', goal: 3 })
        .earned.some(item => item.family === 'streak');
      return { at: got && got.at, sixth: list[5].createdAt, short, gap };
    })()""")
    check('two weeks running at the goal is a 2-week streak, earned by the workout that met it the second time', streak['at'] == streak['sixth'], streak)
    check('not before then, and not with a week missed between', streak['short'] is False and streak['gap'] is False, streak)
    excused = ev("""(() => {
      // Three workouts in the first and the third week, none in the second: with that week on a break, two weeks at the goal in a row.
      const monday = new Date(2026, 0, 5);
      const list = [0, 1, 2, 14, 15, 16].map(n => T.lift(monday.getTime() + n * 86400000 + 43200000, 'Curl', [[20, 10]]));
      const options = breaks => ({ unit: 'lbs', distanceUnit: 'mi', goal: 3, breaks });
      const earned = breaks => achievementsOf(list, options(breaks)).earned.some(item => item.id === 'streak:2');
      const weeks = weekCountsOf(list), thisWeek = new Date(2026, 0, 19);
      return { whole: earned([{ from: '2026-01-12', to: '2026-01-18' }]), oneDay: earned([{ from: '2026-01-18', to: '2026-01-18' }]),
        none: earned([]), elsewhere: earned([{ from: '2026-02-02', to: '2026-02-03' }]),
        run: weeklyStreaks(weeks, 3, thisWeek, [{ from: '2026-01-12', to: '2026-01-14' }]), bare: weeklyStreaks(weeks, 3, thisWeek),
        before: bestStreakBefore(weeks, 3, thisWeek, 2, [{ from: '2026-01-12', to: '2026-01-14' }]) };
    })()""")
    check('a week on a break is passed over: two weeks at the goal either side of one are a 2-week streak', excused['whole'] is True and excused['run'] == {'current': 2, 'best': 2}, excused)
    check('one day of the week is enough', excused['oneDay'] is True, excused)
    check('without the break, or with one in another week, they are not', excused['none'] is False and excused['elsewhere'] is False and excused['bare'] == {'current': 1, 'best': 1}, excused)
    check('and the run that a new best is measured against starts where the current one does', excused['before'] == 0, excused)
    check('five days trained in one week is a big week; five workouts on two days is not',
          'bigWeek:5' in ev("T.ids([0, 1, 2, 3, 4].map(n => T.lift(T.day(n), 'Curl', [[20, 10]])))")
          and 'bigWeek:5' not in ev("T.ids([0, 0, 0, 1, 1].map(n => T.lift(T.day(n) + n, 'Curl', [[20, 10]])))"))
    check('a workout after two weeks off is a comeback; one after thirteen days is not',
          'comeback:1' in ev("T.ids([T.lift(T.day(0), 'Curl', [[20, 10]]), T.lift(T.day(14), 'Curl', [[20, 10]])])")
          and 'comeback:1' not in ev("T.ids([T.lift(T.day(0), 'Curl', [[20, 10]]), T.lift(T.day(13), 'Curl', [[20, 10]])])"))
    volume = ev("""(() => { const list = [T.lift(T.day(0), 'Squat', [[240, 10], [240, 10], [240, 10], [240, 10], [240, 10]])];
      return { lbs: T.ids(list).includes('volume:10000'), kg: T.ids(list, { unit: 'kg', distanceUnit: 'km', goal: 3 }).includes('volume:5000'),
        kgShort: T.ids(list.map(w => ({ ...w, unit: 'kg', exercises: w.exercises.map(e => ({ ...e, sets: e.sets.map(s => ({ ...s, weight: 40 })) })) })), { unit: 'kg', distanceUnit: 'km', goal: 3 }).includes('volume:5000') }; })()""")
    check('10,000 lbs lifted, and the kilogram tiers for kilograms: 12,000 lbs is past 5,000 kg; 2,000 kg is not', volume == {'lbs': True, 'kg': True, 'kgShort': False}, volume)
    distance = ev("""(() => ({ miles: T.ids([T.cardio(T.day(0), 'run', 3600, { distance: 6, distanceUnit: 'mi' }), T.cardio(T.day(1), 'walk', 3600, { distance: 4, distanceUnit: 'mi' })]).includes('distance:10'),
      rowed: T.ids([T.cardio(T.day(0), 'rower', 3600, { distance: 20000, distanceUnit: 'm' })]).includes('distance:10'),
      km: T.ids([T.cardio(T.day(0), 'run', 3600, { distance: 16.2, distanceUnit: 'km' })]).includes('distance:10') }))()""")
    check('ten miles of walking and running is distance covered; a rower’s metres are not; 16.2 km is past 10 miles', distance == {'miles': True, 'rowed': False, 'km': True}, distance)
    check('a workout deleted takes back what it earned', ev("T.ids(ten).includes('workouts:10') && !T.ids(ten.slice(1)).includes('workouts:10')") is True)
    earned_by = ev("achievementsEarnedBy(ten.slice(0, 9), ten[9], { unit: 'lbs', distanceUnit: 'mi', goal: 3 }).map(item => item.id)")
    check('what one workout earned is what the history after it has and the history before it had not', earned_by == ['workouts:10'], earned_by)
    check('with the history not in hand, a finished workout earns nothing', ev("finishRewards(null, ten[0]).earned.length") == 0)

    # The lines: one of the kind asked for, never the same twice in a row, and pinned when the random source is.
    lines = ev("Array.from({ length: 30 }, () => splashLine('idle'))")
    check('an encouraging line is one of its kind, never the same twice running', all(line in ev("splashLines.idle") for line in lines)
          and all(a != b for a, b in zip(lines, lines[1:])), lines[:4])
    check('and the random source can be pinned', ev("sessionStorage.clear(); splashLine('record', () => 0)") == ev("splashLines.record[0]"))
    check('a finished workout is cheered for the biggest thing it did', ev("""[rewardSplashKind({ earned: [1], weekReached: true }, ['r']), rewardSplashKind({ earned: [], weekReached: true }, ['r']),
        rewardSplashKind({ earned: [], weekReached: true }, []), rewardSplashKind({ earned: [], weekReached: false }, [])]""") == ['achievement', 'record', 'streak', 'finish'])

    # ------------------------------------------------------------------ S the Strength page's summary
    print('S   a finished workout says what it earned, with a line to cheer it and fireworks for an achievement')
    lifter = account('milestone')
    for n in range(9):
        api('POST', '/api/workouts', {'name': 'Old', 'notes': '', 'createdAt': now - (60 - n * 5) * DAY_MS, 'clientId': f'old-{n}',
                                      'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, lifter)
    t.set_cookie(lifter)
    t.open_tracker()
    check('between workouts the Tracker has a line to start on', text('splashLine') in ev("splashLines.idle") and ev("!document.getElementById('splashLine').hidden") is True, text('splashLine'))
    t.start(0)
    cdp.pause(0.4)
    check('which goes while a workout is on', ev("getComputedStyle(document.getElementById('splashLine')).display") == 'none')
    t.log_set(8)
    cdp.pause(0.3)
    t.finish_all()
    cdp.wait("!document.getElementById('workoutSummary').hidden", timeout=10)
    cdp.pause(0.3)
    earned = ev("[...document.querySelectorAll('#summaryAchievementList li strong')].map(e => e.textContent)")
    check('the tenth workout is "10 workouts", listed under Achievements unlocked', ev("!document.getElementById('summaryAchievements').hidden") is True
          and '10 workouts' in earned, earned)
    check('with fireworks the size of an achievement', ev("document.querySelector('.firework')?.dataset.size") == 'achievement')
    check('and a line for it', text('summarySplash') in ev("splashLines.achievement"), text('summarySplash'))
    check('a summary shown without the history (not loaded yet) claims nothing', ev("""(() => { showWorkoutSummary({ name: 'X', createdAt: Date.now(), exercises: [] }, [], { history: null });
        return document.getElementById('summaryAchievements').hidden; })()""") is True)
    check('and summaryBefore holds no history until the saved workouts have loaded',
          ev("(() => { const was = savedWorkoutsLoaded; savedWorkoutsLoaded = false; const got = summaryBefore({ name: 'X', createdAt: Date.now(), exercises: [] }).history; savedWorkoutsLoaded = was; return got; })()") is None)

    # ------------------------------------------------------------------ C the Cardio page's summary, counted with strength
    print('C   a cardio session counts with the strength workouts')
    runner = account('mixed')
    for n in range(9):
        api('POST', '/api/workouts', {'name': 'Old', 'notes': '', 'createdAt': now - (60 - n * 5) * DAY_MS, 'clientId': f'mixed-{n}',
                                      'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, runner)
    t.set_cookie(runner)
    cdp.goto('/cardio.html')
    cdp.wait('cardioLoaded === true')
    cdp.pause(0.4)
    cdp.ev("document.getElementById('cardioModeManual').click()")
    cdp.pause(0.2)
    cdp.ev("document.querySelector('#cardioActivityGrid [data-activity=run]').click()")
    cdp.pause(0.3)
    cdp.ev("""(e => { e.value = '30'; e.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('cardioMinutes'))""")
    cdp.ev("document.getElementById('cardioSave').click()")
    cdp.wait("!document.getElementById('cardioSummary').hidden", timeout=10)
    cdp.pause(0.3)
    got = ev("[...document.querySelectorAll('#cardioSummaryAchievementList li strong')].map(e => e.textContent)")
    check('a first run after nine strength workouts is the tenth workout, and the cardio page says so', '10 workouts' in got, got)
    check('with a line to cheer it', text('cardioSummarySplash') in ev("splashLines.achievement"), text('cardioSummarySplash'))

    # ------------------------------------------------------------------ P Progress
    print('P   Progress has a row for each kind, the best earned and a bar to the next')
    cdp.goto('/progress.html')
    cdp.wait("document.querySelectorAll('#achievementList .achievement').length > 0")
    cdp.pause(0.4)
    rows = ev("[...document.querySelectorAll('#achievementList .achievement')].map(li => ({ name: li.querySelector('strong').textContent, earned: li.classList.contains('earned'), "
              "marks: li.querySelectorAll('.achievement-marks i.on').length, next: li.querySelector('.achievement-next').textContent, "
              "bar: li.querySelector('.achievement-bar span').style.width }))")
    check('a row for every kind', len(rows) == ev('achievementFamilies.length'), len(rows))
    workouts = rows[0]
    check('the best earned of a kind leads its row, with a mark for each tier earned and the next to go for',
          workouts['name'] == '10 workouts' and workouts['earned'] is True and workouts['marks'] == 2 and workouts['next'].startswith('Next: 25 workouts · now 10 workouts'), workouts)
    check('its bar drawn through the DOM, as the policy needs: 10 of 25 is 40%', workouts['bar'] == '40%', workouts['bar'])
    check('the folded row says how many are earned and the latest', text('achievementsState').startswith(f"{sum(r['marks'] for r in rows)} of ") and ' earned · latest ' in text('achievementsState'),
          text('achievementsState'))

    # ------------------------------------------------------------------ H History's streak lines
    print('H   History says a new best streak, with fireworks once, and what keeps a streak going')
    streaker = account('streaker')
    monday = ev("startOfWeek(new Date()).getTime()")
    # Three in each of the last two weeks, and three today: a 3-week streak, the best yet.
    for weeks_ago in (2, 1):
        for n in range(3):
            api('POST', '/api/workouts', {'name': 'W', 'notes': '', 'createdAt': monday - weeks_ago * 7 * DAY_MS + n * DAY_MS + 43200000, 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, streaker)
    # This week's three in its first seconds, Monday just after midnight, so they are this week's at any time this week is run.
    for n in range(3):
        api('POST', '/api/workouts', {'name': 'W', 'notes': '', 'createdAt': monday + (n + 1) * 1000, 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, streaker)
    t.set_cookie(streaker)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 9")
    cdp.pause(0.4)
    check('a run longer than any before it is said', text('streakNote') == 'New best streak: 3 weeks in a row at your goal.' and ev("!document.getElementById('streakNote').hidden") is True, text('streakNote'))
    check('with fireworks', ev("document.querySelectorAll('.firework').length") == 1)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 9")
    cdp.pause(0.4)
    check('once: opening the page again says it, without them', text('streakNote').startswith('New best streak') and ev("document.querySelectorAll('.firework').length") == 0)

    keeper = account('keeper')
    # Three last week, none yet this week: a 1-week streak to keep, while there are days enough left.
    for n in range(3):
        api('POST', '/api/workouts', {'name': 'W', 'notes': '', 'createdAt': monday - 7 * DAY_MS + n * DAY_MS + 43200000, 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, keeper)
    t.set_cookie(keeper)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 3")
    cdp.pause(0.4)
    days_left = ev("7 - ((new Date().getDay() + 6) % 7)")
    if days_left >= 3:
        check('a streak this week has yet to keep says what it takes', text('streakNote') == '3 more workouts by Sunday keeps your 1-week streak going.', text('streakNote'))
    else:
        check('with too few days left to keep it, nothing is said', ev("document.getElementById('streakNote').hidden") is True, text('streakNote'))

    # A break this week says so instead, and keeps the streak without asking for the workouts.
    api('PUT', '/api/state', {'settings': {'breaks': [{'from': ev("calendarDayKey(new Date())"), 'to': ev("calendarDayKey(addDays(new Date(), 2))")}]}}, keeper)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 3")
    cdp.pause(0.4)
    check('on a break, History says until when, and that the streak is safe', text('streakNote').startswith('On a break until ') and text('streakNote').endswith('Your 1-week streak is safe.'), text('streakNote'))
    check('the week’s count says it is a break week, and the break’s days are marked on the calendar', text('calendarSummary').endswith('· break week')
          and ev("document.querySelectorAll('#trainingCalendar .calendar-day.away').length") >= 1, text('calendarSummary'))
    api('PUT', '/api/state', {'settings': {'breaks': []}}, keeper)

    # ------------------------------------------------------------------ R within reach
    print('R   during a workout, what the next set or the finish is a step away from')
    reacher = account('reacher')
    api('POST', '/api/workouts', {'name': 'Old', 'notes': '', 'createdAt': now - 20 * DAY_MS, 'exercises': [ex('Barbell Bench Press', 205, 1, [(1, 205)])]}, reacher)
    api('POST', '/api/workouts', {'name': 'Push Day', 'notes': '', 'createdAt': now - 10 * DAY_MS, 'exercises': [ex('Bench Press', 185, 5, [(5, 185)])]}, reacher)
    t.set_cookie(reacher)
    t.open_tracker()
    t.start(0)
    cdp.pause(0.4)

    def weigh(value):
        ev(f"(e => {{ e.value = '{value}'; e.dispatchEvent(new Event('input', {{ bubbles: true }})); }})(document.getElementById('activeWeight'))")

    def hint():
        return text('reachHint') if ev("!document.getElementById('reachHint').hidden") else ''

    def fireworks():
        return ev("document.querySelector('.firework')?.dataset.size || ''")

    check('the workout starts on the bench press, at last time’s 185 lbs', text('activeExerciseName') == 'Bench Press' and t.field('activeWeight') == '185', text('activeExerciseName'))
    check('the reps at this weight that would be a record are said: 185 x 5 was the best, so 6', hint() == '6 reps at 185 lbs would be a record.', hint())
    t.log_set(5)
    cdp.pause(0.3)
    check('one fewer sets off nothing', fireworks() == '' and hint() == '6 reps at 185 lbs would be a record.', [fireworks(), hint()])
    cdp.pause(2.0)
    t.log_set(6)
    cdp.pause(0.3)
    check('the reps it said set off the fireworks of a record', fireworks() == 'record', fireworks())
    check('and the next record is a rep past the one just set', hint() == '7 reps at 185 lbs would be a record.', hint())
    weigh(190)
    check('a weight heavier than ever is a record at any reps', hint() == 'Any set at 190 lbs would be a record.', hint())
    ev("document.getElementById('bigViewBtn').click()")
    cdp.pause(0.4)
    check('the big view says it too', ev("document.getElementById('bigViewReach').textContent") == 'Any set at 190 lbs would be a record.'
          and ev("!document.getElementById('bigViewReach').hidden") is True, ev("document.getElementById('bigViewReach').textContent"))
    ev("document.getElementById('bigViewClose').click()")
    weigh('')
    check('close to a plate tier, from any name for the lift: 205 lbs on the barbell bench press is 20 lbs from two plates',
          hint() == '20 lbs from 2 plates a side (225 lbs).', hint())
    weigh(225)
    check('and a weight that reaches it for the first time says so, and when it is earned',
          hint() == '225 lbs puts 2 plates a side on the bar for the first time. It is yours when you finish.', hint())
    check('without the whole history, nothing is said of the finish',
          ev("(() => { savedWorkoutsLoaded = false; reachBase = null; renderReach(); const hidden = document.getElementById('workoutReach').hidden; savedWorkoutsLoaded = true; reachBase = null; renderReach(); return hidden; })()") is True)
    check('a timed exercise is left in peace', ev("(() => { activeSession.exercises[0].timed = true; renderActiveWorkout(); const quiet = document.getElementById('reachHint').hidden; activeSession.exercises[0].timed = false; renderActiveWorkout(); return quiet; })()") is True)
    t.end_workout()

    almost = account('almost')
    monday = ev("startOfWeek(new Date()).getTime()")
    for n in range(47):
        api('POST', '/api/workouts', {'name': 'Old', 'notes': '', 'createdAt': monday - (60 - n) * DAY_MS, 'clientId': f'almost-{n}', 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, almost)
    for n in range(2):
        api('POST', '/api/workouts', {'name': 'W', 'notes': '', 'createdAt': monday + (n + 1) * 1000, 'clientId': f'week-{n}', 'exercises': [ex('Curl', 20, 10, [(10, 20)])]}, almost)
    t.set_cookie(almost)
    t.open_tracker()
    t.start(0)
    cdp.pause(0.4)
    check('the workout says what finishing it earns: the weekly goal, and the fiftieth workout',
          text('workoutReach').startswith('Finishing this workout reaches your weekly goal') and text('workoutReach').endswith('and earns “50 workouts”.'), text('workoutReach'))
    t.end_workout()

    # ------------------------------------------------------------------ M a program's moments
    print('M   a program day: a + set past its plan, every planned rep made, and the week it finishes')
    programmer = account('programmer')
    last_day = {'definition': 'reddit-ppl', 'startedAt': 1000, 'cycle': 1, 'lastRollover': None,
                'trainingMaxes': {'deadlift': 225, 'row': 115, 'bench': 135, 'press': 85, 'squat': 185}, 'options': {'rounding': 5},
                'done': {f'0-{day}': {'at': 2000 + day, 'skipped': False, 'amrap': None, 'hit': None} for day in range(5)}}
    api('PUT', '/api/state', {'program': last_day}, programmer)
    t.set_cookie(programmer)
    t.open_tracker()
    ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.pause(0.4)
    planned = ev('activeSession.exercises[0].plan.map(set => set.reps)')
    for reps in planned[:-1]:
        t.log_set(reps)
        cdp.pause(0.3)
    cdp.pause(2.0)
    t.log_set(8)
    cdp.pause(0.3)
    check('a + set past its plan is said and celebrated as it is logged', '+ set: 8 reps, 3 more than the 5 planned!' in text('formFeedback') and fireworks() == 'goal',
          [text('formFeedback'), fireworks()])
    cdp.pause(2.8)
    t.finish_all()
    cdp.wait("!document.getElementById('workoutSummary').hidden", timeout=10)
    cdp.pause(0.3)
    lines = ev("[...document.querySelectorAll('#summaryProgramList li')].map(li => li.textContent)")
    check('the summary says the week of the program is done, the + set, and every planned rep of the main lift made',
          ev("!document.getElementById('summaryProgram').hidden") is True and lines and lines[0] == 'Week 1 of Reddit PPL complete.'
          and any(line.startswith('+ set: 8 reps at 185 lbs, 3 more than the 5 planned.') for line in lines)
          and any(line.startswith('Every planned rep of ') for line in lines), lines)
    check('with the biggest fireworks', fireworks() == 'achievement', fireworks())
    check('and the program moved on to its next week', ev('currentProgram.cycle') == 2)

    # ------------------------------------------------------------------ K the card to share
    print('K   an achievement drawn as a picture to share, and saved where it cannot be')
    t.set_cookie(almost)
    cdp.goto('/progress.html')
    cdp.wait("document.querySelectorAll('#achievementList .achievement').length > 0")
    cdp.pause(0.5)
    fitted = ev("""(() => {
      const result = achievementsOf(loadedWorkouts), problems = [];
      const fill = CanvasRenderingContext2D.prototype.fillText;
      const footer = 64 + 1130 - 214;
      achievementFamilies.forEach(family => family.tiers(result.context).forEach(tier => {
        const item = { id: family.id + ':' + tier, family: family.id, tier, name: family.name(tier, result.context), detail: family.detail(tier, result.context), at: Date.now() };
        const drawn = [];
        CanvasRenderingContext2D.prototype.fillText = function (text, x, y) { drawn.push({ text, x, y, width: this.measureText(text).width }); };
        let canvas;
        try { canvas = drawAchievementCard(item, result); } finally { CanvasRenderingContext2D.prototype.fillText = fill; }
        if (canvas.width !== 1080 || canvas.height !== 1350) problems.push(item.id + ' size');
        // The name and what it took: inside the card's margins, and above the line over the date.
        const body = drawn.filter(line => line.x === 144 && line.y < footer);
        body.forEach(line => {
          if (line.x + line.width > 937) problems.push(item.id + ' too wide: ' + line.text);
          if (line.y > footer - 20 || line.y < 64 + 470) problems.push(item.id + ' out of its room: ' + line.text);
        });
        if (body.map(line => line.text).join(' ').replace(/\\u00a0/g, ' ').indexOf(item.name) !== 0) problems.push(item.id + ' name not drawn whole');
      }));
      return problems;
    })()""")
    check('every tier of every kind fits its card: its name and what it took within the margins, under the emblem and above the date', fitted == [], fitted[:5])

    share = ev("""(async () => {
      const result = achievementsOf(loadedWorkouts), item = result.earned[result.earned.length - 1];
      const saved = [], shared = [];
      const click = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () { saved.push(this.download); };
      const real = { share: navigator.share, canShare: navigator.canShare };
      const outcome = {};
      try {
        navigator.canShare = () => true;
        navigator.share = data => { shared.push(data.files.map(file => [file.name, file.type, file.size > 1000])); return Promise.resolve(); };
        outcome.shared = await shareAchievementCard(item, result);
        navigator.share = () => Promise.reject(new DOMException('closed', 'AbortError'));
        outcome.cancelled = await shareAchievementCard(item, result);
        navigator.share = () => Promise.reject(new DOMException('no', 'NotAllowedError'));
        outcome.refused = await shareAchievementCard(item, result);
        navigator.canShare = () => false;
        outcome.unshareable = await shareAchievementCard(item, result);
      } finally {
        HTMLAnchorElement.prototype.click = click;
        navigator.share = real.share; navigator.canShare = real.canShare;
      }
      return { outcome, shared, saved, name: item.name };
    })()""")
    check('where the share sheet takes a picture, it is given the card as a PNG and nothing is saved',
          share['shared'] and share['shared'][0][0][1] == 'image/png' and share['shared'][0][0][2] is True and share['outcome']['shared'] == '', share)
    check('closing the share sheet does nothing more', share['outcome']['cancelled'] == '' and len(share['saved']) == 2, share)
    check('a share refused, or no share sheet at all (a plain http:// address), saves the picture and says so',
          share['outcome']['refused'].startswith('Saved ') and share['outcome']['unshareable'].startswith('Saved ') and all(name.endswith('.png') for name in share['saved']), share)
    check('Progress offers Share on each kind earned', ev("document.querySelectorAll('#achievementList .achievement.earned [data-share]').length") == ev("document.querySelectorAll('#achievementList .achievement.earned').length") > 0)
    ev("navigator.canShare = () => false; HTMLAnchorElement.prototype.click = function () { window.__savedCard = this.download; }")
    ev("document.querySelector('#achievementList [data-share]').click()")
    cdp.pause(0.6)
    check('and tapping it saves the card where it cannot be shared, saying so', ev("window.__savedCard || ''").endswith('.png') and text('achievementFeedback').startswith('Saved '), text('achievementFeedback'))
    t.set_cookie(t.token)
