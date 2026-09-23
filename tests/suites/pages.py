"""Page scripts: shared helpers, exercise names on the Progress page, and the saved-workout buttons."""

import json

INTERCEPT = True


def run(t):
    cdp, check = t.cdp, t.check

    def settle(path, ready):
        cdp.goto(path)
        cdp.wait(ready, timeout=10)
        cdp.pause(0.5)

    # ------------------------------------------------------------------ P1 scripts load cleanly
    print('P1  every page loads its scripts without an error')
    pages = [('/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 3"),
             ('/history.html', "document.querySelectorAll('.history-workout').length >= 3"),
             ('/progress.html', "document.querySelectorAll('#exerciseFilter option').length > 1")]
    for path, ready in pages:
        cdp.console.clear()
        settle(path, ready)
        errors = [line for line in cdp.console if line.startswith('exceptionThrown')]
        check(f'{path}: no uncaught errors', errors == [], errors)
        shared = cdp.ev("typeof $ === 'function' && typeof escapeHTML === 'function' && typeof getSavedWorkouts === 'function' && typeof exerciseKey === 'function'")
        check(f'{path}: the shared helpers are there', shared is True)
        check(f'{path}: the date header is filled in', bool(cdp.ev("document.getElementById('today').textContent")))
        check(f'{path}: no IndexedDB code is left', cdp.ev("typeof openDatabase === 'undefined' && typeof databaseName === 'undefined'") is True)
        # On the first load after an update, the previous service worker can serve the previous page scripts,
        # which declare `const $` at the top level. Evaluating one here is that script arriving; it must not
        # collide with common.js. (It shadows $ for the rest of this page, so it goes last before navigating.)
        try:
            cdp.ev('const $ = id => document.getElementById(id); true')
            collided = None
        except RuntimeError as error:
            collided = str(error)
        check(f'{path}: an older cached script declaring its own $ still runs', collided is None, collided)

    # ------------------------------------------------------------------ P2 exercise names on Progress
    print('P2  Progress treats differently typed names as one exercise')
    # W1 and W3 are "Bench Press"; add the same exercise typed two other ways, the newest last.
    t.seed('Variant Lower', 5, [t.ex('bench press', 110, 8, [(8, 110)])])
    t.seed('Variant Caps', 6, [t.ex('BENCH PRESS ', 115, 8, [(8, 115)])])
    settle('/progress.html', "document.querySelectorAll('#exerciseFilter option').length > 1")
    options = cdp.ev("[...document.getElementById('exerciseFilter').options].map(o => ({ value: o.value, label: o.textContent }))")
    bench = [o for o in options if o['label'].strip().lower() == 'bench press']
    check('one option for all three spellings', len(bench) == 1, options)
    check('labelled with the most recent spelling', bench and bench[0]['label'] == 'BENCH PRESS', bench)
    cdp.ev(f"const f = document.getElementById('exerciseFilter'); f.value = {json.dumps(bench[0]['value'] if bench else '')}; f.dispatchEvent(new Event('change'))")
    cdp.pause(0.3)
    points = cdp.ev('chartData.points.length')
    check('choosing it charts every workout that has it', points == 4, points)
    names = cdp.ev("[...document.querySelectorAll('#legend .legend-item')].map(i => i.textContent)")
    check('across all the workout types that include it', sorted(names) == ['Seed Push', 'Variant Caps', 'Variant Lower'], names)

    # ------------------------------------------------------------------ P3 saved-workout buttons
    print('P3  the saved-workout buttons use the list already on screen')
    settle('/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 5")

    def list_requests():
        return cdp.ev("performance.getEntriesByType('resource').filter(e => new URL(e.name).pathname === '/api/workouts').length")

    before = list_requests()
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
    cdp.pause(0.4)
    check('View opens the details', cdp.ev("!document.querySelector('#savedWorkoutList .workout-details').hidden") is True)
    check('without fetching the whole list again', list_requests() == before, f'{before} -> {list_requests()}')

    cdp.block_api = True
    cdp.ev("document.querySelectorAll('#savedWorkoutList [data-action=view]')[1].click()")
    cdp.pause(0.4)
    check('with the server unreachable, View still works',
          cdp.ev("!document.querySelectorAll('#savedWorkoutList .workout-details')[1].hidden") is True)
    target = cdp.ev("document.querySelectorAll('#savedWorkoutList .saved-workout-summary strong')[1].textContent")
    cdp.ev("document.querySelectorAll('#savedWorkoutList [data-action=repeat]')[1].click()")
    cdp.pause(0.4)
    loaded = cdp.ev("document.getElementById('workoutName').value")
    check('and so does Repeat, for the workout it belongs to', loaded == target, f'{loaded} vs {target}')
    cdp.block_api = False

    # ------------------------------------------------------------------ P4 hidden means hidden
    print('P4  nothing marked hidden is showing')
    # A class that sets display (flex, grid) beats the browser's own [hidden] rule; that left the empty-chart
    # message over a full chart and the rest timer up before the first set.
    leaks = """[...document.querySelectorAll('[hidden]')].filter(e => getComputedStyle(e).display !== 'none')
      .map(e => `${e.tagName.toLowerCase()}#${e.id}.${[...e.classList].join('.')}`)"""
    states = [('the tracker', '/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 3", None),
              ('a workout before its first set', '/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 3",
               "document.querySelector('#templateList [data-template-action=start]').click()"),
              ('History', '/history.html', "document.querySelectorAll('.history-workout').length >= 3", None),
              ('Progress with workouts to chart', '/progress.html', "chartData && chartData.points.length > 0", None),
              ('the sign-in page', '/login.html', "!!document.getElementById('authForm')", None)]
    for label, path, ready, action in states:
        settle(path, ready)
        if action:
            cdp.ev(action)
            cdp.pause(0.4)
        showing = cdp.ev(leaks)
        check(f'{label}: every hidden element is invisible', showing == [], showing)
    settle('/progress.html', "chartData && chartData.points.length > 0")
    cdp.ev("renderProgress([])")
    check('and does show when there is nothing to chart',
          cdp.ev("getComputedStyle(document.getElementById('chartEmpty')).display") != 'none')
