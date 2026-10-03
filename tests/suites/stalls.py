"""Stall detection: a lift whose estimated one-rep max has stopped going up, the deload offered for it, and what is not a stall."""

import json
import time

DAY_MS = 86400000

INTERCEPT = False


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    ex = t.ex

    cookie = api('POST', '/api/auth/register', {'username': 'staller', 'email': 'staller@example.test', 'password': 'chalk-and-plates-42'})[1]
    lifter = cookie.split('session=')[1].split(';')[0]
    now = int(time.time() * 1000)

    def lift(name, days_ago, *exercises):
        api('POST', '/api/workouts', {'name': name, 'notes': '', 'createdAt': now - days_ago * DAY_MS, 'exercises': list(exercises)}, lifter)

    # Bench Press: its best (205 x 5) is 33 days old, and four sessions since have not beaten it. Stalled.
    # Overhead Press: stuck at 135, then a deload to 120 and back up since. Working back up, not stalled.
    bench = {40: (200, 5), 33: (205, 5), 26: (205, 4), 19: (205, 4), 12: (200, 5), 5: (205, 3)}
    press = {40: (135, 5), 33: (135, 4), 26: (135, 4), 19: (120, 5), 12: (125, 5), 5: (130, 5)}
    for days in bench:
        lift('Push', days, ex('Bench Press', bench[days][0], 5, [(bench[days][1], bench[days][0])] * 3),
             ex('Overhead Press', press[days][0], 5, [(press[days][1], press[days][0])] * 3))
    # Squat goes up every time; the deadlift has only three sessions; the row has not been done for six weeks.
    for days, weight in {30: 225, 20: 230, 10: 235}.items():
        lift('Legs', days, ex('Back Squat', weight, 5, [(5, weight)] * 3))
    for days in (14, 7, 3):
        lift('Pull', days, ex('Deadlift', 315, 5, [(5, 315)]))
    for days in (60, 55, 50, 45):
        lift('Back', days, ex('Barbell Row', 135, 8, [(8, 135)] * 3))
    t.set_cookie(lifter)

    # ------------------------------------------------------------------ T1 Progress
    print('T1  Progress lists the lifts that have stalled, with the deload to try')
    cdp.goto('/progress.html')
    cdp.wait("document.querySelectorAll('#stallList li').length > 0 && !document.querySelector('#stallList .empty')?.textContent.startsWith('Your lifts')")
    cdp.pause(0.5)
    stalls = cdp.ev("[...document.querySelectorAll('#stallList .record')].map(r => [...r.children].map(c => c.textContent))")
    best_day = cdp.ev(f"longDate({now - 33 * DAY_MS})")
    check('only the lift with no new best in three weeks, over three sessions, is listed',
          [s[0] for s in stalls] == ['Bench Press'], stalls)
    check('saying since when, the best it reached, and the deload: 10% off last time on the weight step',
          stalls and stalls[0][1:] == [f'No new best since {cdp.ev(f"formatDate({now - 33 * DAY_MS})")}, over 4 sessions.',
                                       f'Best est. one-rep max 239 lbs · {best_day}', "Try a week at 185 lbs, 10% off last time's 205"], stalls)
    cdp.ev("document.querySelector('#stallList .record').click()")
    cdp.pause(0.3)
    check('tapping it charts it', cdp.ev("document.getElementById('exerciseFilter').value") == 'bench press')
    check('a lift still going up, one done only three times, and one not trained lately are not stalled',
          cdp.ev("['back squat', 'deadlift', 'barbell row'].map(key => stallOf(allWorkouts, key))") == [None, None, None])
    # Weighed from its first session, its best (135 x 5, 40 days ago) has not been beaten in five sessions; from the deload on,
    # it has gone up every time.
    check('nor is one working back up from a deload', cdp.ev("stallOf(allWorkouts, 'overhead press')") is None)

    # ------------------------------------------------------------------ T2 the Strength page
    print('T2  before the first set of a stalled lift, the deload is a tap away')
    cdp.goto('/index.html')
    cdp.wait("document.querySelectorAll('#savedWorkoutList .saved-workout').length > 0")
    cdp.pause(0.5)
    newest = "[...document.querySelectorAll('#savedWorkoutList .saved-workout')].find(li => li.querySelector('strong').textContent === 'Push')"
    cdp.ev(f"{newest}.querySelector('[data-action=start]').click()")
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.pause(0.4)
    hint = lambda: None if cdp.ev("document.getElementById('progressionHint').hidden") else cdp.ev("document.getElementById('progressionHint').textContent")
    check('the stalled lift says so, as a caution', cdp.ev("document.getElementById('activeExerciseName').textContent") == 'Bench Press'
          and hint() and hint().startswith('No new best since ') and 'A lighter week often gets a lift moving again: 10% off last time is 185 lbs.' in hint()
          and cdp.ev("document.getElementById('progressionHint').classList.contains('stalled')") is True, hint())
    cdp.ev("document.getElementById('progressionUse').click()")
    check('Use 185 lbs puts it in the weight', cdp.ev("document.getElementById('activeWeight').value") == '185')
    t.log_set(5)
    cdp.pause(0.4)
    check('and once a set is logged it says no more', hint() is None, hint())
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.4)
    check('a lift that is moving gets its usual advice, not a stall', cdp.ev("document.getElementById('activeExerciseName').textContent") == 'Overhead Press'
          and cdp.ev("document.getElementById('progressionHint').classList.contains('stalled')") is False, hint())
    cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn').click()")
    cdp.pause(0.3)

    # ------------------------------------------------------------------ T3 kilograms
    print('T3  in kilograms the deload is in kilograms, on their weight step')
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), unit: 'kg' }); window.dispatchEvent(new Event('settingschange'))")
    cdp.goto('/progress.html')
    cdp.wait("document.querySelectorAll('#stallList .record').length > 0")
    cdp.pause(0.4)
    line = cdp.ev("document.querySelector('#stallList .record').lastElementChild.textContent")
    check('205 lbs is 92.99 kg, and a tenth off is 82.5 kg on 2.5 kg steps', line == "Try a week at 82.5 kg, 10% off last time's 92.99", line)
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), unit: 'lbs' })")
    t.set_cookie(t.token)
