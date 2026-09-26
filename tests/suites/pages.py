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

    # ------------------------------------------------------------------ P7 the Tracker's order and its rows
    print('P7  the Tracker puts your own workouts first, each a tap from starting')
    DAY = 86400000

    def account(name):
        cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'password123'})[1]
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
    check('a button says how many there are', cdp.ev("document.getElementById('templatesToggle').textContent") == 'Show templates (8)',
          cdp.ev("document.getElementById('templatesToggle').textContent"))
    cdp.ev("document.getElementById('templatesToggle').click()")
    check('and shows them', cdp.ev("!document.getElementById('templateArea').hidden && document.getElementById('templatesToggle').textContent === 'Hide templates'") is True)
    cdp.ev("document.getElementById('templatesToggle').click()")
    cdp.ev("document.querySelector('#recentList button').click()")
    cdp.pause(0.4)
    check("Start begins the workout that is due", cdp.ev("document.getElementById('activeWorkoutTitle').textContent") == 'C Day')
    t.end_workout()

    menu_hidden = "[...document.querySelectorAll('#savedWorkoutList .row-menu-items button')].every(b => !b.checkVisibility())"
    counts = cdp.ev("""[...document.querySelectorAll('#savedWorkoutList .saved-workout')].map(row =>
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
    rest = cdp.ev("document.querySelector('.calendar-day:not(.trained):not(.future)').title")
    check('a day without a workout says rest', rest.endswith(': rest'), rest)

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
