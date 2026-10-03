"""Page scripts: shared helpers, exercise names on the Progress page, and the saved-workout buttons."""

import json
import re
import time

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
             ('/cardio.html', "cardioLoaded === true"),
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
    # A workout left going from before would keep the list out of the way (and out of reach of the focus).
    if cdp.ev("!document.getElementById('activeWorkout').hidden"):
        t.end_workout()
    rows_shown = lambda: cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout')].filter(li => !li.hidden).length")
    check('showing the first three', rows_shown() == 3, rows_shown())
    more = cdp.ev("(() => { const a = document.querySelector('#savedWorkoutList .more-workouts a'); return a && [a.textContent, a.getAttribute('href')]; })()")
    check('with a link to all of them in History', more == [f'See all {total} workouts in History', 'history.html'], more)
    check('and Show more for the other seven', cdp.ev("document.querySelector('#savedWorkoutList [data-action=more]').textContent") == 'Show 7 more')
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=more]').click()")
    check('which shows them, and goes to the first of them', rows_shown() == 10 and cdp.ev("!document.querySelector('#savedWorkoutList [data-action=more]')")
          and cdp.ev("document.activeElement === document.querySelectorAll('#savedWorkoutList .saved-workout-toggle')[3]"),
          rows_shown())
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
    spans = cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout')[0].querySelectorAll('.workout-details li span')].map(s => s.textContent)")
    check('its details write sets the same way', spans == expected, spans)
    t.start(0)
    cdp.pause(0.4)
    last = cdp.ev("document.getElementById('activeExerciseLast').textContent")
    check('and so does last time’s line during a workout', last.endswith(': 115 lbs × 5, 5, 5, 5, 9'), last)
    t.end_workout()

    settle('/progress.html', "chartData && chartData.points.length > 0")
    cdp.ev("const f = document.getElementById('exerciseFilter'); f.value = 'all'; f.dispatchEvent(new Event('change'))")
    cdp.wait(f"chartData.points.length >= {total}")
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
    # Inter comes with the app, so the page looks and measures the same on every device, whatever it has installed.
    inter = cdp.ev("document.fonts.ready.then(() => [...document.fonts].filter(f => f.family.replace(/\"/g, '') === 'Inter').map(f => f.status))")
    check('the page draws in Inter, served with the app', 'loaded' in (inter or []), inter)
    served = cdp.ev("fetch('/fonts/inter-latin.woff2').then(r => [r.status, r.headers.get('content-type')])")
    check('and the font is served as one', served == [200, 'font/woff2'], served)

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
    expected = {'weight', 'reps', 'activeWeight', 'completedReps', 'activeAddReps', 'restDurationSetting', 'barSetting',
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
        # A tap on the swatch: the radio changes, and the setting is kept as soon as it does.
        cdp.ev(f"document.getElementById('settingsButton').click(); document.querySelector('#themeSetting input[value={value}]').click();"
               "document.getElementById('closeSettings').click()")
        cdp.pause(0.3)

    def var(name, element='document.documentElement'):
        return cdp.ev(f"getComputedStyle({element}).getPropertyValue('{name}').trim()")

    device('dark')
    t.open_tracker()
    check('with no choice saved, a device in dark mode gets the dark theme', cdp.ev(theme) == 'dark', cdp.ev(theme))
    check('already set before the page is drawn', cdp.ev('window.__themeAtBody') == 'dark', cdp.ev('window.__themeAtBody'))
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings shows Match system as the choice',
          cdp.ev("(i => i.value + ' ' + i.closest('label').textContent)(document.querySelector('#themeSetting input:checked'))") == 'system Match system')
    cdp.ev("document.getElementById('closeSettings').click()")
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

    print('P6b colour themes beyond light and dark')
    device('light')
    t.open_tracker()
    cdp.ev("document.getElementById('settingsButton').click()")
    names = cdp.ev("[...document.querySelectorAll('#themeSetting .theme-swatch')].map(label => label.textContent)")
    check('Appearance offers Match system, Light, Dark and eight colour themes', names == ['Match system', 'Light', 'Sunrise', 'Meadow', 'Blossom',
          'Dark', 'Crimson', 'Emerald', 'Ocean', 'Gold', 'Violet'], names)
    previews = cdp.ev("[...document.querySelectorAll('#themeSetting .theme-preview > span')].map(span => getComputedStyle(span, '::after').backgroundColor)")
    # Match system's preview is two halves, Light's and Dark's; then one for each of the ten themes.
    check('each preview is drawn in its own theme, whatever the page is in', len(previews) == 12 and len(set(previews[2:])) == 10, previews)
    check("and Match system's halves are Light's and Dark's", previews[:2] == [previews[2], previews[6]], previews)
    check('the radios are one group the arrow keys move through', cdp.ev("new Set([...document.querySelectorAll('#themeSetting input')].map(i => i.name)).size") == 1)
    cdp.ev("document.getElementById('closeSettings').click()")
    expected = {'crimson': ('dark', '#ef4444', '#0c0c0e'), 'emerald': ('dark', '#34d399', '#0b0e0c'), 'sunrise': ('light', '#cf4f25', '#fbf5ef'),
                'ocean': ('dark', '#38bdf8', '#0a1220'), 'gold': ('dark', '#f5b72f', '#0e0d0a'), 'violet': ('dark', '#b98cff', '#110c1c'),
                'meadow': ('light', '#23805a', '#f2f7f3'), 'blossom': ('light', '#c23a78', '#fbf3f6')}
    for name, (mode, accent, background) in expected.items():
        choose(name)
        got = (cdp.ev(theme), var('--accent'), var('--bg'), cdp.ev("document.querySelector('meta[name=theme-color]').content"))
        check(f'{name}: a {mode} theme, its accent and background, and the browser chrome in it', got == (mode, accent, background, background), got)
    choose('emerald')
    check('a bright accent takes dark text on its buttons', cdp.ev("getComputedStyle(document.querySelector('.primary')).color") == 'rgb(5, 46, 31)',
          cdp.ev("getComputedStyle(document.querySelector('.primary')).color"))
    check('secondary buttons take a tint of the accent, not the indigo one', var('--accent-soft') == '#12352a'
          and cdp.ev("getComputedStyle(document.querySelector('.secondary')).backgroundColor") == 'rgb(18, 53, 42)',
          cdp.ev("getComputedStyle(document.querySelector('.secondary')).backgroundColor"))
    check('the choice reaches the server', t.wait_for(lambda: t.api('GET', '/api/state', token=t.token)[0]['settings'].get('theme') == 'emerald'))
    t.open_tracker()
    check('and is in place before the next page is drawn', cdp.ev('window.__themeAtBody') == 'dark' and cdp.ev('document.documentElement.dataset.palette') == 'emerald',
          f"{cdp.ev('window.__themeAtBody')} {cdp.ev('document.documentElement.dataset.palette')}")
    device('dark')
    device('light')
    cdp.pause(0.3)
    check('a chosen theme ignores the device changing', cdp.ev('document.documentElement.dataset.palette') == 'emerald')
    cdp.goto('/progress.html?exercise=all')
    cdp.wait("document.querySelectorAll('#legend .legend-swatch').length >= 1", timeout=10)
    check("Progress draws its first line in the theme's accent", cdp.ev("getComputedStyle(document.querySelector('#legend .legend-swatch')).backgroundColor") == 'rgb(52, 211, 153)',
          cdp.ev("getComputedStyle(document.querySelector('#legend .legend-swatch')).backgroundColor"))
    cdp.ev("document.getElementById('settingsButton').click(); document.querySelector('#themeSetting input[value=crimson]').click(); document.getElementById('closeSettings').click()")
    cdp.pause(0.3)
    check('and recolours it when the theme changes', cdp.ev("getComputedStyle(document.querySelector('#legend .legend-swatch')).backgroundColor") == 'rgb(239, 68, 68)',
          cdp.ev("getComputedStyle(document.querySelector('#legend .legend-swatch')).backgroundColor"))
    cdp.goto('/login.html')
    cdp.wait("!!document.getElementById('authForm')")
    check('the sign-in page is in the chosen theme too', cdp.ev('document.documentElement.dataset.palette') == 'crimson' and var('--accent') == '#ef4444')
    t.open_tracker()
    choose('system')
    check('Match system goes back to the device', cdp.ev('document.documentElement.dataset.palette') == 'light' and cdp.ev(theme) == 'light')

    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=at_body)
    cdp.send('Emulation.setEmulatedMedia', features=LIGHT_DEVICE)

    # ------------------------------------------------------------------ P7 the Tracker's order and its rows
    print('P7  the Tracker puts your own workouts first, each a tap from starting')
    DAY = 86400000

    def account(name):
        cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    def top(selector):
        return cdp.ev(f"document.querySelector({json.dumps(selector)}).getBoundingClientRect().top")

    # A rotation of three workouts, most recently B: A, B and C are each done, then A and B again. C is due next.
    rotation = account('rotation')
    base = int(time.time() * 1000) - 10 * DAY
    for day, name in enumerate(['A Day', 'B Day', 'C Day', 'A Day', 'B Day']):
        t.api('POST', '/api/workouts', {'name': name, 'createdAt': base + day * DAY,
                                        'exercises': [t.ex('Bench Press', 135, 5, [(5, 135)])]}, rotation)
    t.set_cookie(rotation)
    t.open_tracker()
    cdp.wait('initialLoadDone')
    shown = cdp.ev("[...document.querySelectorAll('#recentList strong')].map(s => s.textContent)")
    check('Start again offers the recent workouts, the one done longest ago first', shown == ['C Day', 'A Day', 'B Day'], shown)
    check('above the templates and the saved workouts',
          top('#recentCard') < top('#templatesToggle') < top('#savedWorkoutList'), f"{top('#recentCard')} {top('#templatesToggle')}")
    check('with the templates folded away, since there is history', cdp.ev("document.getElementById('templateArea').hidden") is True)
    check('a button says how many there are', cdp.ev("document.getElementById('templatesToggle').textContent") == 'Show templates (9)',
          cdp.ev("document.getElementById('templatesToggle').textContent"))
    cdp.ev("document.getElementById('templatesToggle').click()")
    check('and shows them', cdp.ev("!document.getElementById('templateArea').hidden && document.getElementById('templatesToggle').textContent === 'Hide templates'") is True)
    cdp.ev("document.getElementById('templatesToggle').click()")
    cdp.ev("document.querySelector('#recentList button').click()")
    cdp.pause(0.4)
    check("Start begins the workout that is due", cdp.ev("document.getElementById('activeWorkoutTitle').textContent") == 'C Day')
    t.end_workout()

    menu_hidden = "[...document.querySelectorAll('#savedWorkoutList .row-menu-items button')].every(b => !b.checkVisibility())"
    counts = cdp.ev("""[...document.querySelectorAll('#savedWorkoutList .saved-workout')].filter(row => !row.hidden).map(row =>
        [...row.querySelectorAll('button')].filter(b => b.checkVisibility() && !b.closest('.row-menu-items')).map(b => b.dataset.action).join(' '))""")
    check('each saved workout shows only its name and Start, with the rest in its menu',
          counts and all(c == 'view start' for c in counts) and cdp.ev(menu_hidden) is True, counts)
    cdp.ev("document.querySelector('#savedWorkoutList .saved-workout-toggle').click()")
    check('tapping the name shows what was done',
          cdp.ev("(b => b.getAttribute('aria-expanded') === 'true' && !b.closest('.saved-workout').querySelector('.workout-details').hidden)(document.querySelector('#savedWorkoutList .saved-workout-toggle'))") is True)
    cdp.ev("document.querySelector('#savedWorkoutList .row-menu summary').click()")
    items = cdp.ev("[...document.querySelectorAll('#savedWorkoutList .row-menu[open] .row-menu-items button')].filter(b => b.checkVisibility()).map(b => b.textContent)")
    check('the menu holds Copy as new, Edit and Delete', items == ['Copy as new', 'Edit', 'Delete'], items)
    cdp.ev("document.querySelector('main h1, header h1').click()")
    check('and closes when anything else is tapped', cdp.ev("document.querySelectorAll('.row-menu[open]').length") == 0)
    cdp.ev("document.querySelector('#savedWorkoutList .row-menu summary').click(); document.querySelector('#savedWorkoutList .row-menu [data-action=edit]').click()")
    cdp.pause(0.3)
    check('Edit opens the workout in its own card, and closes the menu',
          cdp.ev("!document.getElementById('workoutBuilderCard').hidden && document.getElementById('workoutBuilderTitle').textContent === 'Edit workout' && !document.querySelector('.row-menu[open]')") is True)
    cdp.ev("document.getElementById('clearBtn').click()")
    check('Cancel closes it again', cdp.ev("document.getElementById('workoutBuilderCard').hidden") is True)
    cdp.ev("document.getElementById('createWorkoutBtn').click()")
    check('Create workout, beside the saved workouts, opens an empty one',
          cdp.ev("!document.getElementById('workoutBuilderCard').hidden && document.getElementById('workoutBuilderTitle').textContent === 'Create a workout' && exercises.length === 0") is True)
    cdp.ev("document.getElementById('clearBtn').click()")
    cdp.ev("if (document.getElementById('templateArea').hidden) document.getElementById('templatesToggle').click();"
           "document.getElementById('createTemplateBtn').focus(); document.getElementById('createTemplateBtn').click()")
    opened = cdp.ev("!document.getElementById('templateModal').hidden && document.activeElement.id")
    cdp.ev("document.getElementById('cancelTemplate').click()")
    check('the template editor, once closed, gives the focus back to the button that opened it',
          opened == 'templateName' and cdp.ev('document.activeElement.id') == 'createTemplateBtn', [opened, cdp.ev('document.activeElement.id')])

    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    cdp.pause(0.3)
    line = cdp.ev("""(() => {
        const row = document.querySelector('#savedWorkoutList .saved-workout');
        const middle = selector => (r => (r.top + r.bottom) / 2)(row.querySelector(selector).getBoundingClientRect());
        const middles = ['.saved-workout-toggle', '[data-action=start]', '.row-menu summary'].map(middle);
        return { spread: Math.max(...middles) - Math.min(...middles), overflow: document.documentElement.scrollWidth - innerWidth };
    })()""")
    check('on a phone a row keeps its name, Start and menu on one line', line['spread'] < 8 and line['overflow'] <= 0, line)
    cdp.send('Emulation.clearDeviceMetricsOverride')

    t.set_cookie(account('newcomer'))
    t.open_tracker()
    cdp.wait('initialLoadDone')
    cdp.pause(0.3)
    check('someone new sees the templates straight away, and no Start again',
          cdp.ev("!document.getElementById('templateArea').hidden && document.getElementById('recentCard').hidden") is True)
    t.set_cookie(t.token)

    # ------------------------------------------------------------------ the training calendar
    print('C   the training calendar and weekly streak')
    import datetime as dt
    calendar = account('calendar')
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())

    def at(day, hour=12):
        return int(dt.datetime.combine(day, dt.time(hour)).timestamp() * 1000)

    def week(offset, weekdays):
        return [at(monday + dt.timedelta(weeks=offset, days=d)) for d in weekdays]

    # This week: two today. Last week and the week before: three each. Three weeks back: one. Then a run of three
    # weeks of three, five to seven weeks back: the best streak so far.
    plan = [('Today A', [at(today, 0) + 30 * 60000]), ('Today B', [at(today, 0) + 45 * 60000]),
            ('Last week', week(-1, (0, 2, 4))), ('Two weeks back', week(-2, (1, 3, 5))), ('Three weeks back', week(-3, (2,))),
            ('Five weeks back', week(-5, (0, 2, 4))), ('Six weeks back', week(-6, (0, 2, 4))), ('Seven weeks back', week(-7, (0, 2, 4)))]
    for name, times in plan:
        for created in times:
            t.api('POST', '/api/workouts', {'name': name, 'createdAt': created, 'exercises': [t.ex('Squat', 100, 5, [(5, 100)])]}, calendar)
    t.set_cookie(calendar)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.calendar-day').length > 0")
    cdp.pause(0.4)

    def calendar_state():
        return cdp.ev("""(() => ({
          summary: document.getElementById('calendarSummary').textContent,
          streak: document.getElementById('streakSummary').textContent,
          days: document.querySelectorAll('.calendar-day').length,
          trained: [...document.querySelectorAll('.calendar-day.trained')].map(d => d.dataset.date),
          today: [...document.querySelectorAll('.calendar-day.today')].map(d => [d.dataset.date, d.className, d.title]),
          future: document.querySelectorAll('.calendar-day.future').length,
          first: document.querySelector('.calendar-day').dataset.date,
          months: [...document.querySelectorAll('.calendar-month')].filter(m => m.textContent).length }))()""")

    state = calendar_state()
    expected_days = sorted({dt.date.fromtimestamp(created / 1000).isoformat() for _, times in plan for created in times})
    check('12 weeks of days, Monday first', state['days'] == 84 and state['first'] == (monday - dt.timedelta(weeks=11)).isoformat(), state)
    check('every day with a workout is filled, and only those', sorted(state['trained']) == expected_days, f"{sorted(state['trained'])} vs {expected_days}")
    check('today is marked, filled darker for two workouts, and names them',
          state['today'] and state['today'][0][0] == today.isoformat() and 'many' in state['today'][0][1]
          and 'Today A' in state['today'][0][2] and 'Today B' in state['today'][0][2], state['today'])
    check('the rest of this week is left blank', state['future'] == 6 - today.weekday(), state['future'])
    check('month names head the weeks they start in', state['months'] >= 3, state['months'])
    check('this week counts toward the default goal of 3', state['summary'] == 'This week: 2 of 3 workouts', state['summary'])
    check('an unfinished week does not break the streak: last week and the one before', state['streak'] == '2-week streak · best 3', state['streak'])
    cdp.ev(f"document.querySelector('.calendar-day[data-date=\"{today.isoformat()}\"]').click()")
    detail = cdp.ev("document.getElementById('calendarDetail').textContent")
    check('tapping a day writes its workouts under the calendar, for phones', 'Today A' in detail and 'Today B' in detail, detail)
    rest = cdp.ev("document.querySelector('.calendar-day:not(.trained):not(.future)').title")
    check('a day without a workout says rest', rest.endswith(': rest'), rest)

    # From the keyboard: one day in the tab order, today, and the arrow keys from there. A headless page is not focused,
    # which holds back focus events, so it is made to act as one that is.
    cdp.send('Emulation.setFocusEmulationEnabled', enabled=True)
    tabbable = cdp.ev("[...document.querySelectorAll('#trainingCalendar [tabindex=\"0\"]')].map(d => d.dataset.date)")
    check('the calendar is one stop for the keyboard, at today', tabbable == [today.isoformat()], tabbable)

    def press(key):
        cdp.ev(f"document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {{ key: '{key}', bubbles: true, cancelable: true }}))")

    cdp.ev(f"document.querySelector('.calendar-day[data-date=\"{today.isoformat()}\"]').focus()")
    press('ArrowLeft')
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    focused = cdp.ev("document.activeElement.dataset.date")
    check('left goes back a week', focused == week_ago, focused)
    check('writing that day under the calendar', cdp.ev("document.getElementById('calendarDetail').textContent") == cdp.ev("document.activeElement.title"))
    press('ArrowUp')
    focused = cdp.ev("document.activeElement.dataset.date")
    check('up goes back a day', focused == (today - dt.timedelta(days=8)).isoformat(), focused)
    press('ArrowRight')
    press('ArrowDown')
    focused = cdp.ev("document.activeElement.dataset.date")
    check('right and down come forward again', focused == today.isoformat(), focused)
    tabbable = cdp.ev("[...document.querySelectorAll('#trainingCalendar [tabindex=\"0\"]')].map(d => d.dataset.date)")
    check('and the tab order follows it', tabbable == [today.isoformat()], tabbable)
    if today.weekday() < 6:
        press('ArrowDown')
        check('a day still to come cannot be reached', cdp.ev("document.activeElement.dataset.date") == today.isoformat())
    cdp.send('Emulation.setFocusEmulationEnabled', enabled=False)

    cdp.ev("document.getElementById('settingsButton').click()")
    check('the weekly goal is in Settings, at 3', cdp.ev("document.getElementById('weeklyGoalSetting').value") == '3')
    cdp.ev("document.getElementById('weeklyGoalSetting').value = '2'; document.getElementById('settingsForm').requestSubmit()")
    cdp.pause(0.4)
    state = calendar_state()
    check('a goal of 2 counts at once: this week is reached', state['summary'] == 'This week: 2 workouts · goal of 2 reached', state['summary'])
    check('and joins the streak, which is now the best', state['streak'] == '3-week streak', state['streak'])
    check('the goal is saved to the account', t.wait_for(lambda: t.api('GET', '/api/state', token=calendar)[0]['settings'].get('weeklyGoal') == 2))
    cdp.ev("document.getElementById('settingsButton').click()")
    cdp.ev("document.getElementById('weeklyGoalSetting').value = '4'; document.getElementById('settingsForm').requestSubmit()")
    cdp.pause(0.4)
    state = calendar_state()
    check('a goal no week has reached means no streak, and no best', state['streak'] == 'Reach 4 in a week to start a streak'
          and state['summary'] == 'This week: 2 of 4 workouts', state)

    empty = account('nocalendar')
    t.set_cookie(empty)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.calendar-day').length > 0")
    cdp.pause(0.3)
    state = calendar_state()
    check('someone with no workouts yet sees an empty calendar and how to start', state['trained'] == [] and state['summary'] == 'This week: 0 of 3 workouts'
          and state['streak'] == 'Reach 3 in a week to start a streak', state)
    t.set_cookie(t.token)

    # ------------------------------------------------------------------ P8 the Progress chart and personal records
    print('P8  Progress spaces workouts by date, writes only the values that fit, and lists personal records')
    lifter = account('lifter')
    start = int(time.time() * 1000) - 70 * 86400000

    def lift(day, *exercises):
        t.api('POST', '/api/workouts', {'name': 'Upper', 'notes': '', 'createdAt': start + day * 86400000, 'exercises': list(exercises)}, lifter)

    def timed(name, *seconds):
        return {'name': name, 'weight': 0, 'reps': seconds[0], 'timed': True, 'sets': [{'weight': 0, 'reps': s} for s in seconds]}

    def pick(element, value):
        cdp.ev(f"(e => {{ e.value = {json.dumps(value)}; e.dispatchEvent(new Event('change')); }})(document.getElementById('{element}'))")
        cdp.pause(0.2)

    ex = t.ex
    lift(0, ex('Bench Press', 135, 5, [(5, 135)]), ex('Squat', 185, 5, [(5, 185)]), ex('Chin-up', 0, 10, [(10, 0)]), timed('Plank', 60))
    lift(1, ex('Bench Press', 140, 5, [(5, 140)]), ex('Squat', 190, 5, [(5, 190)]), ex('Curl', 30, 15, [(15, 30)]))
    lift(30, ex('Bench Press', 150, 3, [(3, 150)]))
    lift(31, ex('Bench Press', 145, 8, [(8, 145)]), ex('Chin-up', 0, 12, [(12, 0)]), timed('Plank', 90))
    lift(32, ex('Bench Press', 150, 5, [(5, 150)]))
    t.set_cookie(lifter)
    settle('/progress.html', "chartData && chartData.points.length > 0 && document.querySelectorAll('#recordsList .record').length > 0")

    check('the page opens on the exercise done most', cdp.ev("document.getElementById('exerciseFilter').value") == 'bench press',
          cdp.ev("document.getElementById('exerciseFilter').value"))
    xs = cdp.ev('drawnPoints.map(point => point.x)') or []
    ratio = (xs[2] - xs[1]) / (xs[1] - xs[0]) if len(xs) >= 3 and xs[1] != xs[0] else 0
    check('workouts sit apart by the time between them: 29 days take 29 times the room of 1', 25 < ratio < 33, f'{ratio:.1f} {xs}')
    label = cdp.ev("document.getElementById('progressChart').getAttribute('aria-label')")
    check('the chart is described in words for a screen reader', label.startswith('Heaviest weight for Bench Press: 5 workouts from ')
          and label.endswith('lowest 135 lbs, highest 150 lbs.'), label)
    point = cdp.ev('drawnPoints[2]')
    cdp.ev(f"""(() => {{ const chart = document.getElementById('progressChart'); const box = chart.getBoundingClientRect();
      chart.dispatchEvent(new MouseEvent('click', {{ clientX: box.left + {point['x']} + 3, clientY: box.top + {point['y']} - 2, bubbles: true }})); }})()""")
    detail = cdp.ev("document.getElementById('chartDetail').textContent")
    check('tapping a point says what it is', detail == point['text'] and detail.startswith('Upper, ') and detail.endswith(': 150 lbs'), detail)

    pick('metricFilter', 'oneRepMax')
    values = cdp.ev('[...chartData.types[0].values.values()]')
    check("the estimated one-rep max is charted from each workout's best set", [round(v, 2) for v in values] == [157.5, 163.33, 165, 183.67, 175], values)
    check('and titled so', cdp.ev("document.getElementById('progressTitle').textContent") == 'Estimated one-rep max')
    pick('exerciseFilter', 'curl')
    empty = cdp.ev("document.getElementById('chartEmpty').textContent")
    check('an exercise with only long sets has no one-rep max to chart, and says why',
          cdp.ev('chartData.points.length') == 0 and empty.startswith('Nothing to chart: a one-rep max needs'), empty)
    pick('exerciseFilter', 'chin-up')
    check('nor does a bodyweight exercise, rather than a line of zeros', cdp.ev('chartData.points.length') == 0)
    cdp.ev("document.getElementById('clearFilters').click()")
    cdp.pause(0.2)
    shown = cdp.ev("[document.getElementById('metricFilter').value, document.getElementById('exerciseFilter').value]")
    check('Clear filters goes back to how the page opened', shown == ['weight', 'bench press'], shown)

    records = cdp.ev("[...document.querySelectorAll('#recordsList .record')].map(r => ({ name: r.querySelector('strong').textContent, "
                     "lines: [...r.querySelectorAll(':scope > span')].map(s => s.textContent) }))") or []
    names = [record['name'] for record in records]
    lines = {record['name']: record['lines'] for record in records}

    def day(n):
        return cdp.ev(f'longDate({start + n * 86400000})')

    check('each exercise has its records, the most recent first', names[0] == 'Bench Press' and set(names[1:3]) == {'Chin-up', 'Plank'}
          and set(names[3:]) == {'Squat', 'Curl'}, names)
    check('the heaviest weight with the most reps done at it, and when', lines.get('Bench Press', [None])[0] == f'Heaviest 150 lbs × 5 · {day(32)}', lines.get('Bench Press'))
    check('the best estimated one-rep max, which need not be the heaviest set', f'Est. one-rep max 184 lbs, from 145 × 8 · {day(31)}' in lines.get('Bench Press', []),
          lines.get('Bench Press'))
    check('the most reps without weight', lines.get('Chin-up') == [f'Most reps 12 reps · {day(31)}'], lines.get('Chin-up'))
    check('the longest hold', lines.get('Plank') == [f'Longest hold 90 s · {day(31)}'], lines.get('Plank'))
    check('and no one-rep max from sets of more than 12 reps', lines.get('Curl') == [f'Heaviest 30 lbs × 15 · {day(1)}'], lines.get('Curl'))
    cdp.ev("[...document.querySelectorAll('#recordsList .record')].find(r => r.textContent.startsWith('Squat')).click()")
    cdp.pause(0.3)
    check('tapping a record charts that exercise', cdp.ev("document.getElementById('exerciseFilter').value") == 'squat' and cdp.ev('chartData.points.length') == 2)

    # Goals: a weight to reach, measured against the heaviest set so far.
    print('P8b Progress keeps a goal a weight, with a bar towards it, a deadline and a way to remove it')
    goal_items = "[...document.querySelectorAll('#goalList .goal')].map(g => g.querySelector('strong').textContent + ' | ' + g.querySelector('.goal-head span').textContent + ' | ' + g.querySelector('.goal-foot span').textContent + ' | ' + g.querySelector('[role=progressbar]').getAttribute('aria-valuenow') + ' | ' + g.classList.contains('reached'))"

    def set_goal(exercise, target, by=''):
        cdp.ev(f"document.getElementById('goalExercise').value = {json.dumps(exercise)}; document.getElementById('goalTarget').value = {json.dumps(str(target))}; "
               f"document.getElementById('goalBy').value = {json.dumps(by)}; document.querySelector('#goalForm button[type=submit]').click();")
        cdp.pause(0.3)

    settle('/progress.html', "document.querySelectorAll('#recordsList .record').length > 0")
    check('with no goals the card says so', cdp.ev("document.querySelectorAll('#goalList .goal').length") == 0
          and 'No goals yet' in cdp.ev("document.getElementById('goalList').textContent"))
    check('the exercises done are offered', 'Bench Press' in cdp.ev("[...document.querySelectorAll('#goalExercises option')].map(o => o.value)"))
    check('the target is asked for in the unit in use', cdp.ev("document.querySelector('#goalForm .unit-label').textContent") == 'lbs')
    set_goal('bench press', '')
    check('a goal with no target is refused', cdp.ev("document.querySelectorAll('#goalList .goal').length") == 0
          and 'target weight' in cdp.ev("document.getElementById('goalFeedback').textContent"), cdp.ev("document.getElementById('goalFeedback').textContent"))
    set_goal('', 200)
    check('and one with no exercise', cdp.ev("document.querySelectorAll('#goalList .goal').length") == 0
          and 'exercise' in cdp.ev("document.getElementById('goalFeedback').textContent"))
    set_goal('bench press', 200)
    check('a goal shows the heaviest weight so far against the target, under the exercise as it was written',
          cdp.ev(goal_items) == ['Bench Press | 150 of 200 lbs | 50 lbs to go | 75 | false'], cdp.ev(goal_items))
    check('and says so', cdp.ev("document.getElementById('goalFeedback').textContent") == 'Goal set for Bench Press.')
    drawn = cdp.ev("(bar => bar.firstElementChild.getBoundingClientRect().width / bar.clientWidth)(document.querySelector('#goalList .goal-bar'))")
    check('its bar is drawn three quarters full, not full (the CSP refuses widths written into markup)', drawn is not None and abs(drawn - 0.75) < 0.01, drawn)
    check('the form is cleared for the next', cdp.ev("document.getElementById('goalTarget').value") == '')
    tomorrow = "(d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'))(new Date(Date.now() + 86400000))"
    set_goal('Squat', 250, cdp.ev(tomorrow))
    squat = [g for g in cdp.ev(goal_items) if g.startswith('Squat')]
    check('a goal with a day says how long is left', squat and '60 lbs to go' in squat[0] and '1 day left' in squat[0], squat)
    set_goal('Squat', 190)
    reached = cdp.ev(goal_items)
    check('setting a goal again replaces it, and one already met is marked Reached',
          len(reached) == 2 and 'Squat | 190 of 190 lbs | Reached | 100 | true' in reached, reached)
    check('goals still to reach come before those reached', reached[0].startswith('Bench Press') and reached[1].startswith('Squat'), reached)
    goals = t.wait_for(lambda: 'squat' in t.api('GET', '/api/state', token=lifter)[0].get('goals', {})) and t.api('GET', '/api/state', token=lifter)[0]['goals']
    check('the goals are kept with the account, in the unit they were set in',
          goals == {'bench press': {'name': 'Bench Press', 'target': 200, 'unit': 'lbs', 'by': ''},
                    'squat': {'name': 'Squat', 'target': 190, 'unit': 'lbs', 'by': ''}}, goals)
    settle('/progress.html', "document.querySelectorAll('#goalList .goal').length == 2")
    check('and are there when the page opens again', len(cdp.ev(goal_items)) == 2, cdp.ev(goal_items))
    cdp.ev("document.querySelector('#goalList [data-goal-remove=\"squat\"]').click()")
    cdp.pause(0.3)
    check('Remove takes a goal away', [g.split(' | ')[0] for g in cdp.ev(goal_items)] == ['Bench Press']
          and cdp.ev("document.getElementById('goalFeedback').textContent") == 'Goal removed for Squat.', cdp.ev(goal_items))
    cdp.pause(0.6)
    check('for good', list(t.api('GET', '/api/state', token=lifter)[0]['goals']) == ['bench press'])

    # A month of daily sessions: far more points than there is room to write a value over.
    for n in range(40, 70):
        lift(n, ex('Bench Press', 150 + n % 3 * 5, 5, [(5, 150 + n % 3 * 5)]))
    settle('/progress.html', 'chartData && chartData.points.length >= 35')
    written = cdp.ev("""(() => {
      const labels = [];
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...rest) {
        if (this.font.startsWith('11px')) {
          const width = this.measureText(text).width;
          labels.push({ left: this.textAlign === 'right' ? x - width : x, width, y });
        }
        return original.call(this, text, x, y, ...rest);
      };
      drawChart();
      CanvasRenderingContext2D.prototype.fillText = original;
      const last = drawnPoints[drawnPoints.length - 1];
      const box = document.getElementById('progressChart').clientWidth;
      return { labels: labels.length, points: drawnPoints.length,
               overlaps: labels.filter((a, i) => labels.some((b, j) => j > i && a.left < b.left + b.width && b.left < a.left + a.width && Math.abs(a.y - b.y) < 11)).length,
               clipped: labels.filter(label => label.left < 0 || label.left + label.width > box).length,
               lastWritten: labels.some(label => Math.abs(label.y - (last.y - 8)) < 0.5 && (Math.abs(label.left - (last.x + 7)) < 0.5 || Math.abs(label.left + label.width - (last.x - 7)) < 0.5)) };
    })()""")
    check('only the values with room are written over the points, never overlapping', 1 < written['labels'] < written['points'] and written['overlaps'] == 0, written)
    check('always including the latest', written['lastWritten'] is True, written)
    check('none cut off at the edge of the chart', written['clipped'] == 0, written)
    # Three workout types taking turns on one line, as with push, pull and legs: their values must not collide either.
    for n in range(70, 100):
        t.api('POST', '/api/workouts', {'name': ['Push', 'Pull', 'Legs'][n % 3], 'notes': '', 'createdAt': start + n * 86400000,
                                        'exercises': [ex('Bench Press', 160 + n, 5, [(5, 160 + n)])]}, lifter)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    settle('/progress.html', 'chartData && chartData.types.length >= 4')
    mixed = cdp.ev(f"""(() => {{
      const labels = [];
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...rest) {{
        if (this.font.startsWith('11px')) {{ const width = this.measureText(text).width; labels.push({{ left: this.textAlign === 'right' ? x - width : x, width, y }}); }}
        return original.call(this, text, x, y, ...rest);
      }};
      drawChart();
      CanvasRenderingContext2D.prototype.fillText = original;
      const box = document.getElementById('progressChart').clientWidth;
      return {{ labels: labels.length, overlaps: labels.filter((a, i) => labels.some((b, j) => j > i && a.left < b.left + b.width && b.left < a.left + a.width && Math.abs(a.y - b.y) < 11)).length,
               clipped: labels.filter(label => label.left < 0 || label.left + label.width > box).length }};
    }})()""")
    check('with several workout types on one line, on a phone, the values still never overlap or run off the edge',
          mixed['labels'] >= 2 and mixed['overlaps'] == 0 and mixed['clipped'] == 0, mixed)
    fits = cdp.ev("document.querySelector('.progress-filters').scrollWidth <= document.querySelector('.progress-filters').clientWidth")
    check('and the filters fit the phone', fits is True)
    cdp.send('Emulation.clearDeviceMetricsOverride')

    print('P8c Progress logs bodyweight a day at a time, charts it, and says how it has moved')
    settle('/progress.html', "document.getElementById('bodyweightForm') !== null")
    field = lambda idn: cdp.ev(f"document.getElementById('{idn}').textContent")
    rows = "[...document.querySelectorAll('#bodyweightList li')].map(li => li.querySelector('strong').textContent)"

    def weigh(weight, day=None):
        cdp.ev(f"document.getElementById('bodyweightValue').value = {json.dumps(str(weight))};"
               + (f"document.getElementById('bodyweightDate').value = {day};" if day else '')
               + "document.querySelector('#bodyweightForm button[type=submit]').click()")
        cdp.pause(0.3)

    today_key = cdp.ev('dayKey(new Date())')
    check('with nothing logged it says what it is for, and draws no chart', 'Log your weight' in field('bodyweightSummary')
          and cdp.ev("document.getElementById('bodyweightChart').hidden") is True and cdp.ev(rows) == [], field('bodyweightSummary'))
    check('the day starts at today, and cannot go past it', cdp.ev("document.getElementById('bodyweightDate').value") == today_key
          and cdp.ev("document.getElementById('bodyweightDate').max") == today_key)
    check('the weight is asked for in the unit in use', cdp.ev("document.querySelector('#bodyweightForm .unit-label').textContent") == 'lbs')
    weigh('')
    check('no weight is refused', 'Enter your weight' in field('bodyweightFeedback') and cdp.ev(rows) == [], field('bodyweightFeedback'))
    weigh(180, "dayKey(new Date(Date.now() + 2 * 86400000))")
    check('and a day still to come', 'today or before' in field('bodyweightFeedback') and cdp.ev(rows) == [], field('bodyweightFeedback'))
    cdp.ev("document.getElementById('bodyweightDate').value = dayKey(new Date())")
    weigh(182.4)
    check('a weight is logged for today, and said so', field('bodyweightFeedback') == 'Logged 182.4 lbs for today.' and cdp.ev(rows) == ['182.4 lbs'],
          field('bodyweightFeedback'))
    check('the summary gives it, and asks for another to show a trend', field('bodyweightSummary').startswith('182.4 lbs on ')
          and field('bodyweightSummary').endswith('Log it again to see how it moves'), field('bodyweightSummary'))
    check('and the chart is drawn', cdp.ev("document.getElementById('bodyweightChart').hidden") is False
          and 'Bodyweight: 1 weigh-in' in cdp.ev("document.getElementById('bodyweightChart').getAttribute('aria-label')"))
    weigh(185, "dayKey(new Date(Date.now() - 31 * 86400000))")
    check('an earlier day goes in its place, newest first', cdp.ev(rows) == ['182.4 lbs', '185 lbs'], cdp.ev(rows))
    check('and the summary says how it has moved over the last month', field('bodyweightSummary').endswith('Down 2.6 lbs in 31 days'), field('bodyweightSummary'))
    weigh(186.6)
    check('weighing in again the same day replaces it', field('bodyweightFeedback') == 'Updated 186.6 lbs for today.'
          and cdp.ev(rows) == ['186.6 lbs', '185 lbs'] and field('bodyweightSummary').endswith('Up 1.6 lbs in 31 days'), field('bodyweightSummary'))
    kept = t.wait_for(lambda: len(t.api('GET', '/api/state', token=lifter)[0].get('bodyweight', {})) == 2) and t.api('GET', '/api/state', token=lifter)[0]['bodyweight']
    check('the weights are kept with the account, by day, in the unit logged', kept and kept.get(today_key) == {'weight': 186.6, 'unit': 'lbs'}
          and all(entry['unit'] == 'lbs' for entry in kept.values()), kept)
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), unit: 'kg' }); window.dispatchEvent(new Event('settingschange'))")
    cdp.pause(0.3)
    check('in kilograms they show converted', cdp.ev(rows) == ['84.6 kg', '83.9 kg'] and field('bodyweightSummary').endswith('Up 0.7 kg in 31 days'),
          [cdp.ev(rows), field('bodyweightSummary')])
    check('without changing what was logged', t.api('GET', '/api/state', token=lifter)[0]['bodyweight'].get(today_key) == {'weight': 186.6, 'unit': 'lbs'})
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), unit: 'lbs' }); window.dispatchEvent(new Event('settingschange'))")
    cdp.pause(0.3)
    settle('/progress.html', "document.querySelectorAll('#bodyweightList li').length === 2")
    check('they are there when the page opens again', cdp.ev(rows) == ['186.6 lbs', '185 lbs'], cdp.ev(rows))
    cdp.ev("document.querySelectorAll('#bodyweightList [data-bodyweight-remove]')[1].click()")
    cdp.pause(0.3)
    check('Remove takes a day away', cdp.ev(rows) == ['186.6 lbs'] and field('bodyweightFeedback').startswith('Removed the weight for '), field('bodyweightFeedback'))
    check('for good', t.wait_for(lambda: list(t.api('GET', '/api/state', token=lifter)[0]['bodyweight']) == [today_key]))
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    cdp.pause(0.3)
    fits = cdp.ev("(f => f.scrollWidth <= f.clientWidth && document.documentElement.scrollWidth <= innerWidth)(document.getElementById('bodyweightForm'))")
    check('and on a phone the form fits, with no sideways scrolling', fits is True)
    cdp.send('Emulation.clearDeviceMetricsOverride')
    t.set_cookie(t.token)

    # ------------------------------------------------------------------ P9 History, a month at a time
    print('P9  History lists workouts a line each, by month, with a search, a menu to change them, and the calendar leading to them')
    historian = account('historian')

    def mid_month(back):
        year, month = today.year, today.month - back
        while month < 1:
            year, month = year - 1, month + 12
        return dt.date(year, month, 15)

    def saved(name, day, hour, lift, duration=None, notes=''):
        workout = {'name': name, 'notes': notes, 'createdAt': at(day, hour), 'exercises': [t.ex(lift, 100, 5, [(5, 100)])]}
        if duration:
            workout['duration'] = duration
        return t.api('POST', '/api/workouts', workout, historian)[0]['id']

    push = saved('Push Day', today, 1, 'Bench Press', 3600, 'Felt strong')
    legs = saved('Leg Day', today, 2, 'Squat', 1800)
    for back in range(1, 6):
        saved('Old Pull', mid_month(back), 12, 'Deadlift')
    total = 7
    t.set_cookie(historian)
    settle('/history.html', f"document.querySelectorAll('.history-workout').length === {total}")

    def history():
        return cdp.ev("""(() => ({
          months: [...document.querySelectorAll('.history-month')].map(m => [m.querySelector('h3 span').textContent, m.querySelector('.history-month-total').textContent, m.hidden]),
          rows: [...document.querySelectorAll('.history-workout')].filter(r => !r.closest('[hidden]')).map(r => r.querySelector('strong').textContent),
          open: [...document.querySelectorAll('.history-workout')].filter(r => !r.querySelector('.workout-details').hidden).map(r => r.dataset.id),
          older: document.querySelector('#historyList [data-action=older]')?.textContent ?? null,
          summary: document.getElementById('historySummary').textContent }))()""")

    def search(words):
        cdp.ev(f"(i => {{ i.value = {json.dumps(words)}; i.dispatchEvent(new Event('input')); }})(document.getElementById('historySearch'))")

    def row(workout_id):
        return f"document.querySelector('.history-workout[data-id=\"{workout_id}\"]')"

    state = history()
    this_month = today.strftime('%B %Y')
    check('each workout is one line, its sets folded away', state['open'] == [] and state['rows'][:2] == ['Leg Day', 'Push Day'], state)
    check("under a heading for its month, with the month's workouts and time", state['months'][0] == [this_month, '2 workouts · 1 h 30 min', False], state['months'])
    check('the latest three months show, and a button brings the rest', [m[2] for m in state['months']] == [False] * 3 + [True] * 3
          and state['older'] == 'Show 3 older workouts' and len(state['rows']) == 4, state)
    cdp.ev(f"{row(push)}.querySelector('[data-action=view]').click()")
    check('tapping a workout shows its sets and notes', history()['open'] == [str(push)]
          and 'Felt strong' in cdp.ev(f"{row(push)}.querySelector('.workout-details').textContent")
          and cdp.ev(f"{row(push)}.querySelector('[data-action=view]').getAttribute('aria-expanded')") == 'true')

    search('squat')
    state = history()
    check('a search finds workouts by exercise', state['rows'] == ['Leg Day'] and state['summary'] == f'1 of {total} saved workouts', state)
    search('STRONG')
    check('or by a note, whatever the case', history()['rows'] == ['Push Day'], history()['rows'])
    search('deadlift')
    state = history()
    check('and looks through every month, the older ones too', state['rows'] == ['Old Pull'] * 5 and state['older'] is None, state)
    search('old squat')
    check('every word has to match', cdp.ev("document.getElementById('historyList').textContent") == 'No saved workouts match that search.')
    search('')
    state = history()
    check('clearing it brings the list back as it was, the open workout still open', len(state['rows']) == 4 and state['open'] == [str(push)], state)
    cdp.ev("document.querySelector('#historyList [data-action=older]').click()")
    state = history()
    check('Show older brings the older months', not any(m[2] for m in state['months']) and len(state['rows']) == total and state['older'] is None, state)
    check('with the focus on the first of them', cdp.ev("document.activeElement === document.querySelectorAll('.history-month')[3].querySelector('.saved-workout-toggle')") is True)

    # The calendar leads to a day's workouts, opened and marked for a moment, even when a search was hiding them.
    settle('/history.html', f"document.querySelectorAll('.history-workout').length === {total}")
    search('deadlift')
    cdp.ev(f"document.querySelector('.calendar-day[data-date=\"{today.isoformat()}\"]').click()")
    cdp.pause(0.3)
    state = history()
    check("tapping a day you trained goes to its workouts, clearing a search that hid them",
          cdp.ev("document.getElementById('historySearch').value") == '' and sorted(state['open']) == sorted([str(push), str(legs)]), state)
    check('marked for a moment, with the focus on the first', cdp.ev(f"{row(legs)}.classList.contains('picked') && {row(push)}.classList.contains('picked')") is True
          and cdp.ev(f"document.activeElement === {row(legs)}.querySelector('.saved-workout-toggle')") is True)
    old = mid_month(4).isoformat()
    cdp.ev(f"goToDay('{old}')")
    check('a day in a month still folded away brings the older months out first',
          cdp.ev(f"!document.querySelector('.history-workout[data-date=\"{old}\"]').closest('[hidden]') && !document.querySelector('.history-workout[data-date=\"{old}\"] .workout-details').hidden") is True)

    # The ⋯ menu: copying and editing open the Tracker's form; deleting happens here.
    cdp.ev(f"{row(legs)}.querySelector('.row-menu summary').click()")
    items = cdp.ev(f"[...{row(legs)}.querySelectorAll('.row-menu-items button')].filter(b => b.checkVisibility()).map(b => b.textContent)")
    check("each workout's menu holds Copy as new, Edit and Delete", items == ['Copy as new', 'Edit', 'Delete'], items)
    cdp.ev(f"{row(legs)}.querySelector('[data-action=edit]').click()")
    cdp.pause(0.3)
    opened = cdp.wait("location.pathname === '/index.html' && !document.getElementById('workoutBuilderCard').hidden", timeout=10)
    check('Edit opens it in the Tracker, in the form, to change', opened and cdp.ev("document.getElementById('workoutBuilderTitle').textContent") == 'Edit workout'
          and cdp.ev("document.getElementById('workoutName').value") == 'Leg Day' and cdp.ev("exercises.map(e => e.name)") == ['Squat'])
    check('taking the request off the address, so a reload does not open it again', cdp.ev('location.search') == '', cdp.ev('location.search'))
    settle('/history.html', f"document.querySelectorAll('.history-workout').length === {total}")
    cdp.ev(f"{row(legs)}.querySelector('[data-action=copy]').click()")
    cdp.pause(0.3)
    opened = cdp.wait("location.pathname === '/index.html' && !document.getElementById('workoutBuilderCard').hidden", timeout=10)
    check('Copy as new opens it there as a new workout', opened and cdp.ev("document.getElementById('workoutBuilderTitle').textContent") == 'Create a workout'
          and cdp.ev("document.getElementById('workoutName').value") == 'Leg Day' and cdp.ev("document.getElementById('saveBtn').textContent") == 'Save workout')
    cdp.ev("document.getElementById('clearBtn').click()")

    settle('/history.html', f"document.querySelectorAll('.history-workout').length === {total}")
    cdp.block_api = True
    cdp.ev(f"{row(push)}.querySelector('[data-action=delete]').click()")
    cdp.wait("!document.getElementById('historyFeedback').hidden")
    check('a delete that cannot reach the server says so, and keeps the workout', 'could not be deleted' in cdp.ev("document.getElementById('historyFeedback').textContent")
          and cdp.ev(f"!!{row(push)}") is True, cdp.ev("document.getElementById('historyFeedback').textContent"))
    cdp.block_api = False
    cdp.ev(f"{row(push)}.querySelector('[data-action=delete]').click()")
    cdp.wait(f"!{row(push)}")
    state = history()
    check('Delete asks, then takes it out of the list and the month', cdp.ev("document.getElementById('historyFeedback').textContent") == 'Deleted “Push Day”.'
          and state['months'][0][1] == '1 workout · 30 min' and state['summary'] == f'{total - 1} saved workouts', state)
    check('and off the server', all(w['id'] != push for w in t.api('GET', '/api/workouts', token=historian)[0]['workouts']))
    check('the calendar follows', cdp.ev(f"document.querySelector('.calendar-day[data-date=\"{today.isoformat()}\"]').title").endswith(': Leg Day'))
    t.set_cookie(t.token)
