"""Saved-workout flow: start links, replacing an active workout, editing, repeating, and the chart."""

import json
import time

from ..harness import ACTIVE, HIDDEN as HIDDEN_ACTIVE, TITLE

INTERCEPT = False


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    workouts, workout = t.workouts, t.workout
    W1, W2, W3 = t.W1, t.W2, t.W3

    print('T1  ?start= handling')
    cdp.goto(f'/index.html?start={W1}')
    check('start link opens the requested workout', cdp.wait(f"{ACTIVE} && {TITLE} === 'Seed Push'"))
    check('?start is removed from the URL', cdp.ev('location.search') == '', cdp.ev('location.search'))
    cdp.ev("document.getElementById('completedReps').value = '8'; document.getElementById('completeSetBtn').click();")
    cdp.pause(0.8)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.wait(ACTIVE)
    cdp.pause(0.8)
    sets_after_reload = cdp.ev("document.querySelectorAll('#completedSets li').length")
    check('refresh mid-workout keeps the logged set', sets_after_reload == 1, f'sets={sets_after_reload}')
    before = len(workouts())
    for _ in range(3):
        cdp.ev("document.getElementById('nextExerciseBtn').click()")
        cdp.pause(0.3)
    cdp.pause(1.5)
    check('finished workout is saved', len(workouts()) == before + 1, f'{before} -> {len(workouts())}')
    check('finishing does not restart the workout', cdp.ev("document.getElementById('activeWorkout').hidden") is True)
    check('no active session left on the server', api('GET', '/api/active-session', token=token)[0]['session'] is None)

    print('T2  replace-in-progress confirmation')
    cdp.goto('/index.html')
    cdp.wait("document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
    start = lambda i: cdp.ev(f"document.querySelectorAll('#templateList [data-template-action=start]')[{i}].click()")
    start(0)
    cdp.pause(0.8)
    cdp.dialogs.clear(); cdp.answer = False
    start(1)
    cdp.pause(0.3)
    check('asks before replacing an active workout', len(cdp.dialogs) == 1 and 'Push Day' in cdp.dialogs[0], str(cdp.dialogs))
    check('declining keeps the current workout', cdp.ev(TITLE) == 'Push Day', cdp.ev(TITLE))
    cdp.answer = True
    start(1)
    cdp.pause(0.3)
    check('accepting replaces it', cdp.ev(TITLE) == 'Pull Day', cdp.ev(TITLE))
    cdp.dialogs.clear()
    cdp.ev('window.__realSettings = window.__realSettings || getWorkoutSettings; getWorkoutSettings = () => ({ ...window.__realSettings(), confirmEnd: false })')
    start(2)
    cdp.pause(0.3)
    check('no prompt when confirm-end is off', not cdp.dialogs and cdp.ev(TITLE) == 'Leg Day', f'{cdp.dialogs} {cdp.ev(TITLE)}')
    cdp.pause(0.8)

    print('T3  ?start= with a workout already in progress')
    cdp.dialogs.clear(); cdp.answer = False
    cdp.goto(f'/index.html?start={W2}')
    cdp.wait(ACTIVE)
    cdp.pause(0.5)
    check('page-load start asks before replacing', len(cdp.dialogs) == 1, str(cdp.dialogs))
    check('declining keeps the in-progress workout', cdp.ev(TITLE) == 'Leg Day', cdp.ev(TITLE))
    cdp.answer = True
    cdp.goto(f'/index.html?start={W2}')
    cdp.wait(f"{TITLE} === 'Seed Pull'")
    check('accepting starts the requested workout', cdp.ev(TITLE) == 'Seed Pull', cdp.ev(TITLE))
    cdp.pause(0.8)
    cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.8)

    print('T4  editing / repeating workouts that have logged sets')
    cdp.goto('/index.html')
    cdp.wait(f"document.querySelector('.saved-workout[data-id=\"{W1}\"]')")
    edit = lambda: (cdp.ev(f"document.querySelector('.saved-workout[data-id=\"{W1}\"] [data-action=edit]').click()"), cdp.wait('exercises.length === 2'))
    edit()
    cdp.ev("document.getElementById('saveBtn').click()")
    cdp.pause(1.0)
    w = workout(W1)
    check('saving an unchanged edit keeps set details', len(w['exercises'][0].get('sets', [])) == 2 and len(w['exercises'][1].get('sets', [])) == 1, json.dumps(w['exercises']))

    # A finished workout is changed a set at a time.
    def set_rows(exercise):
        return cdp.ev(f"[...document.querySelectorAll('#exerciseList > li')[{exercise}].querySelectorAll('.set-list li')]"
                      ".map(li => [li.querySelector('[data-field=weight]').value, li.querySelector('[data-field=reps]').value, !!li.querySelector('[data-remove-set]')])")

    def change_set(exercise, index, field, value):
        cdp.ev(f"(i => {{ i.value = '{value}'; i.dispatchEvent(new Event('change', {{ bubbles: true }})); }})"
               f"(document.querySelector('#exerciseList [data-exercise=\"{exercise}\"][data-set=\"{index}\"][data-field={field}]'))")

    def tap(selector):
        cdp.ev(f"document.querySelector('#exerciseList {selector}').click()")

    def saved_sets(exercise):
        return [(s['weight'], s['reps']) for s in workout(W1)['exercises'][exercise].get('sets', [])]

    edit()
    check('editing shows every logged set, its weight and reps', set_rows(0) == [['100', '8', True], ['100', '8', True]] and [r[:2] for r in set_rows(1)] == [['60', '8']], [set_rows(0), set_rows(1)])
    check('an exercise’s last set cannot be taken away, only the exercise', set_rows(1)[0][2] is False
          and cdp.ev("document.querySelectorAll('#exerciseList > li')[1].querySelector(':scope > .remove').textContent") == 'Remove exercise')
    check('and no weight or reps for the exercise as a whole', cdp.ev("document.querySelectorAll('#exerciseList input[data-index][data-field=weight]').length") == 0)
    check('the form says what it is for', cdp.ev("document.getElementById('workoutBuilderIntro').textContent").startswith('Change any set'))
    change_set(0, 1, 'reps', '0')
    check('a set’s reps below 1 snap back, and say why', set_rows(0)[1][1] == '8' and cdp.ev("document.getElementById('formFeedback').textContent") == 'Reps must be at least 1.', set_rows(0))
    change_set(0, 1, 'reps', '7.5')
    check('and reps that are not whole', set_rows(0)[1][1] == '8' and cdp.ev("document.getElementById('formFeedback').textContent") == 'Reps must be a whole number.', set_rows(0))
    change_set(0, 1, 'weight', '-5')
    check('and a weight below zero', set_rows(0)[1][0] == '100' and cdp.ev("document.getElementById('formFeedback').textContent") == 'Weight cannot be negative.', set_rows(0))
    change_set(0, 1, 'weight', '110')
    change_set(0, 1, 'reps', '6')
    tap('[data-exercise="1"][data-add-set]')
    check('Add set adds one like the last, its reps ready to change', [r[:2] for r in set_rows(1)] == [['60', '8'], ['60', '8']]
          and cdp.ev("document.activeElement.matches('[data-exercise=\"1\"][data-set=\"1\"][data-field=reps]')") is True, set_rows(1))
    change_set(1, 1, 'reps', '7')
    cdp.ev("document.getElementById('saveBtn').click()")
    check('a set changed and a set added are saved', t.wait_for(lambda: saved_sets(0) == [(100, 8), (110, 6)] and saved_sets(1) == [(60, 8), (60, 7)]), [saved_sets(0), saved_sets(1)])
    e0, e1 = workout(W1)['exercises']
    check('each exercise’s weight and reps follow its sets: the heaviest, and the last set’s reps', (e0['weight'], e0['reps'], e1['weight'], e1['reps']) == (110, 6, 60, 7), json.dumps([e0, e1]))
    check('and it says it was saved', cdp.ev("document.getElementById('formFeedback').textContent") == '“Seed Push” saved successfully.', cdp.ev("document.getElementById('formFeedback').textContent"))
    cdp.pause(0.6)
    edit()
    tap('[data-exercise="0"][data-remove-set="0"]')
    check('× takes a set away, and the rest renumber', [r[:2] for r in set_rows(0)] == [['110', '6']]
          and cdp.ev("document.querySelector('#exerciseList .set-number').textContent") == 'Set 1', set_rows(0))
    change_set(1, 0, 'weight', '65')
    cdp.ev("document.getElementById('clearBtn').click()")
    check('Cancel leaves the workout as it was, on the server and on the page', saved_sets(0) == [(100, 8), (110, 6)]
          and cdp.ev(f"JSON.stringify(savedWorkouts.find(w => w.id === {W1}).exercises.map(e => e.sets.map(s => [s.weight, s.reps])))") == '[[[100,8],[110,6]],[[60,8],[60,7]]]',
          cdp.ev(f"JSON.stringify(savedWorkouts.find(w => w.id === {W1}).exercises.map(e => e.sets))"))
    edit()
    check('so editing again starts from what was saved', [r[:2] for r in set_rows(0)] == [['100', '8'], ['110', '6']] and set_rows(1)[0][:2] == ['60', '8'], [set_rows(0), set_rows(1)])
    cdp.dialogs.clear(); cdp.answer = False
    change_set(0, 0, 'weight', '1100')
    check('a set changed to ten times the heaviest asks first, and saying no puts it back', len(cdp.dialogs) == 1
          and 'your heaviest Bench Press' in cdp.dialogs[0] and set_rows(0)[0][0] == '100', f'{cdp.dialogs} {set_rows(0)}')
    cdp.answer = True
    tap('[data-exercise="0"][data-remove-set="1"]')
    cdp.ev("document.getElementById('saveBtn').click()")
    check('and a set taken away is gone once saved', t.wait_for(lambda: saved_sets(0) == [(100, 8)]), saved_sets(0))
    cdp.pause(0.6)
    known = {w['id'] for w in workouts()}
    cdp.ev(f"document.querySelector('.saved-workout[data-id=\"{W3}\"] [data-action=repeat]').click()")
    cdp.wait('exercises.length === 2')
    check('repeat loads a plan without the old sets', cdp.ev("exercises.every(e => !('sets' in e))") is True)
    cdp.ev("document.getElementById('saveBtn').click()")
    cdp.pause(1.0)
    created = [w for w in workouts() if w['id'] not in known]
    check('repeated workout is saved without fake sets', len(created) == 1 and all('sets' not in e for e in created[0]['exercises']), json.dumps([w['exercises'] for w in created]))

    print('T5  progress chart with several workout types')
    cdp.goto('/progress.html')
    cdp.wait('typeof chartData !== "undefined" && chartData && chartData.points.length > 0')
    # The page opens on the exercise done most; this is about every workout type at once.
    cdp.ev("const f = document.getElementById('exerciseFilter'); f.value = 'all'; f.dispatchEvent(new Event('change'))")
    info = cdp.ev("""(() => {
      const arcs = [];
      const original = CanvasRenderingContext2D.prototype.arc;
      CanvasRenderingContext2D.prototype.arc = function (x, y, ...rest) { arcs.push(y); return original.call(this, x, y, ...rest); };
      drawChart();
      const baseline = 22 + (360 - 22 - 52);
      return { arcs: arcs.length, expected: chartData.types.reduce((n, t) => n + t.values.size, 0), atZero: arcs.filter(y => Math.abs(y - baseline) < 0.5).length, types: chartData.types.length };
    })()""")
    check('chart has multiple workout types', info['types'] >= 2, str(info))
    check('each series plots only its own workouts', info['arcs'] == info['expected'], str(info))
    check('no phantom zero-value points', info['atZero'] == 0, str(info))

    # A saved workout with no exercises (the API and an import can hold one) once threw on starting, and the empty
    # workout it left in progress threw on every load after, on every device, hiding the saved workouts with it.
    print('T6  a workout with no exercises cannot break the Tracker')
    empty = t.seed('Empty Day', 30, [])
    rows = "document.querySelectorAll('.saved-workout').length"
    feedback = "document.getElementById('formFeedback').textContent"
    cdp.console.clear()
    cdp.goto(f'/index.html?start={empty}')
    cdp.wait(f'{rows} > 0')
    cdp.pause(0.5)
    check('starting it says there is nothing to start', cdp.ev(feedback) == '“Empty Day” has no exercises to start.'
          and cdp.ev("document.getElementById('activeWorkout').hidden") is True, cdp.ev(feedback))
    api('POST', '/api/active-session', {'session': {'name': 'Empty Day', 'exercises': [], 'currentIndex': 0, 'unit': 'lbs'}}, token)
    cdp.goto('/index.html')
    cdp.wait(f'{rows} > 0')
    cdp.pause(1)
    check('one left in progress by an older version is closed, and the saved workouts still show',
          cdp.ev(feedback) == 'The workout in progress had no exercises to show, so it was closed.' and cdp.ev(rows) > 0, cdp.ev(feedback))
    check('on the server too, so no other device meets it', t.wait_for(lambda: api('GET', '/api/active-session', token=token)[0]['session'] is None))
    api('POST', '/api/active-session', {'session': {'name': 'Past The End', 'exercises': [{'name': 'Curl', 'weight': '', 'reps': '10', 'sets': []}],
                                                    'currentIndex': 7, 'unit': 'lbs'}}, token)
    cdp.goto('/index.html')
    cdp.wait(ACTIVE)
    cdp.pause(0.5)
    check('one pointing past its last exercise opens on the last', cdp.ev("document.getElementById('activeExerciseName').textContent") == 'Curl'
          and cdp.ev('activeSession.currentIndex') == 0)
    cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.5)
    thrown = [line for line in cdp.console if line.startswith('exceptionThrown')]
    check('and nothing threw along the way', not thrown, thrown[:2])

    # A workout started by mistake: Cancel workout takes it away as if it had never been started, with Undo for a slip.
    print('T7  cancelling a workout saves nothing and changes no stats, and Undo brings it back')
    cookie = api('POST', '/api/auth/register', {'username': 'canceller', 'email': 'canceller@example.test', 'password': 'chalk-and-plates-42'})[1]
    canceller = cookie.split('session=')[1].split(';')[0]
    api('POST', '/api/workouts', {'name': 'Earlier Press', 'notes': '', 'createdAt': int(time.time() * 1000) - 2 * 86400000,
                                  'exercises': [t.ex('Overhead Press', 95, 5, [(5, 95)])]}, canceller)
    api('PUT', '/api/state', {'program': {'definition': 'wendler-531', 'unit': 'lbs',
                                          'trainingMaxes': {'press': 100, 'deadlift': 300, 'bench': 200, 'squat': 250}}}, canceller)
    t.set_cookie(canceller)
    cdp.goto('/index.html')
    cdp.wait("document.querySelector('#programNext [data-program-action=start]') && Object.keys(lastPerformance).length > 0")
    cdp.pause(0.8)
    feedback = "document.getElementById('formFeedback').textContent"
    stats = "JSON.stringify([lastPerformance, personalBests, readPendingWorkouts().length, document.getElementById('programNext').textContent])"
    before_stats, before_saved = cdp.ev(stats), len(api('GET', '/api/workouts', token=canceller)[0]['workouts'])
    check('the cancel button says what it does', cdp.ev("document.getElementById('endWorkoutBtn').textContent") == 'Cancel workout')

    cdp.ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.wait(ACTIVE)
    started = cdp.ev(TITLE)
    cdp.pause(0.8)
    check('a workout in progress reaches the server', t.wait_for(lambda: api('GET', '/api/active-session', token=canceller)[0]['session'] is not None))
    cdp.dialogs.clear()
    cdp.ev("document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.4)
    check('one started by mistake, with nothing logged, is cancelled at once, without a question',
          not cdp.dialogs and cdp.ev("document.getElementById('activeWorkout').hidden") is True, cdp.dialogs)
    check('and the banner says nothing was saved, with Undo', cdp.ev(feedback) == f'“{started}” was cancelled. Nothing was saved. Undo', cdp.ev(feedback))
    check('the server is told it ended', t.wait_for(lambda: api('GET', '/api/active-session', token=canceller)[0]['session'] is None))
    cdp.ev("document.querySelector('#formFeedback .feedback-action').click()")
    cdp.pause(0.4)
    check('Undo brings it back', cdp.ev(f"{ACTIVE} && {TITLE}") == started and cdp.ev(feedback) == f'“{started}” is back.', cdp.ev(feedback))
    check('on the server too', t.wait_for(lambda: (api('GET', '/api/active-session', token=canceller)[0]['session'] or {}).get('name') == started))

    # Two sets, the second heavier than anything before: a record, had it been kept.
    cdp.ev("document.getElementById('activeWeight').value = '400'")
    t.log_set(5)
    cdp.pause(0.4)
    cdp.ev("document.getElementById('activeWeight').value = '405'")
    t.log_set(5)
    cdp.pause(0.6)
    cdp.dialogs.clear()
    cdp.answer = False
    cdp.ev("document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.3)
    check('with sets logged it asks first, saying how many would go', cdp.dialogs == ['Cancel this workout? Its 2 logged sets will not be saved.'], cdp.dialogs)
    check('and declining keeps the workout and its sets', cdp.ev(ACTIVE) and cdp.ev('activeSession.exercises[activeSession.currentIndex].sets.length') == 2)
    cdp.answer = True
    cdp.ev("document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.4)
    check('accepting cancels it', cdp.ev("document.getElementById('activeWorkout').hidden") is True)
    cdp.ev("document.querySelector('#formFeedback .feedback-action').click()")
    cdp.pause(0.4)
    check('and Undo brings it back with its sets', cdp.ev(ACTIVE) and cdp.ev('activeSession.exercises[activeSession.currentIndex].sets.length') == 2)
    # Cancelled again, and another workout started before Undo: the cancelled one cannot take its place.
    cdp.ev("window.__cancelled = activeSession; document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.4)
    cdp.ev("document.querySelectorAll('#templateList [data-template-action=start]')[0].click()")
    cdp.wait(f"{ACTIVE} && {TITLE} === 'Push Day'")
    cdp.ev('resumeWorkout(window.__cancelled)')
    cdp.pause(0.2)
    check('Undo once another workout has started says it cannot, and keeps the new one',
          cdp.ev(feedback) == f'“{started}” cannot come back: another workout has started.' and cdp.ev(TITLE) == 'Push Day', cdp.ev(feedback))
    cdp.ev("document.getElementById('endWorkoutBtn').click()")
    cdp.pause(1)

    check('nothing cancelled was saved', t.wait_for(lambda: len(api('GET', '/api/workouts', token=canceller)[0]['workouts']) == before_saved),
          len(api('GET', '/api/workouts', token=canceller)[0]['workouts']))
    check("and last time's numbers, the records, the upload queue and the program's next day are as they were", cdp.ev(stats) == before_stats,
          [cdp.ev(stats), before_stats])
    check('nor is anything left in progress', api('GET', '/api/active-session', token=canceller)[0]['session'] is None)
    cdp.goto('/index.html')
    cdp.wait("document.querySelector('#programNext [data-program-action=start]') && Object.keys(lastPerformance).length > 0")
    cdp.pause(0.8)
    check('even after a reload, with no record from the cancelled sets', cdp.ev(stats) == before_stats and cdp.ev(HIDDEN_ACTIVE) is True,
          [cdp.ev(stats), before_stats])
    t.set_cookie(token)
