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
    t.set_cookie(t.token)
