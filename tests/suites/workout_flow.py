"""Saved-workout flow: start links, replacing an active workout, editing, repeating, and the chart."""

import json
import time

from ..harness import ACTIVE, TITLE

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
    edit()
    cdp.ev("const i = document.querySelector('#exerciseList input[data-index=\"0\"][data-field=\"weight\"]'); i.value = '110'; i.dispatchEvent(new Event('input', { bubbles: true })); document.getElementById('saveBtn').click();")
    cdp.pause(1.0)
    w = workout(W1)
    e0, e1 = w['exercises']
    check('changed weight replaces that exercise\'s stale sets', 'sets' not in e0 and str(e0['weight']) == '110', json.dumps(e0))
    check('untouched exercises keep their sets', len(e1.get('sets', [])) == 1, json.dumps(e1))
    check('user is told sets were replaced', 'replaced' in (cdp.ev("document.getElementById('formFeedback').textContent") or ''))
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
