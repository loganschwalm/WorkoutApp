"""Page scripts: shared helpers, exercise names on the Progress page, and the saved-workout buttons."""

import json
import re

from ..harness import LIGHT_DEVICE

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

    # ------------------------------------------------------------------ P5 compact sets, recent workouts, chart dates
    print('P5  sets written compactly, the ten most recent workouts, and chart dates that fit')
    # Four weeks of older workouts, one a day, so the lists and the chart have more than fits.
    for days_back in range(6, 31):
        t.seed('Older Session', -days_back, [t.ex('Barbell Row', 80, 8, [(8, 80), (8, 80)])])
    t.seed('Format Check', 7, [
        t.ex('Back Squat', 185, 5, [(5, 185), (5, 185), (5, 185)]),
        t.ex('Bench Press', 115, 9, [(5, 115), (5, 115), (5, 115), (5, 115), (9, 115)]),
        t.ex('Chin-up', 0, 8, [(10, 0), (9, 0), (8, 0)]),
        t.ex('Overhead Press', 85, 3, [(5, 45), (5, 65), (3, 85)]),
        t.ex('Dip', 0, 12, [(12, 0), (12, 0), (12, 0)]),
    ])
    total = len(t.workouts())
    expected = ['3 × 5 at 185 lbs', '115 lbs × 5, 5, 5, 5, 9', '10, 9, 8 reps', '45 lbs × 5 · 65 lbs × 5 · 85 lbs × 3', '3 × 12']

    settle('/history.html', f"document.querySelectorAll('.history-workout').length >= {total}")
    spans = cdp.ev("[...[...document.querySelectorAll('.history-workout')].find(li => li.textContent.includes('Format Check')).querySelectorAll('.workout-details li span')].map(s => s.textContent)")
    check('History writes repeated sets compactly', spans == expected, spans)
    history = cdp.ev("document.getElementById('historyList').textContent")
    check('and bodyweight sets as reps, never 0 lbs', not re.search(r'(?<![\d.])0 lbs', history), re.findall(r'.{20}(?<![\d.])0 lbs', history))

    settle('/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 10")
    names = cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout-summary strong')].map(s => s.textContent)")
    check('the Tracker lists the ten most recent workouts', len(names) == 10 and names[0] == 'Format Check' and names.count('Older Session') == 4, names)
    more = cdp.ev("(() => { const a = document.querySelector('#savedWorkoutList .more-workouts a'); return a && [a.textContent, a.getAttribute('href')]; })()")
    check('with a link to all of them in History', more == [f'See all {total} workouts in History', 'history.html'], more)
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
    spans = cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout')[0].querySelectorAll('.workout-details li span')].map(s => s.textContent)")
    check('its details write sets the same way', spans == expected, spans)
    t.start(0)
    cdp.pause(0.4)
    last = cdp.ev("document.getElementById('activeExerciseLast').textContent")
    check('and so does last time’s line during a workout', last.endswith(': 115 lbs × 5, 5, 5, 5, 9'), last)
    t.end_workout()

    settle('/progress.html', f"chartData && chartData.points.length >= {total}")
    dates = cdp.ev("""(() => {
      const labels = [];
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...rest) {
        if (y === 360 - 20) labels.push({ text, x, width: this.measureText(text).width });
        return original.call(this, text, x, y, ...rest);
      };
      drawChart();
      CanvasRenderingContext2D.prototype.fillText = original;
      const overlaps = labels.slice(1).filter((label, i) => label.x - labels[i].x < (label.width + labels[i].width) / 2).length;
      return { labels: labels.length, points: chartData.points.length, overlaps, first: labels[0]?.text === formatDate(chartData.points[0].createdAt),
               last: labels[labels.length - 1]?.text === formatDate(chartData.points[chartData.points.length - 1].createdAt) };
    })()""")
    check('the chart writes only the dates that fit', 1 < dates['labels'] < dates['points'] and dates['overlaps'] == 0, dates)
    check('starting with the first workout and ending with the most recent', dates['first'] is True and dates['last'] is True, dates)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    cdp.pause(0.3)
    narrow = cdp.ev("""(() => {
      const labels = [];
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...rest) {
        if (y === 360 - 20) labels.push({ x, width: this.measureText(text).width });
        return original.call(this, text, x, y, ...rest);
      };
      drawChart();
      CanvasRenderingContext2D.prototype.fillText = original;
      return { labels: labels.length, overlaps: labels.slice(1).filter((label, i) => label.x - labels[i].x < (label.width + labels[i].width) / 2).length };
    })()""")
    check('even on a phone', narrow['labels'] >= 2 and narrow['overlaps'] == 0, narrow)
    cdp.send('Emulation.clearDeviceMetricsOverride')

    # ------------------------------------------------------------------ P6 fonts, number pads and appearance
    print('P6  buttons in the page font, number pads for numbers, and a theme that follows the device')
    t.open_tracker()
    look = "(e => (s => ({ family: s.fontFamily, weight: s.fontWeight }))(getComputedStyle(e)))"
    fonts = cdp.ev(f"""({{ body: getComputedStyle(document.body).fontFamily,
                        button: {look}(document.getElementById('createWorkoutBtn')),
                        link: {look}(document.querySelector('a.button-link')) }})""")
    check('buttons use the page font, in bold', fonts['button'] == {'family': fonts['body'], 'weight': '700'}, fonts)
    check('and so do links drawn as buttons', fonts['link'] == {'family': fonts['body'], 'weight': '700'}, fonts)

    # Every number field the Tracker can show: the page's own, a built workout's rows, the template editor's, and a
    # logged set's. Each has to ask a phone for its number pad: decimal for weights (they take .5), numeric otherwise.
    fields = """[...document.querySelectorAll('input[type=number]')].map(i => ({
        name: i.id || i.className, pad: i.inputMode, weight: i.step === '0.5' }))"""
    seen = {}
    cdp.ev("document.getElementById('createWorkoutBtn').click(); document.getElementById('exercise').value = 'Curl';"
           "document.getElementById('weight').value = '20'; document.getElementById('reps').value = '10'; document.getElementById('addBtn').click()")
    seen.update({f['name']: f for f in cdp.ev(fields)})
    cdp.ev("document.getElementById('createTemplateBtn').click()")
    seen.update({f['name']: f for f in cdp.ev(fields)})
    cdp.ev("document.getElementById('cancelTemplate').click(); document.getElementById('clearBtn').click()")
    t.start(0)
    t.log_set(8)
    cdp.pause(0.3)
    seen.update({f['name']: f for f in cdp.ev(fields)})
    t.end_workout()
    expected = {'weight', 'reps', 'activeWeight', 'completedReps', 'activeAddReps', 'restDurationSetting',
                'templateReps0', 'exercise-edit', 'set-edit'}
    check('every kind of number field was on screen', expected <= set(seen), sorted(set(seen)))
    wrong = {name: field['pad'] for name, field in seen.items() if field['pad'] != ('decimal' if field['weight'] else 'numeric')}
    check('each asks for a number pad, with a decimal point for weights', not wrong, wrong)

    def device(scheme):
        cdp.send('Emulation.setEmulatedMedia', features=[{'name': 'prefers-color-scheme', 'value': scheme}])

    theme = 'document.documentElement.dataset.theme'
    # What the theme was when <body> was created, before anything on the page could be drawn.
    at_body = cdp.send('Page.addScriptToEvaluateOnNewDocument', source="""
        window.__themeAtBody = 'not seen';
        new MutationObserver((records, observer) => {
          if (!document.body) return;
          window.__themeAtBody = document.documentElement.dataset.theme || null;
          observer.disconnect();
        }).observe(document, { childList: true, subtree: true });
    """)['result']['identifier']

    def choose(value):
        cdp.ev(f"document.getElementById('settingsButton').click(); document.getElementById('themeSetting').value = '{value}';"
               "document.getElementById('settingsForm').requestSubmit()")
        cdp.pause(0.3)

    device('dark')
    t.open_tracker()
    check('with no choice saved, a device in dark mode gets the dark theme', cdp.ev(theme) == 'dark', cdp.ev(theme))
    check('already set before the page is drawn', cdp.ev('window.__themeAtBody') == 'dark', cdp.ev('window.__themeAtBody'))
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings shows Match system as the choice',
          cdp.ev("(s => s.value + ' ' + s.selectedOptions[0].textContent)(document.getElementById('themeSetting'))") == 'system Match system')
    cdp.ev("document.getElementById('cancelSettings').click()")
    device('light')
    check('the device switching to light mode takes the open page with it', cdp.wait(f"{theme} === 'light'"), cdp.ev(theme))
    device('dark')
    check('and back to dark', cdp.wait(f"{theme} === 'dark'"), cdp.ev(theme))

    choose('light')
    check('choosing Light overrides a dark device', cdp.ev(theme) == 'light', cdp.ev(theme))
    t.open_tracker()
    check('from the first moment of the next page', cdp.ev('window.__themeAtBody') == 'light' and cdp.ev(theme) == 'light',
          f"{cdp.ev('window.__themeAtBody')} {cdp.ev(theme)}")
    device('light')
    device('dark')
    cdp.pause(0.3)
    check('and ignores the device changing', cdp.ev(theme) == 'light', cdp.ev(theme))
    device('light')
    choose('dark')
    check('choosing Dark overrides a light device', cdp.ev(theme) == 'dark', cdp.ev(theme))
    choose('system')
    check('choosing Match system follows it again', cdp.ev(theme) == 'light', cdp.ev(theme))
    check('and the choice reaches the server', t.wait_for(lambda: t.api('GET', '/api/state', token=t.token)[0]['settings'].get('theme') == 'system'))

    device('dark')
    cdp.goto('/login.html')
    cdp.wait("!!document.getElementById('authForm')")
    check('the sign-in page follows the device too', cdp.ev(theme) == 'dark' and cdp.ev('window.__themeAtBody') == 'dark',
          f"{cdp.ev('window.__themeAtBody')} {cdp.ev(theme)}")
    check('with the browser chrome to match', cdp.ev("document.querySelector('meta[name=theme-color]').content").lower() == '#151923')

    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=at_body)
    cdp.send('Emulation.setEmulatedMedia', features=LIGHT_DEVICE)
