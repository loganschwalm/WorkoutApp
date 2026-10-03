"""In-workout usability: last time's numbers, editing sets, navigation, skipped exercises,
message visibility, the phone layout, session expiry and signing out."""

import json
import time
import urllib.parse

from ..harness import ACTIVE, HIDDEN

INTERCEPT = True


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    seed, ex, workouts, ids, raw = t.seed, t.ex, t.workouts, t.ids, t.raw
    safe_ev, wait_for = t.safe_ev, t.wait_for
    start, log_set, open_tracker, end_workout = t.start, t.log_set, t.open_tracker, t.end_workout
    server_session, set_cookie, W1 = t.active_session, t.set_cookie, t.W1

    # ------------------------------------------------------------------ gym usability
    def log(weight, reps):
        cdp.ev(f"document.getElementById('activeWeight').value = '{weight}'; document.getElementById('completedReps').value = '{reps}'; document.getElementById('completeSetBtn').click();")

    def rows():
        return cdp.ev("[...document.querySelectorAll('#completedSets li')].map(li => ({ label: li.querySelector('.set-number').textContent, weight: li.querySelector('[data-field=weight]').value, reps: li.querySelector('[data-field=reps]').value }))")

    def edit_set(index, field, value):
        cdp.ev(f"(() => {{ const i = document.querySelector('#completedSets [data-set=\"{index}\"][data-field=\"{field}\"]'); i.value = '{value}'; i.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').value")

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def visible(idn):
        return cdp.ev(f"!document.getElementById('{idn}').hidden")

    def newest_workout(known):
        fresh = [w for w in workouts() if w['id'] not in known]
        return fresh[0] if fresh else None

    def ui_login(query=''):
        cdp.goto('/login.html' + query)
        cdp.ev("document.getElementById('username').value = 'tester'; document.getElementById('password').value = 'chalk-and-plates-42'; document.getElementById('authForm').requestSubmit()")
        cdp.wait("location.pathname !== '/login.html'")
        cdp.pause(0.6)

    def no_confirm():
        # Page-scoped, like the variable it replaced: the next page load reads the real settings again.
        cdp.ev('window.__realSettings = window.__realSettings || getWorkoutSettings; getWorkoutSettings = () => ({ ...window.__realSettings(), confirmEnd: false })')

    # ---- L: last time's numbers
    print('L   last time\'s numbers')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    last = text('activeExerciseLast')
    check('shows the most recent session of the exercise', visible('activeExerciseLast') and 'Last time' in last and '105 lbs × 8' in last, last)
    check('prefills weight and reps from it (template has no weight)', field('activeWeight') == '105' and field('completedReps') == '8', f"{field('activeWeight')} × {field('completedReps')}")
    log(110, 6)
    cdp.pause(0.3)
    check('after a set, the next one defaults to the set just logged', field('activeWeight') == '110' and field('completedReps') == '6', f"{field('activeWeight')} × {field('completedReps')}")
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('each exercise shows its own history', '62 lbs × 8' in text('activeExerciseLast') and field('activeWeight') == '62', text('activeExerciseLast'))
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('an exercise with no history shows nothing and prefills nothing', not visible('activeExerciseLast') and field('activeWeight') == '' and field('completedReps') == '', f"{visible('activeExerciseLast')} '{field('activeWeight')}' '{field('completedReps')}'")
    end_workout()
    seed('Seed Push', 6, [ex('bench press ', 200, 3, [(3, 200)])])
    seed('Seed Push', 7, [ex('Bench Press', 105, 8, [])])
    open_tracker()
    start(0)
    cdp.pause(0.4)
    last = text('activeExerciseLast')
    check('names match regardless of case and spacing', '200 lbs × 3' in last, last)
    check('a skipped session is not treated as last time', '105 lbs × 8' not in last, last)
    end_workout()
    cdp.block_api = True
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(1.2)
    start(0)
    cdp.pause(0.4)
    last = text('activeExerciseLast')
    check('still shown when the server is unreachable', '200 lbs × 3' in last, last)
    log(220, 2)
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(0.6)
    start(0)
    cdp.pause(0.4)
    last = text('activeExerciseLast')
    check('a workout finished offline is remembered immediately', '220 lbs × 2' in last, last)
    end_workout()
    cdp.block_api = False
    check('and uploads afterwards', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0), '')

    # ---- A: fixing logged sets
    print('A   correcting logged sets')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    log(100, 8); log(100, 8); log(95, 7)
    cdp.pause(0.4)
    r = rows()
    check('each logged set is an editable row', len(r) == 3 and [x['label'] for x in r] == ['Set 1', 'Set 2', 'Set 3'] and r[2]['weight'] == '95', str(r))
    cdp.ev("document.querySelector('#completedSets [data-remove-set=\"1\"]').click()")
    cdp.pause(0.3)
    r = rows()
    check('a wrong set can be removed and the rest renumber', len(r) == 2 and [x['label'] for x in r] == ['Set 1', 'Set 2'] and [x['weight'] for x in r] == ['100', '95'], str(r))
    cdp.ev("document.getElementById('completedReps').value = '5'")
    edit_set(0, 'weight', 105)
    cdp.pause(0.2)
    s = cdp.ev('activeSession.exercises[0].sets')
    check('a set can be edited in place', s[0]['weight'] == 105 and s[1]['weight'] == 95, str(s))
    check('editing does not disturb what is typed for the next set', field('completedReps') == '5', field('completedReps'))
    edit_set(1, 'reps', 0)
    cdp.pause(0.2)
    fb = text('formFeedback')
    check('an invalid edit snaps back and explains why', rows()[1]['reps'] == '7' and 'at least 1' in fb, f"{rows()[1]['reps']} / {fb}")
    check('corrections reach the server', wait_for(lambda: (server_session() or {}).get('exercises', [{}])[0].get('sets', [{}])[0].get('weight') == 105), '')
    known = ids()
    for _ in range(3):
        cdp.ev("document.getElementById('nextExerciseBtn').click()")
        cdp.pause(0.2)
    cdp.pause(1.5)
    w = newest_workout(known)
    e0 = w['exercises'][0] if w else {}
    check('the saved workout uses the corrected sets', w and e0.get('weight') == 105 and e0.get('reps') == 7 and len(e0.get('sets', [])) == 2, json.dumps(e0))

    # ---- N: moving between exercises
    print('N   previous exercise')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    check('no Previous button on the first exercise', cdp.ev("document.getElementById('prevExerciseBtn').hidden") is True)
    log(100, 8)
    cdp.pause(0.3)
    check('logging a set starts the rest timer', visible('restPanel'))
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('Previous appears from the second exercise on', cdp.ev("document.getElementById('prevExerciseBtn').hidden") is False and 'Exercise 2 of 3' in text('activeWorkoutProgress'))
    check('moving on resets the rest timer', cdp.ev("document.getElementById('restPanel').hidden") is True)
    cdp.ev("document.getElementById('prevExerciseBtn').click()")
    cdp.pause(0.3)
    check('going back returns to the earlier exercise with its sets', text('activeExerciseName') == 'Bench Press' and len(rows()) == 1 and cdp.ev("document.getElementById('prevExerciseBtn').hidden") is True, f"{text('activeExerciseName')} {rows()}")
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('last exercise offers Finish', text('nextExerciseBtn') == 'Finish workout')
    cdp.pause(0.8)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.wait(ACTIVE)
    cdp.pause(0.6)
    check('and going back is remembered too', 'Exercise 3 of 3' in text('activeWorkoutProgress') and cdp.ev("document.getElementById('prevExerciseBtn').hidden") is False, text('activeWorkoutProgress'))
    no_confirm()
    end_workout()

    # ---- X: adding an exercise mid-workout
    print('X   adding an exercise mid-workout')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    cdp.ev("document.getElementById('activeWeight').value = '111'; document.getElementById('completedReps').value = '9'; document.getElementById('addActiveExercise').open = true")
    cdp.ev("document.getElementById('activeAddBtn').click()")
    check('needs a name', 'exercise name' in text('formFeedback') and cdp.ev("document.getElementById('activeAddName').getAttribute('aria-invalid')") == 'true', text('formFeedback'))
    cdp.ev("document.getElementById('activeAddName').value = 'Dips'; document.getElementById('activeAddBtn').click()")
    check('needs target reps', 'target rep' in text('formFeedback'), text('formFeedback'))
    cdp.ev("document.getElementById('activeAddReps').value = '10'; document.getElementById('activeAddBtn').click()")
    cdp.pause(0.3)
    check('the exercise count updates', 'Exercise 1 of 4' in text('activeWorkoutProgress'), text('activeWorkoutProgress'))
    check('what was typed for the current set is kept', field('activeWeight') == '111' and field('completedReps') == '9', f"{field('activeWeight')} × {field('completedReps')}")
    check('the form clears and closes', field('activeAddName') == '' and cdp.ev("document.getElementById('addActiveExercise').open") is False)
    check('the user is told where it went', 'next exercise' in text('formFeedback'), text('formFeedback'))
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('Next goes to the new exercise', text('activeExerciseName') == 'Dips' and 'Target: 10 reps' in text('activeExerciseTarget'), f"{text('activeExerciseName')} {text('activeExerciseTarget')}")
    check('it reaches the server in the right place', wait_for(lambda: [e['name'] for e in (server_session() or {}).get('exercises', [])][:2] == ['Bench Press', 'Dips']), str([e['name'] for e in (server_session() or {}).get('exercises', [])]))
    log(0, 12)
    known = ids()
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(1.5)
    w = newest_workout(known)
    check('and is saved with the workout', w and [e['name'] for e in w['exercises']] == ['Dips'] and w['exercises'][0]['sets'][0]['reps'] == 12, json.dumps(w['exercises']) if w else 'none')

    # ---- K: skipped exercises
    print('K   skipped exercises')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    log(100, 8)
    known = ids()
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(1.5)
    w = newest_workout(known)
    check('exercises with no sets are left out of the saved workout', w and [e['name'] for e in w['exercises']] == ['Bench Press'], json.dumps([e['name'] for e in w['exercises']]) if w else 'none')
    check('the user is told what was left out', '2 exercises with no sets were left out' in text('formFeedback'), text('formFeedback'))
    known = ids()
    open_tracker()
    start(1)
    cdp.pause(0.4)
    cdp.dialogs.clear(); cdp.answer = False
    for _ in range(4):
        cdp.ev("document.getElementById('nextExerciseBtn').click()")
        cdp.pause(0.2)
    check('finishing with nothing logged asks first', len(cdp.dialogs) == 1 and 'No sets were logged' in cdp.dialogs[0], str(cdp.dialogs))
    check('and stays in the workout if declined', cdp.ev(ACTIVE) is True)
    cdp.answer = True
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.8)
    check('accepting ends it without saving anything', cdp.ev(HIDDEN) is True and ids() == known and 'nothing was saved' in text('formFeedback'), text('formFeedback'))
    cdp.pause(0.6)
    check('no empty workout was queued either', safe_ev('readPendingWorkouts().length', -1) == 0)
    known = ids()
    open_tracker()
    cdp.goto(f'/index.html?start={W1}')
    cdp.wait(ACTIVE)
    cdp.pause(0.4)
    check('starting a saved workout prefills its own weight', field('activeWeight') == '100', field('activeWeight'))
    log(90, 8)
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(1.5)
    w = newest_workout(known)
    check('the saved weight comes from the sets, not the plan', w and w['exercises'][0]['weight'] == 90, json.dumps(w['exercises']) if w else 'none')
    old_skip = seed('Old Skip', 8, [ex('Curl', 50, 10, [])])
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length > 0")
    cdp.pause(0.4)
    skipped_text = cdp.ev("[...document.querySelectorAll('.history-workout')].find(li => li.textContent.includes('Old Skip')).textContent")
    check('older skipped exercises are labelled in History', 'Skipped' in skipped_text and '50 lbs' not in skipped_text, skipped_text)
    cdp.goto('/progress.html')
    cdp.wait('typeof chartData !== "undefined" && chartData && chartData.points.length > 0')
    keys = cdp.ev('chartData.points.map(p => p.key)')
    check('and are not charted as if they were done', str(old_skip) not in keys and len(keys) > 0, str(keys))

    # ---- F: feedback stays in view
    print('F   messages stay in view')
    # A short screen, so the workout (which has the page to itself) runs past the bottom of it.
    cdp.send('Emulation.setDeviceMetricsOverride', width=1024, height=420, deviceScaleFactor=1, mobile=False)
    open_tracker()
    start(0)
    cdp.pause(0.4)
    cdp.ev("document.getElementById('completedReps').value = ''; window.scrollTo(0, document.body.scrollHeight)")
    cdp.pause(0.3)
    cdp.ev("document.getElementById('completeSetBtn').click()")
    cdp.pause(0.3)
    box = cdp.ev("(() => { const f = document.getElementById('formFeedback'); const r = f.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, vh: innerHeight, scrolled: scrollY, position: getComputedStyle(f).position, hidden: f.hidden }; })()")
    check('a validation message is visible even when scrolled to the bottom', box['scrolled'] > 100 and not box['hidden'] and box['top'] >= 0 and box['bottom'] <= box['vh'], str(box))
    cdp.send('Emulation.clearDeviceMetricsOverride')
    cdp.pause(7)
    check('errors stay until dealt with', cdp.ev("!document.getElementById('formFeedback').hidden") is True)
    cdp.ev("document.getElementById('addActiveExercise').open = true; document.getElementById('activeAddName').value = 'Row'; document.getElementById('activeAddReps').value = '8'; document.getElementById('activeAddBtn').click()")
    cdp.pause(0.3)
    check('a success message appears', 'Added' in text('formFeedback') and 'success' in cdp.ev("document.getElementById('formFeedback').className"))
    cdp.pause(7)
    check('and clears itself', cdp.ev("document.getElementById('formFeedback').hidden") is True)
    cdp.ev("document.getElementById('completedReps').value = ''; document.getElementById('completeSetBtn').click()")
    cdp.pause(0.2)
    cdp.ev("document.getElementById('formFeedback').click()")
    check('an error can be dismissed with a tap', cdp.ev("document.getElementById('formFeedback').hidden") is True)
    cdp.ev("document.getElementById('completeSetBtn').click()")
    cdp.pause(0.2)
    check('and comes back if the mistake is repeated', cdp.ev("!document.getElementById('formFeedback').hidden") is True)
    cdp.ev("document.getElementById('settingsButton').click()")
    check('opening settings clears a stale message', cdp.ev("document.getElementById('formFeedback').hidden") is True)
    cdp.ev("document.getElementById('closeSettings').click()")
    no_confirm()
    end_workout()

    # ---- W: wording
    print('W   error wording')
    open_tracker()
    # A new workout is kept on the device offline (timer_and_sync's P14); a change to a saved one needs the server.
    cdp.ev("document.querySelector('#savedWorkoutList .saved-workout [data-action=edit]').click()")
    cdp.wait('exercises.length > 0')
    cdp.block_api = True
    cdp.ev("document.getElementById('saveBtn').click()")
    cdp.pause(1.0)
    fb = text('formFeedback')
    check('a failed save says what to do', 'connection' in fb and 'on this device' not in fb, fb)
    check('and the button works again for another go', cdp.ev("document.getElementById('saveBtn').disabled") is False)
    cdp.ev("document.getElementById('clearBtn').click()")
    cdp.goto('/history.html')
    cdp.pause(1.0)
    check('history says it could not load', text('historySummary') == 'Unable to load workouts.', text('historySummary'))
    cdp.goto('/progress.html')
    cdp.pause(1.0)
    check('progress says it could not load', text('chartEmpty') == 'Progress data could not be loaded.', text('chartEmpty'))
    cdp.block_api = False

    # ---- M: phone layout
    print('M   phone layout')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    open_tracker()
    start(0)
    cdp.pause(0.4)
    log(100, 8); log(100, 8)
    cdp.pause(0.4)
    cdp.ev("document.getElementById('completedSetsToggle').open = true")
    m = cdp.ev("""(() => { const inputs = [...document.querySelectorAll('#completedSets .set-edit')].map(i => i.getBoundingClientRect().width); const foot = document.querySelector('.footer-buttons').getBoundingClientRect(); return { overflow: document.documentElement.scrollWidth - innerWidth, minInput: Math.min(...inputs), footRight: foot.right, vw: innerWidth }; })()""")
    check('no sideways scrolling with editable sets', m['overflow'] <= 0, str(m))
    # A logged set is one line on a phone; each field still has room for "227.5" at full size beside its unit.
    check('set inputs are wide enough to use', m['minInput'] >= 70, str(m))
    # iOS Safari zooms the page in when a box with text under 16px is tapped.
    sizes = cdp.ev("[...document.querySelectorAll('#activeWorkout input:not([type=checkbox]), #activeWorkout textarea')].map(i => parseFloat(getComputedStyle(i).fontSize))")
    check('every box in a workout has 16px text, so tapping one does not zoom the page', min(sizes) >= 16, sizes)
    check('the Completed sets label says what was logged last', text('completedSetsSummary') == 'Completed sets (2) · last 100 lbs × 8', text('completedSetsSummary'))
    cdp.ev("document.getElementById('activeNotesToggle').open = true; document.getElementById('addActiveExercise').open = true")
    cdp.pause(0.2)
    small = cdp.ev("""[...document.querySelectorAll('#activeWorkout button, #activeWorkout summary, #activeWorkout a')]
        .filter(e => e.closest('details:not([open])') === null || e.parentElement.tagName === 'DETAILS' && e.tagName === 'SUMMARY')
        .map(e => ({ e, r: e.getBoundingClientRect() })).filter(({ r }) => r.width > 0 && r.height > 0)
        .filter(({ r }) => r.width < 44 || r.height < 44)
        .map(({ e, r }) => `${e.id || e.getAttribute('aria-label') || e.textContent.trim()} ${Math.round(r.width)}x${Math.round(r.height)}`)""")
    check('everything to tap in a workout is at least 44px, the size of a fingertip', small == [], small)
    cdp.ev("document.getElementById('activeNotesToggle').open = false; document.getElementById('addActiveExercise').open = false")
    # Typing into a prefilled weight or reps replaces it: a tap selects what is there. A headless page only gets focus
    # events with focus emulated.
    cdp.send('Emulation.setFocusEmulationEnabled', enabled=True)
    picked = cdp.ev("""new Promise(done => { const input = document.getElementById('activeWeight'); let selected = false;
        input.select = () => { selected = true; HTMLInputElement.prototype.select.call(input); };
        input.blur(); input.focus(); setTimeout(() => { delete input.select; input.blur(); done(selected); }, 50); })""")
    check('tapping the weight selects it, so typing replaces it', picked is True)
    cdp.send('Emulation.setFocusEmulationEnabled', enabled=False)
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    m = cdp.ev("(() => { const p = document.getElementById('prevExerciseBtn').getBoundingClientRect(); const n = document.getElementById('nextExerciseBtn').getBoundingClientRect(); return { prev: p.width, next: n.width, right: n.right, vw: innerWidth }; })()")
    check('Previous and Next fit side by side', m['prev'] > 40 and m['next'] > 40 and m['right'] <= m['vw'], str(m))
    cdp.send('Emulation.clearDeviceMetricsOverride')
    no_confirm()
    end_workout()

    # ---- E: session expiry
    print('E   session expiry')
    _, cookie_b = api('POST', '/api/auth/login', {'username': 'tester', 'password': 'chalk-and-plates-42'})
    token_b = cookie_b.split('session=')[1].split(';')[0]
    set_cookie(token_b)
    open_tracker()
    start(0)
    cdp.pause(0.6)
    api('POST', '/api/auth/logout', None, token_b)
    cdp.ev("fetch('/api/workouts'); fetch('/api/workouts'); fetch('/api/state')")
    check('an expired session shows a banner', cdp.wait("!!document.getElementById('sessionExpired')"), '')
    check('only one banner however many requests fail', cdp.ev("document.querySelectorAll('#sessionExpired').length") == 1)
    link = cdp.ev("document.querySelector('#sessionExpired a').getAttribute('href')")
    check('it links back to the current page after signing in', link == '/login.html?next=%2Findex.html', link)
    check('the page is left as it was', cdp.ev(ACTIVE) is True)
    log(100, 8)
    cdp.pause(0.6)
    check('sets logged after expiry are still kept on this device', cdp.ev('readLocalActive().session.exercises[0].sets.length') == 1)
    status, location = raw('GET', '/history.html?x=1')
    check('the server sends signed-out visitors to login with a way back', status == 303 and location == '/login.html?next=%2Fhistory.html%3Fx%3D1', f'{status} {location}')
    ui_login('?next=/history.html')
    check('signing in returns to the page you were on', cdp.ev('location.pathname') == '/history.html', cdp.ev('location.pathname'))
    # The last three look like paths, but the browser strips tabs and newlines from a URL, leaving //evil.example.
    for bad in ('https://evil.example/', '//evil.example', '/\\evil.example', 'javascript:alert(1)',
                '/\t/evil.example', '/\n/evil.example', '/\r/evil.example'):
        ui_login('?next=' + urllib.parse.quote(bad, safe=''))
        where = str(cdp.ev('location.hostname + location.pathname'))
        check(f'a crafted next ({bad!r}) stays on this site', where.startswith('127.0.0.1') and 'evil' not in where, where)
    set_cookie(token)
    open_tracker()
    cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn')?.click()")
    cdp.pause(0.6)

    # ---- O: signing out
    print('O   signing out')
    _, cookie_c = api('POST', '/api/auth/login', {'username': 'tester', 'password': 'chalk-and-plates-42'})
    token_c = cookie_c.split('session=')[1].split(';')[0]
    set_cookie(token_c)
    open_tracker()
    cdp.ev("document.getElementById('settingsButton').click()")
    check('the account name is shown', text('accountName') == 'Signed in as tester', text('accountName'))
    cdp.dialogs.clear()
    cdp.ev("document.getElementById('signOutButton').click()")
    check('signing out lands on the sign-in page', cdp.wait("location.pathname === '/login.html'"), cdp.ev('location.pathname'))
    check('without a warning when everything is synced', not cdp.dialogs, str(cdp.dialogs))
    check('and ends the session on the server', api('GET', '/api/auth/me', token=token_c)[0]['user'] is None)
    check('the app now requires signing in again', raw('GET', '/index.html')[0] == 303)

    ui_login()
    open_tracker()
    start(0)
    cdp.pause(0.6)
    log(100, 8)
    known = ids()
    cdp.block_api = True
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(0.6)
    cdp.dialogs.clear(); cdp.answer = True
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('signOutButton').click()")
    cdp.pause(0.8)
    check('cannot sign out while offline, and says so', cdp.ev('location.pathname') != '/login.html' and any('Could not sign out' in d for d in cdp.dialogs), str(cdp.dialogs))
    cdp.block_api = False
    check('the queued workout still uploads afterwards', wait_for(lambda: len(ids() - known) == 1), f'{len(ids() - known)} new')

    print('O2  signing out with work still waiting to sync')
    open_tracker()
    start(0)
    cdp.pause(0.6)
    log(100, 8)
    known = ids()
    cdp.block_paths = ['/api/workouts']
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click();")
    cdp.pause(0.8)
    check('a finished workout is waiting to sync', safe_ev('readPendingWorkouts().length', -1) == 1, safe_ev('readPendingWorkouts().length', -1))
    cdp.dialogs.clear(); cdp.answer = False
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('signOutButton').click()")
    cdp.pause(0.6)
    check('signing out warns about it', any('has not reached the server' in d for d in cdp.dialogs), str(cdp.dialogs))
    check('declining keeps you signed in', cdp.ev('location.pathname') != '/login.html')
    cdp.answer = True
    cdp.ev("document.getElementById('signOutButton').click()")
    check('accepting signs out', cdp.wait("location.pathname === '/login.html'"), cdp.ev('location.pathname'))
    pending_key = cdp.ev("Object.keys(localStorage).find(k => k.startsWith('workout-tracker-pending-'))")
    kept = safe_ev(f"JSON.parse(localStorage.getItem('{pending_key}') || '[]').length", -1) if pending_key else -1
    check('the unsent workout stays on this device', kept == 1 and len(ids() - known) == 0, f'pending={kept}, on server={len(ids() - known)}')
    cdp.block_paths = []
    ui_login()
    check('and uploads when the same account signs back in', wait_for(lambda: len(ids() - known) == 1), f'{len(ids() - known)} new')
    check('leaving nothing queued', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0), safe_ev('readPendingWorkouts().length', -1))
    set_cookie(token)

    # ---- R: the controls within reach
    print('R   the set entry, the rest timer and the plates where a thumb can reach them')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=740, deviceScaleFactor=1, mobile=True)
    open_tracker()
    if cdp.ev(ACTIVE):
        end_workout()
    start(0)  # Push Day: Bench Press, Overhead Press, Tricep Pushdown
    cdp.pause(0.6)

    def top(idn):
        return cdp.ev(f"document.getElementById('{idn}').getBoundingClientRect().top")

    check('weight, reps and Complete set come straight after the exercise',
          top('completeSetBtn') < top('activeNotesToggle'), f"set {top('completeSetBtn')} notes {top('activeNotesToggle')}")
    check('with no Completed sets until a set is logged', not visible('completedSetsToggle'))
    check('Complete set is on the first screen of a phone, above the tab bar',
          cdp.ev("document.getElementById('completeSetBtn').getBoundingClientRect().bottom <= document.querySelector('.site-nav').getBoundingClientRect().top") is True,
          cdp.ev("document.getElementById('completeSetBtn').getBoundingClientRect().bottom"))
    check('with the notes folded away', cdp.ev("document.getElementById('activeNotesToggle').open") is False)

    # A phone's header is the title and Settings; the pages are a tab bar along the bottom of the screen.
    bar = cdp.ev("(r => ({ top: r.top, bottom: r.bottom, vh: innerHeight, position: getComputedStyle(document.querySelector('.site-nav')).position }))"
                 "(document.querySelector('.site-nav').getBoundingClientRect())")
    check('on a phone the pages are a tab bar along the bottom', bar['position'] == 'fixed' and abs(bar['bottom'] - bar['vh']) < 1, bar)
    check("and the header leaves out the page's tagline", cdp.ev("getComputedStyle(document.querySelector('header .subtitle')).display") == 'none')

    def shown(selector):
        return cdp.ev(f"[...document.querySelectorAll('{selector}')].map(e => getComputedStyle(e).display !== 'none')")

    check('during a workout the rest of the Tracker is out of the way', shown('.between-workouts') == [False] * 4 and visible('otherCardsToggle')
          and shown('#otherCardsToggle') == [True], shown('.between-workouts'))
    cdp.ev("document.getElementById('otherCardsToggle').click()")
    check('one button under the workout brings it back', shown('.between-workouts')[2:] == [True, True]
          and text('otherCardsToggle') == 'Hide the rest of the Tracker', shown('.between-workouts'))
    cdp.ev("document.getElementById('otherCardsToggle').click()")
    check('and puts it away again', shown('.between-workouts') == [False] * 4, shown('.between-workouts'))

    # Swap, the note and the superset are in one menu beside the exercise's name.
    cdp.ev("document.getElementById('exerciseMenu').open = true")
    cdp.ev("document.getElementById('swapToggle').click()")
    cdp.pause(0.2)
    check("Swap is in the exercise's menu, which closes once it is picked",
          cdp.ev("document.getElementById('exerciseMenu').open") is False and visible('swapPanel'))
    cdp.ev("document.getElementById('swapCancel').click()")

    def set_weight(value):
        cdp.ev(f"(i => {{ i.value = '{value}'; i.dispatchEvent(new Event('input', {{ bubbles: true }})); }})(document.getElementById('activeWeight'))")

    def step(amount):
        cdp.ev(f"document.querySelector('#weightStepper [data-weight-step=\"{amount}\"]').click()")

    def plates():
        return None if cdp.ev("document.getElementById('plateHint').hidden") else text('plateHint')

    set_weight(100)
    step(5)
    check('+5 adds 5 lbs', field('activeWeight') == '105', field('activeWeight'))
    step(-5)
    step(-5)
    check('-5 takes 5 off', field('activeWeight') == '95', field('activeWeight'))
    set_weight(3)
    step(-5)
    check('never below nothing', field('activeWeight') == '0', field('activeWeight'))
    set_weight(187.5)
    step(5)
    check('and a half pound stays', field('activeWeight') == '192.5', field('activeWeight'))

    set_weight(135)
    check('Bench Press shows the plates for each side of the bar', plates() == 'Each side of a 45 lb bar: 45', plates())
    check('drawn as plates', cdp.ev("[...document.querySelectorAll('#plateHint .plate')].map(p => p.className)") == ['plate plate-size-0'])
    step(5)
    check('which follow the weight as it changes', plates() == 'Each side of a 45 lb bar: 45 + 2.5', plates())
    set_weight(190)
    check('down to the 2.5s', plates() == 'Each side of a 45 lb bar: 45 + 25 + 2.5', plates())
    check('each drawn to its size', cdp.ev("[...document.querySelectorAll('#plateHint .plate')].map(p => p.getBoundingClientRect().height)")
          == sorted(cdp.ev("[...document.querySelectorAll('#plateHint .plate')].map(p => p.getBoundingClientRect().height)"), reverse=True))
    set_weight(187.5)
    check('and the 1.25s a program rounded to 2.5 lbs needs', plates() == 'Each side of a 45 lb bar: 45 + 25 + 1.25', plates())
    set_weight(187)
    check('and a weight the plates cannot make says what they do make', plates() == 'Each side of a 45 lb bar: 45 + 25 (makes 185 lbs)', plates())
    set_weight(45)
    check('just the bar', plates() == 'Just the 45 lb bar', plates())
    set_weight(40)
    check('nothing under the weight of the bar', plates() is None, plates())

    # Settings' Bar and plates: a gym with a 35 lb bar, 15s and no 1.25s, and a weight step of 2.5 lbs.
    def change(selector, value=None):
        set_value = f"e.value = {json.dumps(value)};" if value is not None else 'e.checked = !e.checked;'
        cdp.ev(f"(e => {{ {set_value} e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})(document.querySelector({json.dumps(selector)}))")

    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings shows the bar and plates there are, 45 lbs and 45s down to 1.25s by default',
          field('barSetting') == '45' and cdp.ev("[...document.querySelectorAll('#plateSetting input:checked')].map(i => i.value)")
          == ['45', '35', '25', '10', '5', '2.5', '1.25'] and field('stepSetting') == '5')
    change('#barSetting', '35')
    change('#plateSetting input[value="1.25"]')
    change('#plateSetting input[value="15"]')
    change('#stepSetting', '2.5')
    cdp.ev("document.getElementById('doneSettings').click()")
    cdp.pause(0.2)
    kept = cdp.ev("(s => [s.barLbs, s.platesLbs, s.stepLbs, s.barKg])(getWorkoutSettings())")
    check('they are kept in Settings, the kilogram bar untouched', kept == [35, [45, 35, 25, 15, 10, 5, 2.5], 2.5, 20], kept)
    set_weight(135)
    check('the plates are for that bar', plates() == 'Each side of a 35 lb bar: 45 + 5', plates())
    step(2.5)
    check('the weight buttons go up by the step chosen', field('activeWeight') == '137.5'
          and cdp.ev("document.querySelector('#weightStepper [data-weight-step]').textContent") == '−2.5', field('activeWeight'))
    check('and with no 1.25s, the plates say what they do make', plates() == 'Each side of a 35 lb bar: 45 + 5 (makes 135 lbs)', plates())
    set_weight(35)
    check('just the bar is the 35 lb one', plates() == 'Just the 35 lb bar', plates())
    fewest = cdp.ev("platesPerSide(28, { unit: 'kg', bar: 20, plates: [25, 20, 15, 10, 5, 2.5, 2], step: 2.5 })")
    check('the fewest plates that make a weight, not just the heaviest first: two 2s for 4 kg a side',
          fewest == {'plates': [2, 2], 'makes': 28}, fewest)

    cdp.ev("document.getElementById('settingsButton').click()")
    change('#unitSetting', 'kg')
    in_kg = cdp.ev("""({ bar: document.getElementById('barSetting').value, unit: document.querySelector('[data-equipment-unit]').textContent,
        plates: [...document.querySelectorAll('#plateSetting input')].map(i => i.value), step: document.getElementById('stepSetting').value })""")
    check('in kilograms, the kilogram bar and plates', in_kg == {'bar': '20', 'unit': 'kg', 'step': '2.5',
          'plates': ['25', '20', '15', '10', '5', '2.5', '2', '1.25', '1', '0.5']}, in_kg)
    change('#unitSetting', 'lbs')
    check('and back in pounds, the pound ones as they were', field('barSetting') == '35' and field('stepSetting') == '2.5', field('barSetting'))
    change('#barSetting', '500')
    check('a bar that heavy is not kept', field('barSetting') == '35' and cdp.ev('getWorkoutSettings().barLbs') == 35, field('barSetting'))
    for plate in ('45', '35', '25', '15', '10', '5'):
        change(f'#plateSetting input[value="{plate}"]')
    last = cdp.ev("[...document.querySelectorAll('#plateSetting input:checked')].map(i => [i.value, i.disabled])")
    check('the last plate cannot be taken away', last == [['2.5', True]], last)
    cdp.ev("document.getElementById('doneSettings').click()")
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), barLbs: 45, platesLbs: [45, 35, 25, 10, 5, 2.5, 1.25], stepLbs: 5 });"
           "window.dispatchEvent(new Event('settingschange'))")
    judged = cdp.ev("""['Bench Press', 'Back Squat', 'Deadlift', 'Overhead Press', 'Barbell Row', 'Romanian Deadlift',
        'Dumbbell Bench Press', 'Leg Press', 'Goblet Squat', 'Lat Pulldown', 'Tricep Pushdown', 'Bench Dips']
        .filter(name => isBarbellExercise({ name }))""")
    check('only barbell lifts get plates, going by their names',
          judged == ['Bench Press', 'Back Squat', 'Deadlift', 'Overhead Press', 'Barbell Row', 'Romanian Deadlift'], judged)
    cdp.ev("document.getElementById('nextExerciseBtn').click(); document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    set_weight(100)
    check('so the Tricep Pushdown gets none', text('activeExerciseName') == 'Tricep Pushdown' and plates() is None, plates())

    log(100, 8)
    cdp.pause(0.4)
    check('the rest timer comes up right under the set entry', visible('restPanel') and top('completeSetBtn') < top('restPanel') < top('completedSetsToggle'))
    check('and the set logged folds away under Completed sets, with its count',
          visible('completedSetsToggle') and cdp.ev("document.getElementById('completedSetsToggle').open") is False
          and text('completedSetsSummary').startswith('Completed sets (1) · last '), text('completedSetsSummary'))
    cdp.ev("document.getElementById('completedSetsToggle').open = true")
    cdp.ev("document.getElementById('completedSets').scrollIntoView({ block: 'start' })")
    cdp.pause(0.3)
    pinned = cdp.ev("(r => ({ top: r.top, bottom: r.bottom, vh: innerHeight }))(document.getElementById('restPanel').getBoundingClientRect())")
    check('and stays on screen while the page scrolls past it', pinned['top'] >= 0 and pinned['bottom'] <= pinned['vh'], pinned)
    # The list of exercises open above it pushes it off the bottom of a short screen, where it waits above the tab bar.
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=600, deviceScaleFactor=1, mobile=True)
    cdp.ev("document.getElementById('activeWorkoutProgress').click(); document.getElementById('addActiveExercise').open = true; scrollTo(0, 0)")
    cdp.pause(0.3)
    pinned = cdp.ev("(r => ({ top: r.top, bottom: r.bottom, bar: document.querySelector('.site-nav').getBoundingClientRect().top,"
                    " below: document.getElementById('completedSetsToggle').getBoundingClientRect().top }))(document.getElementById('restPanel').getBoundingClientRect())")
    check('or scrolled above it, at the bottom of the screen over the tab bar', pinned['below'] > pinned['bar'] and 0 <= pinned['top'] and pinned['bottom'] <= pinned['bar'], pinned)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=740, deviceScaleFactor=1, mobile=True)
    end_workout()
    check('once the workout ends the rest of the Tracker is back', shown('.between-workouts')[2:] == [True, True] and not cdp.ev("getComputedStyle(document.getElementById('otherCardsToggle')).display !== 'none'"),
          shown('.between-workouts'))

    noted = api('POST', '/api/workouts', {'name': 'Noted Day', 'notes': 'Pause the reps.', 'createdAt': t.t0 + 7 * 86400000,
                                          'exercises': [ex('Bench Press', 135, 5, [(5, 135)])]}, token)[0]['id']
    cdp.goto(f'/index.html?start={noted}')
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.pause(0.3)
    check("a workout that brings notes with it opens them", cdp.ev("document.getElementById('activeNotesToggle').open") is True
          and field('activeNotes') == 'Pause the reps.', field('activeNotes'))
    end_workout()
    cdp.send('Emulation.clearDeviceMetricsOverride')

    # ---- U: undoing a removed set
    print('U   a removed set can be put back')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    log(100, 8); log(105, 6); log(110, 4)
    cdp.pause(0.3)

    def remove_set(index):
        cdp.ev(f"document.querySelector('#completedSets [data-remove-set=\"{index}\"]').click()")
        cdp.pause(0.2)

    def undo():
        cdp.ev("document.querySelector('#formFeedback .feedback-action').click()")
        cdp.pause(0.2)

    def local_sets(exercise=0):
        return safe_ev(f'readLocalActive().session.exercises[{exercise}].sets.map(s => [s.weight, s.reps])', [])

    remove_set(1)
    check('Remove takes the set away at once', [r['weight'] for r in rows()] == ['100', '110'] and local_sets() == [[100, 8], [110, 4]], f'{rows()} {local_sets()}')
    banner = cdp.ev("(() => { const f = document.getElementById('formFeedback'); const b = f.querySelector('.feedback-action'); return { text: f.textContent, kind: f.className, button: b && b.textContent, shown: !f.hidden }; })()")
    check('the banner says which set went, and offers Undo', banner['shown'] and banner['text'].startswith('Removed set 2 of Bench Press (105 lbs × 6).')
          and banner['button'] == 'Undo' and 'info' in banner['kind'], banner)
    undo()
    check('Undo puts it back in its place', [(r['label'], r['weight'], r['reps']) for r in rows()] == [('Set 1', '100', '8'), ('Set 2', '105', '6'), ('Set 3', '110', '4')], rows())
    check('and says so', text('formFeedback') == 'Set 2 of Bench Press is back.' and cdp.ev("!document.querySelector('#formFeedback .feedback-action')") is True, text('formFeedback'))
    check('the restored set is saved on this device', local_sets() == [[100, 8], [105, 6], [110, 4]], local_sets())
    check('and reaches the server', wait_for(lambda: (server_session() or {}).get('exercises', [{}])[0].get('sets', []) == [{'reps': 8, 'weight': 100}, {'reps': 6, 'weight': 105}, {'reps': 4, 'weight': 110}]),
          (server_session() or {}).get('exercises', [{}])[0].get('sets'))

    remove_set(2)
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    undo()
    check('Undo after moving on restores the set to its own exercise', local_sets(0) == [[100, 8], [105, 6], [110, 4]]
          and cdp.ev('activeSession.currentIndex') == 1 and text('activeExerciseName') == 'Overhead Press', f"{local_sets(0)} {text('activeExerciseName')}")
    cdp.ev("document.getElementById('prevExerciseBtn').click()")
    cdp.pause(0.3)
    check('where it shows again', len(rows()) == 3, rows())

    remove_set(0)
    cdp.ev("document.getElementById('formFeedback').click()")
    cdp.pause(0.2)
    check('dismissing the banner lets the removal stand', cdp.ev("document.getElementById('formFeedback').hidden") is True and local_sets() == [[105, 6], [110, 4]], local_sets())
    remove_set(0)
    log(120, 3)
    check('a new message replaces the offer', cdp.ev("!document.querySelector('#formFeedback .feedback-action')") is True and local_sets() == [[110, 4], [120, 3]], local_sets())

    remove_set(0)
    no_confirm()
    end_workout()
    check("cancelling the workout replaces the set's offer with the workout's own", text('formFeedback').startswith('“Push Day” was cancelled.')
          and cdp.ev("document.getElementById('activeWorkout').hidden") is True, text('formFeedback'))
    undo()
    check('whose Undo brings the workout back as it was cancelled, the removed set still gone',
          text('formFeedback') == '“Push Day” is back.' and local_sets() == [[120, 3]], [text('formFeedback'), local_sets()])
    end_workout()
