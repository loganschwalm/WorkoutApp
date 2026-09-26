"""Rest timer accuracy, the screen wake lock, and saving through a network drop."""

import json
import time

from ..harness import ACTIVE, DISPLAY, HIDDEN, TITLE, TOGGLE

INTERCEPT = True


def seconds(text):
    minutes, secs = text.split(':')
    return int(minutes) * 60 + int(secs)


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    ex, workouts = t.ex, t.workouts
    safe_ev, wait_for = t.safe_ev, t.wait_for
    start, log_set, open_tracker = t.start, t.log_set, t.open_tracker
    server_sets, finish_all, end_workout = t.server_sets, t.finish_all, t.end_workout

    # ------------------------------------------------------------------ rest timer
    print('R   rest timer follows the clock, not the tick count')
    open_tracker()
    cdp.ev("""window.__offset = 0; const realNow = Date.now.bind(Date); Date.now = () => realNow() + window.__offset;
      window.__vib = []; navigator.vibrate = p => { window.__vib.push(p); return true; };
      window.__osc = 0; const co = AudioContext.prototype.createOscillator; AudioContext.prototype.createOscillator = function () { window.__osc++; return co.call(this); };""")
    start(0)
    cdp.pause(0.5)
    log_set(8)
    cdp.pause(0.3)
    d = safe_ev(DISPLAY, '?')
    check('rest starts at the configured duration', d in ('1:30', '1:29'), d)
    cdp.pause(2.3)
    d = seconds(safe_ev(DISPLAY, '0:00'))
    check('counts down in real time', 86 <= d <= 88, d)
    cdp.ev('window.__offset = 45000')
    cdp.pause(0.7)
    d = seconds(safe_ev(DISPLAY, '0:00'))
    check('catches up after a stalled timer (clock jumped 45s)', 38 <= d <= 43, d)
    d = seconds(cdp.ev("window.__offset = 60000; document.dispatchEvent(new Event('visibilitychange')); document.getElementById('timerDisplay').textContent"))
    check('returning to the page updates the display immediately', 22 <= d <= 29, d)
    cdp.ev('window.__offset = 200000')
    cdp.pause(0.7)
    check('timer stops at 0:00 when the time is up', cdp.ev(DISPLAY) == '0:00' and cdp.ev(TOGGLE) == 'Start rest', f'{cdp.ev(DISPLAY)} / {cdp.ev(TOGGLE)}')
    check('vibrates when rest is over', cdp.ev('window.__vib.length') >= 1, cdp.ev('window.__vib.length'))
    check('beeps when rest is over', cdp.ev('window.__osc') >= 2, cdp.ev('window.__osc'))
    cdp.ev("document.getElementById('restToggleBtn').click()")
    cdp.pause(0.3)
    check('"Start rest" at 0:00 restarts the full duration', cdp.ev(DISPLAY) in ('1:30', '1:29') and cdp.ev(TOGGLE) == 'Pause rest', f'{cdp.ev(DISPLAY)} / {cdp.ev(TOGGLE)}')
    cdp.ev("document.getElementById('restToggleBtn').click()")
    v1 = seconds(cdp.ev(DISPLAY))
    cdp.ev('window.__offset += 30000')
    cdp.pause(0.7)
    check('pausing freezes the countdown', cdp.ev(TOGGLE) == 'Start rest' and seconds(cdp.ev(DISPLAY)) == v1, f'{cdp.ev(DISPLAY)} vs {v1}')
    cdp.ev("document.getElementById('restToggleBtn').click(); window.__offset += 10000")
    cdp.pause(0.7)
    d = seconds(cdp.ev(DISPLAY))
    check('resuming continues from the paused value', v1 - 11 <= d <= v1 - 10, f'{d} vs paused {v1}')
    end_workout()

    print('W   screen stays awake during a workout')
    open_tracker()
    cdp.ev("""window.__lock = { requests: 0, releases: 0 };
      Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async () => {
        window.__lock.requests++; const listeners = [];
        return { addEventListener: (t, f) => listeners.push(f), release: async () => { window.__lock.releases++; listeners.forEach(f => f()); } };
      } } });""")
    start(0)
    cdp.pause(0.5)
    check('requests a wake lock when a workout starts', cdp.ev('window.__lock.requests') == 1, cdp.ev('window.__lock.requests'))
    cdp.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'))")
    cdp.pause(0.4)
    check('releases it when the page is hidden', cdp.ev('window.__lock.releases') == 1, cdp.ev('window.__lock.releases'))
    cdp.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange'))")
    cdp.pause(0.4)
    check('re-acquires it when the page is visible again', cdp.ev('window.__lock.requests') == 2, cdp.ev('window.__lock.requests'))
    end_workout()
    check('releases it when the workout ends', cdp.ev('window.__lock.releases') == 2, cdp.ev('window.__lock.releases'))

    # ------------------------------------------------------------------ offline
    print('P1  sets logged while the server is unreachable')
    open_tracker()
    start(0)
    cdp.pause(1.0)
    check('server has the started workout', server_sets() == 0, server_sets())
    cdp.block_api = True
    log_set(8); log_set(8)
    cdp.pause(1.5)
    check('server has not seen the offline sets', server_sets() == 0, server_sets())
    check('user is told the sets are saved on this device', safe_ev("!document.getElementById('activeSyncNotice').hidden", False) is True)
    cdp.block_api = False
    check('sets sync automatically once the server is back', wait_for(lambda: server_sets() == 2), server_sets())
    cdp.pause(0.5)
    check('notice clears after syncing', safe_ev("document.getElementById('activeSyncNotice').hidden", False) is True)

    print('P2  reloading the page while the server is unreachable')
    cdp.block_api = True
    log_set(6)
    cdp.pause(1.0)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    check('workout is restored from this device', cdp.wait(ACTIVE), '')
    cdp.pause(0.8)
    shown = cdp.ev("document.querySelectorAll('#completedSets li').length")
    check('all three logged sets are still there', shown == 3, shown)
    check('page says the server is unreachable', 'unreachable' in (cdp.ev("document.getElementById('storageStatus').textContent") or '').lower(), cdp.ev("document.getElementById('storageStatus').textContent"))
    check('server still has only the first two sets', server_sets() == 2, server_sets())
    cdp.block_api = False
    check('third set reaches the server later', wait_for(lambda: server_sets() == 3), server_sets())

    print('P3  finishing a workout while the server is unreachable')
    before_ids = {w['id'] for w in workouts()}
    cdp.block_api = True
    finish_all()
    cdp.pause(0.5)
    check('workout ends normally', cdp.ev(HIDDEN) is True)
    fb = cdp.ev("document.getElementById('formFeedback').textContent") or ''
    check('user is told it is saved on this device', 'saved on this device' in fb, fb)
    check('workout is queued locally', safe_ev('readPendingWorkouts().length', -1) == 1, safe_ev('readPendingWorkouts().length', -1))
    check('page shows a workout waiting to sync', 'waiting to sync' in (cdp.ev("document.getElementById('storageStatus').textContent") or ''), cdp.ev("document.getElementById('storageStatus').textContent"))
    check('server has not got it yet', {w['id'] for w in workouts()} == before_ids)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(1.0)
    check('queued workout survives a reload', safe_ev('readPendingWorkouts().length', -1) == 1, safe_ev('readPendingWorkouts().length', -1))
    check('finished workout is not resurrected as active', cdp.ev(HIDDEN) is True)
    cdp.block_api = False
    check('workout uploads once the server is back', wait_for(lambda: len({w['id'] for w in workouts()} - before_ids) == 1), '')
    created = [w for w in workouts() if w['id'] not in before_ids]
    check('uploaded workout has every set', created and sum(len(e['sets']) for e in created[0]['exercises']) == 3, json.dumps(created[0]['exercises']) if created else 'none')
    check('local queue is empty afterwards', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0), safe_ev('readPendingWorkouts().length', -1))
    check('server no longer has an active workout', wait_for(lambda: server_sets() is None), server_sets())
    uploaded = created[0]['id'] if created else None
    check('saved-workouts list refreshes on its own', wait_for(lambda: cdp.ev(f"!!document.querySelector('#savedWorkoutList .saved-workout[data-id=\"{uploaded}\"]')") is True),
          cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout')].map(li => li.dataset.id)"))

    print('P4  a retried upload never duplicates a workout')
    body = {'name': 'Dupe Check', 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': 'abc123', 'exercises': [ex('Squat', 100, 5, [(5, 100)])]}
    n = len(workouts())
    first, _ = api('POST', '/api/workouts', body, token)
    second, _ = api('POST', '/api/workouts', body, token)
    check('same clientId returns the same workout', first['id'] == second['id'], f'{first} {second}')
    check('only one copy is stored', len(workouts()) == n + 1, f'{n} -> {len(workouts())}')
    _, other_cookie = api('POST', '/api/auth/register', {'username': 'other', 'email': 'other@example.test', 'password': 'password123'})
    other_token = other_cookie.split('session=')[1].split(';')[0]
    third, _ = api('POST', '/api/workouts', body, other_token)
    check('another account can reuse a clientId', third['id'] != first['id'])

    print('P5  upload succeeded but the response was lost')
    open_tracker()
    start(1)
    cdp.pause(0.6)
    log_set(5)
    n = len(workouts())
    cdp.drop_responses = 1
    finish_all()
    check('local queue drains after the retry', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0, 15), safe_ev('readPendingWorkouts().length', -1))
    check('the first response really was dropped', cdp.dropped == 1, cdp.dropped)
    check('server stored exactly one copy', len(workouts()) == n + 1, f'{n} -> {len(workouts())}')

    print('P6  another account on the same browser')
    me_id = api('GET', '/api/auth/me', token=token)[0]['user']['id']
    open_tracker()
    ghost = {'name': 'Ghost Workout', 'notes': '', 'exercises': [{'name': 'Squat', 'weight': 100, 'reps': '5', 'sets': [{'reps': 5, 'weight': 100}]}], 'currentIndex': 0, 'clientId': 'ghost'}
    cdp.ev(f"localStorage.setItem('workout-tracker-active-{me_id}', JSON.stringify({{ session: {json.dumps(ghost)}, dirty: true, stamp: 'ghost-1' }}))")
    cdp.send('Network.setCookie', name='session', value=other_token, domain='127.0.0.1', path='/')
    cdp.goto('/index.html')
    cdp.pause(2.5)
    check("other account does not see the first account's local workout", cdp.ev(HIDDEN) is True)
    check("first account's workout was not uploaded to the other account", api('GET', '/api/active-session', token=other_token)[0]['session'] is None)
    check("first account's local copy is left alone", 'Ghost Workout' in (cdp.ev(f"localStorage.getItem('workout-tracker-active-{me_id}')") or ''))
    cdp.send('Network.setCookie', name='session', value=token, domain='127.0.0.1', path='/')
    cdp.goto('/index.html')
    check('first account gets its unsynced workout back', cdp.wait(f"{ACTIVE} && {TITLE} === 'Ghost Workout'"), cdp.ev(TITLE))
    def ghost_on_server():
        s = api('GET', '/api/active-session', token=token)[0]['session']
        return bool(s) and s['name'] == 'Ghost Workout'
    check('and syncs it to the server', wait_for(ghost_on_server))
    end_workout()
    check('ending it clears the server copy', wait_for(lambda: server_sets() is None), server_sets())

    print('P7  History page uploads pending workouts before listing')
    open_tracker()
    start(0)
    cdp.pause(0.8)
    log_set(8)
    cdp.block_api = True
    finish_all()
    cdp.pause(0.4)
    n = len(workouts())
    check('workout is waiting locally', safe_ev('readPendingWorkouts().length', -1) == 1, safe_ev('readPendingWorkouts().length', -1))
    cdp.block_api = False
    cdp.goto('/history.html')
    check('history shows the workout without visiting the tracker', cdp.wait(f"document.querySelectorAll('.history-workout').length === {n + 1}"), cdp.ev("document.querySelectorAll('.history-workout').length"))
    check('server has it', len(workouts()) == n + 1, len(workouts()))

    print('P8  a workout the server refuses does not hold up the ones behind it')
    open_tracker()
    n = len(workouts())
    # A queued workout the server will never accept (as if written by a buggy older build), then a normal one.
    broken = {'name': 'Broken', 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': 'broken-1', 'exercises': 'not a list'}
    fine = {'name': 'Behind It', 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': 'behind-1',
            'exercises': [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}]}]}
    cdp.ev(f"queuePendingWorkout({json.dumps(broken)}); queuePendingWorkout({json.dumps(fine)})")
    flushed = cdp.ev('flushPendingWorkouts()')
    names = [w['name'] for w in workouts()]
    check('the flush finishes', flushed is True, flushed)
    check('the workout behind it is uploaded', 'Behind It' in names and len(names) == n + 1, names[:5])
    check('the refused one is not stored', 'Broken' not in names)
    check('nothing is left in the upload queue', safe_ev('readPendingWorkouts().length', -1) == 0)
    kept = safe_ev('readRejectedWorkouts().map(w => w.name)', [])
    check('the refused one is kept on this device', kept == ['Broken'], kept)
    cdp.pause(0.5)
    status = cdp.ev("document.getElementById('storageStatus').textContent")
    check('and the status line says so', 'refused by the server' in status, status)

    print('R2  30 seconds more or less rest')
    open_tracker()
    cdp.ev("""window.__offset = 0; const realNow = Date.now.bind(Date); Date.now = () => realNow() + window.__offset;
      window.__vib = []; navigator.vibrate = p => { window.__vib.push(p); return true; };
      window.__osc = 0; const co = AudioContext.prototype.createOscillator; AudioContext.prototype.createOscillator = function () { window.__osc++; return co.call(this); };""")
    start(0)
    cdp.pause(0.5)
    log_set(8)
    cdp.pause(0.3)

    def adjust(seconds, times=1):
        cdp.ev(f"for (let i = 0; i < {times}; i += 1) document.querySelector('#restAdjust [data-rest-adjust=\"{seconds}\"]').click()")
        cdp.pause(0.2)

    labels = cdp.ev("[...document.querySelectorAll('#restAdjust button')].map(b => [b.textContent, b.getAttribute('aria-label')])")
    check('the rest panel offers 30 seconds less and more', labels == [['−30s', '30 seconds less rest'], ['+30s', '30 seconds more rest']], labels)
    adjust(30)
    d = seconds(cdp.ev(DISPLAY))
    check('+30s while resting adds half a minute', 118 <= d <= 120, d)
    cdp.ev('window.__offset += 10000')
    cdp.pause(0.6)
    d = seconds(cdp.ev(DISPLAY))
    check('and the countdown carries on from there', 108 <= d <= 110 and cdp.ev(TOGGLE) == 'Pause rest', d)
    adjust(-30)
    d = seconds(cdp.ev(DISPLAY))
    check('minus 30s takes half a minute off', 78 <= d <= 80, d)
    cdp.ev("document.getElementById('restToggleBtn').click()")
    paused = seconds(cdp.ev(DISPLAY))
    adjust(30)
    cdp.ev('window.__offset += 20000')
    cdp.pause(0.6)
    check('paused, +30s adds to the paused time, which stays put', seconds(cdp.ev(DISPLAY)) == paused + 30 and cdp.ev(TOGGLE) == 'Start rest', f'{cdp.ev(DISPLAY)} vs {paused}')
    cdp.ev("document.getElementById('restToggleBtn').click(); window.__offset += 5000")
    cdp.pause(0.6)
    d = seconds(cdp.ev(DISPLAY))
    check('and resuming counts down from the new time', paused + 24 <= d <= paused + 25, f'{d} vs {paused + 25}')
    cdp.ev('window.__osc = 0; window.__vib = []')
    adjust(-30, 6)
    check('taking it down to nothing ends the rest', cdp.ev(DISPLAY) == '0:00' and cdp.ev(TOGGLE) == 'Start rest', f'{cdp.ev(DISPLAY)} / {cdp.ev(TOGGLE)}')
    cdp.pause(0.6)
    check('quietly: no beep and no vibration', cdp.ev('window.__osc') == 0 and cdp.ev('window.__vib.length') == 0, f"{cdp.ev('window.__osc')} {cdp.ev('window.__vib.length')}")
    adjust(30)
    check('+30s at 0:00 sets up 30 seconds', cdp.ev(DISPLAY) == '0:30' and cdp.ev(TOGGLE) == 'Start rest', cdp.ev(DISPLAY))
    cdp.ev("document.getElementById('restToggleBtn').click()")
    cdp.pause(0.3)
    d = seconds(cdp.ev(DISPLAY))
    check('which Start rest then counts down', 29 <= d <= 30 and cdp.ev(TOGGLE) == 'Pause rest', d)
    cdp.ev('window.__offset += 31000')
    cdp.pause(0.7)
    check('and alerts at the end like any rest', cdp.ev(DISPLAY) == '0:00' and cdp.ev('window.__osc') >= 2, f"{cdp.ev(DISPLAY)} {cdp.ev('window.__osc')}")
    adjust(30, 150)
    check('rest tops out at an hour', cdp.ev(DISPLAY) == '60:00', cdp.ev(DISPLAY))
    adjust(-30, 200)
    check('and cannot go below zero', cdp.ev(DISPLAY) == '0:00', cdp.ev(DISPLAY))
    end_workout()
