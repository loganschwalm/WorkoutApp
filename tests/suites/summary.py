"""The summary of a finished workout, piece by piece: the top set of some sets and how it compares with last time's, the volume
against the last time the same workout was done, the goals a workout reached, what summaryBefore takes from the history, and
what the summary shows for a first workout, for kilograms and for names that look like markup."""

import json

INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check
    t.open_tracker()

    def call(expression):
        return cdp.ev(expression)

    def change(top, before, timed='false', unit="'lbs'"):
        return call(f"topSetChange({json.dumps(top)}, {json.dumps(before)}, {timed}, {unit})")

    # ------------------------------------------------------------------ T the top set
    print('T   the top set of some sets')
    check('the heaviest weight is the top set', call("topSet([{ weight: 100, reps: 8 }, { weight: 120, reps: 3 }, { weight: 110, reps: 5 }])") == {'weight': 120, 'reps': 3})
    check('at the same weight, the most reps', call("topSet([{ weight: 100, reps: 5 }, { weight: 100, reps: 8 }, { weight: 100, reps: 6 }])") == {'weight': 100, 'reps': 8})
    check('with no weight it is the most reps, or seconds', call("topSet([{ weight: 0, reps: 8 }, { weight: '', reps: 12 }, { reps: 10 }])") == {'weight': 0, 'reps': 12})
    check('weights and reps typed as text count', call("topSet([{ weight: '135', reps: '5' }, { weight: '140', reps: '3' }])") == {'weight': 140, 'reps': 3})
    check('no sets, no top set', call("topSet([])") is None)
    check('a top set is told as weight × reps, reps for bodyweight, seconds for a hold',
          call("[describeTopSet({ weight: 187.5, reps: 5 }, false, 'lbs'), describeTopSet({ weight: 0, reps: 10 }, false, 'lbs'), describeTopSet({ weight: 0, reps: 1 }, false, 'lbs'), "
               "describeTopSet({ weight: 0, reps: 45 }, true, 'lbs'), describeTopSet({ weight: 50, reps: 8 }, false, 'kg')]")
          == ['187.5 lbs × 5', '10 reps', '1 rep', '45 s', '50 kg × 8'])

    # ------------------------------------------------------------------ C against last time
    print('C   a top set against the one before it')
    top = {'weight': 110, 'reps': 5}
    check('a heavier weight is up, by how much', change(top, {'weight': 105, 'reps': 8}) == {'kind': 'up', 'text': '+5 lbs'})
    check('whatever the reps were', change({'weight': 110, 'reps': 1}, {'weight': 105, 'reps': 10}) == {'kind': 'up', 'text': '+5 lbs'})
    check('a lighter one is down', change(top, {'weight': 120, 'reps': 5}) == {'kind': 'down', 'text': '−10 lbs'})
    check('at the same weight the reps decide: more is up', change(top, {'weight': 110, 'reps': 3}) == {'kind': 'up', 'text': '+2 reps'})
    check('fewer is down', change(top, {'weight': 110, 'reps': 6}) == {'kind': 'down', 'text': '−1 rep'})
    check('the same is the same', change(top, {'weight': 110, 'reps': 5}) == {'kind': 'same', 'text': 'Same as last time'})
    check('with no last time it is the first', change(top, None) == {'kind': 'first', 'text': 'First time'})
    check('bodyweight is compared by its reps', change({'weight': 0, 'reps': 12}, {'weight': 0, 'reps': 10}) == {'kind': 'up', 'text': '+2 reps'})
    check('adding weight to a bodyweight exercise is up in weight', change({'weight': 25, 'reps': 8}, {'weight': 0, 'reps': 12}) == {'kind': 'up', 'text': '+25 lbs'})
    check('a hold is compared by its seconds', change({'weight': 0, 'reps': 52}, {'weight': 0, 'reps': 45}, 'true') == {'kind': 'up', 'text': '+7 s'}
          and change({'weight': 0, 'reps': 40}, {'weight': 0, 'reps': 45}, 'true') == {'kind': 'down', 'text': '−5 s'})
    check('a weight in kilograms says so, to a fraction', change({'weight': 61.25, 'reps': 5}, {'weight': 60, 'reps': 5}, 'false', "'kg'") == {'kind': 'up', 'text': '+1.25 kg'})
    check('a weight converted from the other unit is not made a change by rounding',
          change({'weight': 45.36, 'reps': 5}, {'weight': 45.36, 'reps': 5}, 'false', "'kg'")['kind'] == 'same')

    # ------------------------------------------------------------------ V volume
    print('V   the volume against the last time')
    day = "new Date(2026, 2, 11, 12).getTime()"
    check('more is a percentage more, to the whole percent', call(f"volumeLine(1620, {{ volume: 1336, date: {day} }})").startswith('21% more volume than last time ('))
    check('less is less', call(f"volumeLine(500, {{ volume: 1620, date: {day} }})").startswith('69% less volume than last time ('))
    check('within half a percent is the same', call(f"volumeLine(1000, {{ volume: 1003, date: {day} }})").startswith('The same volume as last time ('))
    check('it names the day of the last time', 'Mar 11' in call(f"volumeLine(1620, {{ volume: 1336, date: {day} }})"))
    check('with nothing before, or no volume either side, there is nothing to say', call(f"[volumeLine(1620, null), volumeLine(1620, {{ volume: 0, date: {day} }}), volumeLine(0, {{ volume: 100, date: {day} }})]") == ['', '', ''])
    check('the volume of a workout leaves holds out, and counts a set with no weight as nothing',
          call("workoutVolume({ exercises: [{ name: 'Bench', sets: [{ weight: 100, reps: 5 }, { weight: 100, reps: 5 }] }, { name: 'Weighted Plank', timed: true, sets: [{ weight: 20, reps: 60 }] }, { name: 'Push-up', sets: [{ weight: 0, reps: 20 }] }] })") == 1000)
    check('the week against the goal', call("[weekGoalLine(2, 4), weekGoalLine(4, 4), weekGoalLine(5, 4), weekGoalLine(1, 1)]")
          == ['This week: 2 of 4 workouts', 'This week: 4 workouts · goal of 4 reached', 'This week: 5 workouts · goal of 4 reached', 'This week: 1 workout · goal of 1 reached'])

    # ------------------------------------------------------------------ G goals
    print('G   goals reached')
    call("writeLocal(localKey('goals'), { value: { 'bench press': { target: 225, unit: 'lbs' }, 'squat': { target: 100, unit: 'kg' }, 'deadlift': { target: 0, unit: 'lbs' } } })")
    workout = {'name': 'Heavy', 'unit': 'lbs', 'exercises': [{'name': 'Bench Press', 'sets': [{'weight': 225, 'reps': 1}]}, {'name': 'Squat', 'sets': [{'weight': 200, 'reps': 3}]},
                                                             {'name': 'Deadlift', 'sets': [{'weight': 500, 'reps': 1}]}, {'name': 'Curl', 'sets': [{'weight': 30, 'reps': 10}]}]}
    reached = call(f"goalsReached({json.dumps(workout)}, {{ 'bench press': {{ weight: 220 }}, squat: {{ weight: 300 }} }})")
    check('a goal first met by the workout is reached', reached[0] == 'Bench Press: 225 lbs, goal reached', reached)
    check('in the goal’s own unit: 200 lbs is not 100 kg, but 225 lbs is more than 100 kg', len(reached) == 1, reached)
    check('a goal already met before it is not reached again', call(f"goalsReached({json.dumps(workout)}, {{ 'bench press': {{ weight: 225 }} }})") == [])
    check('a goal with no target, and an exercise with no goal, are not goals', not any('Deadlift' in line or 'Curl' in line for line in reached), reached)
    heavy_kg = {'name': 'Heavy', 'unit': 'kg', 'exercises': [{'name': 'Squat', 'sets': [{'weight': 100, 'reps': 1}]}]}
    check('a workout in kilograms meets a goal in kilograms', call(f"goalsReached({json.dumps(heavy_kg)}, {{}})") == ['Squat: 100 kg, goal reached'])
    split = {'name': 'Heavy', 'unit': 'lbs', 'exercises': [{'name': 'Bench Press', 'sets': [{'weight': 200, 'reps': 5}]}, {'name': 'bench press', 'sets': [{'weight': 230, 'reps': 1}]}]}
    check('an exercise done twice in one workout counts once, by its heaviest', call(f"goalsReached({json.dumps(split)}, {{}})") == ['Bench Press: 225 lbs, goal reached'])
    call("localStorage.removeItem(localKey('goals'))")
    check('with no goals, none', call(f"goalsReached({json.dumps(workout)}, {{}})") == [])

    # ------------------------------------------------------------------ B what is taken before
    print('B   what the summary takes from the history, before the workout is in it')
    call("window.keep = { savedWorkouts, savedSessions, lastPerformance, bests: personalBests }")
    call("""(() => {
        const at = (month, day, hour = 12) => new Date(2026, month - 1, day, hour).getTime();
        const push = (name, createdAt, weight, unit = 'lbs') => ({ name, createdAt, unit, exercises: [{ name: 'Bench', weight, reps: 10, sets: [{ weight, reps: 10 }] }] });
        savedWorkouts = [push('Push Day', at(3, 2), 100), push(' push DAY ', at(3, 9), 50, 'kg'), push('Push Day', at(3, 20), 300), push('Pull Day', at(3, 10), 200)];
        savedSessions = [...savedWorkouts, { name: 'Run', createdAt: at(3, 8), kind: 'cardio', exercises: [] }, { name: 'Run', createdAt: at(3, 15, 23), kind: 'cardio', exercises: [] }];
        lastPerformance = { bench: { name: 'Bench', date: at(3, 9), unit: 'lbs', sets: [{ weight: 100, reps: 5 }] } };
        personalBests = { bench: { weight: 100, oneRepMax: 0, reps: 0, seconds: 0 } };
        window.found = summaryBefore({ name: 'PUSH day', createdAt: at(3, 11), exercises: [{ name: 'Bench' }, { name: 'Row' }] });
        personalBests.bench.weight = 999;
    })()""")
    found = call("window.found")
    check('the last time of an exercise, where there is one', list(found['last']) == ['bench'] and found['last']['bench']['sets'] == [{'weight': 100, 'reps': 5}], found['last'])
    check('the last workout of the same name, whatever its case and spaces, that came before this one, not one after it',
          found['previous'] is not None and found['previous']['date'] == call("new Date(2026, 2, 9, 12).getTime()"), found['previous'])
    check('its volume in the unit shown: 50 kg × 10 is 1102.3 lbs', abs(found['previous']['volume'] - 1102.3) < 0.01, found['previous'])
    check('the records so far, as they were, whatever happens to them after', found['bests']['bench']['weight'] == 100, found['bests'])
    check('this week’s workouts, Monday to Sunday, cardio too: Monday’s push, Tuesday’s pull and the Sunday night run are in, the Sunday before is not, and this one makes four',
          found['week'] == 4, found['week'])
    nothing = call("summaryBefore({ name: 'Brand New', createdAt: new Date(2026, 3, 1, 12).getTime(), exercises: [{ name: 'Row' }] })")
    check('a workout with no history has no previous, no last times and a week of just itself', nothing['previous'] is None and nothing['last'] == {} and nothing['week'] == 1, nothing)
    call("({ savedWorkouts, savedSessions, lastPerformance, personalBests } = { ...window.keep, personalBests: window.keep.bests })")

    # ------------------------------------------------------------------ S what is shown
    print('S   the summary as shown')

    def show(workout, records='[]', before='{}'):
        call(f"showWorkoutSummary({json.dumps(workout)}, {records}, {before})")
        return cdp.ev("""({ shown: !document.getElementById('workoutSummary').hidden, stats: [...document.querySelectorAll('#summaryStats li strong')].map(e => e.textContent),
            compare: document.getElementById('summaryCompare').hidden ? null : document.getElementById('summaryCompare').textContent,
            week: document.getElementById('summaryWeek').hidden ? null : document.getElementById('summaryWeek').textContent,
            goals: document.getElementById('summaryGoals').hidden ? null : [...document.querySelectorAll('#summaryGoalList li')].map(e => e.textContent),
            exercises: document.getElementById('summaryExercises').hidden ? null : [...document.querySelectorAll('#summaryExerciseList li')].map(li => li.querySelector('strong').textContent + ' | ' +
                li.querySelector('div span').textContent + ' | ' + li.querySelector('.summary-change').textContent.trim()),
            html: document.getElementById('summaryExerciseList').innerHTML })""")

    first = {'name': 'First Ever', 'unit': 'lbs', 'duration': 1500, 'exercises': [{'name': 'Squat', 'sets': [{'weight': 135, 'reps': 5}, {'weight': 135, 'reps': 5}]}]}
    shown = show(first)
    check('a first workout has no comparison and no goals, only its exercises, as firsts',
          shown['shown'] and shown['compare'] is None and shown['goals'] is None and shown['week'] is None and shown['exercises'] == ['Squat | 2 sets · top 135 lbs × 5 | First time'], shown)
    check('and the usual numbers', shown['stats'] == ['25 min', '1', '2', '1,350 lbs'], shown['stats'])
    shown = show(first, before="{ week: 2, previous: null, last: {}, bests: {} }")
    check('the week shows once the history has been looked at', shown['week'] is not None and shown['week'].startswith('This week:'), shown['week'])
    kg = {'name': 'Metric', 'unit': 'kg', 'exercises': [{'name': 'Press', 'sets': [{'weight': 40, 'reps': 8}]}]}
    shown = show(kg)
    check('a workout in the other unit is shown in the unit chosen, as the stats are', shown['exercises'] == ['Press | 1 set · top 88.18 lbs × 8 | First time'], shown)
    hostile = {'name': '<b>Bold</b>', 'unit': 'lbs', 'exercises': [{'name': '<img src=x onerror=alert(1)>', 'sets': [{'weight': 10, 'reps': 5}]}]}
    shown = show(hostile)
    check('an exercise named like markup is shown as text', '<img' not in shown['html'] and '&lt;img' in shown['html'] and cdp.ev("document.querySelectorAll('#summaryExerciseList img').length") == 0, shown['html'])
    check('and the workout’s name too', cdp.ev("document.getElementById('summaryName').textContent") == '<b>Bold</b>' and cdp.ev("document.querySelectorAll('#summaryName b').length") == 0)
    cdp.ev("document.getElementById('summaryDone').click()")
    check('Done puts it away', cdp.ev("document.getElementById('workoutSummary').hidden") is True)
