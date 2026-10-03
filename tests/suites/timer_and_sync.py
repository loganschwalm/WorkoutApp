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
    check('and says nothing about the screen while it can keep it on', cdp.ev("document.getElementById('screenAwakeNotice').hidden") is True)

    print('W2  where the screen cannot be kept on, the workout says so')
    NOTICE = "document.getElementById('screenAwakeNotice')"
    # A plain http:// address, as a server on the local network is: no Wake Lock API, and not a secure context.
    plain_http = cdp.send('Page.addScriptToEvaluateOnNewDocument', source="""
      delete Navigator.prototype.wakeLock;
      Object.defineProperty(window, 'isSecureContext', { configurable: true, get: () => false });""")['result']['identifier']
    open_tracker()
    check('nothing is said before a workout starts', cdp.ev(f'{NOTICE}.hidden') is True)
    start(0)
    cdp.pause(0.4)
    check('during one, it says a locked phone cannot sound the rest alert', cdp.ev(f'!{NOTICE}.hidden') is True
          and 'locked phone cannot sound the rest alert' in cdp.ev(f'{NOTICE}.textContent'), cdp.ev(f'{NOTICE}.textContent'))
    check('why: a plain http:// address, and what to do about it', all(words in cdp.ev(f'{NOTICE}.textContent') for words in ('http://', 'Auto-Lock', 'HTTPS')),
          cdp.ev(f'{NOTICE}.textContent'))
    end_workout()
    check('and it goes when the workout ends', cdp.ev(f'{NOTICE}.hidden') is True)

    print('W3  without a Wake Lock, a silent video keeps the screen on instead')
    # What the video is asked to do is recorded, rather than relying on the test browser playing H.264.
    video_spy = cdp.send('Page.addScriptToEvaluateOnNewDocument', source="""
      window.__video = { plays: 0, pauses: 0 };
      HTMLMediaElement.prototype.play = function () { window.__video.plays++; Object.defineProperty(this, 'paused', { configurable: true, get: () => false }); return Promise.resolve(); };
      HTMLMediaElement.prototype.pause = function () { window.__video.pauses++; Object.defineProperty(this, 'paused', { configurable: true, get: () => true }); };""")['result']['identifier']
    open_tracker()
    check('nothing plays before a workout', cdp.ev('window.__video.plays') == 0)
    check('Settings offers to turn it off, ticked', cdp.ev("!document.getElementById('keepAwakeSettingRow').hidden && document.getElementById('keepAwakeSetting').checked") is True)
    start(0)
    cdp.pause(0.4)
    check('starting a workout plays it', cdp.ev('window.__video.plays') >= 1, cdp.ev('window.__video'))
    check('the bundled video, muted and inline', cdp.ev("keepAwakeVideo.getAttribute('src') === '/media/keep-awake.mp4' && keepAwakeVideo.muted && keepAwakeVideo.hasAttribute('playsinline')") is True)
    check('not looping, which Safari would let the screen sleep under', cdp.ev('keepAwakeVideo.loop') is False)
    cdp.ev("Object.defineProperty(keepAwakeVideo, 'currentTime', { configurable: true, get: () => 1.4, set: value => { window.__seekedTo = value; } });"
           "keepAwakeVideo.dispatchEvent(new Event('timeupdate'))")
    check('instead it is sent back to its start before it ends', cdp.ev('window.__seekedTo') == 0, cdp.ev('window.__seekedTo'))
    check('and the note says so, with what to do if the phone locks anyway', 'silent video' in cdp.ev(f'{NOTICE}.textContent')
          and all(words in cdp.ev(f'{NOTICE}.textContent') for words in ('locked phone cannot sound the rest alert', 'Auto-Lock', 'HTTPS')), cdp.ev(f'{NOTICE}.textContent'))
    cdp.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'))")
    cdp.pause(0.3)
    check('it stops while the page is hidden', cdp.ev('window.__video.pauses') >= 1 and cdp.ev('keepAwakeVideo.paused') is True, cdp.ev('window.__video'))
    cdp.ev("window.__video.plays = 0; Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange'))")
    cdp.pause(0.3)
    check('and plays again when it is back', cdp.ev('window.__video.plays') >= 1, cdp.ev('window.__video'))
    cdp.ev("window.__video.plays = 0")
    log_set(8)
    check('each set logged asks again, in case the phone refused at first', cdp.ev('window.__video.plays') >= 1, cdp.ev('window.__video'))
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('keepAwakeSetting').click(); document.getElementById('closeSettings').click()")
    cdp.pause(0.3)
    check('turned off in Settings, it stops at once', cdp.ev('keepAwakeVideo.paused') is True and 'silent video' not in cdp.ev(f'{NOTICE}.textContent'),
          cdp.ev(f'{NOTICE}.textContent'))
    cdp.ev("window.__video.plays = 0")
    log_set(8)
    check('and stays off', cdp.ev('window.__video.plays') == 0, cdp.ev('window.__video'))
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('keepAwakeSetting').click(); document.getElementById('closeSettings').click()")
    cdp.pause(0.3)
    end_workout()
    check('ending the workout stops it', cdp.ev('keepAwakeVideo.paused') is True)
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=plain_http)
    open_tracker()
    check('with a Wake Lock, Settings does not offer it', cdp.ev("document.getElementById('keepAwakeSettingRow').hidden") is True)
    cdp.ev("""Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async () => ({ addEventListener() {}, release: async () => {} }) } })""")
    start(0)
    cdp.pause(0.4)
    check('and plays no video', cdp.ev('window.__video.plays') == 0 and cdp.ev('keepAwakeVideo') is None, cdp.ev('window.__video'))
    end_workout()
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=video_spy)
    open_tracker()
    cdp.ev("Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async () => { throw new DOMException('no', 'NotAllowedError'); } } })")
    start(0)
    cdp.pause(0.4)
    check('a browser that refuses the lock over HTTPS gets the note too, without the http:// advice', cdp.ev(f'!{NOTICE}.hidden') is True
          and 'http://' not in cdp.ev(f'{NOTICE}.textContent') and 'locked phone' in cdp.ev(f'{NOTICE}.textContent'), cdp.ev(f'{NOTICE}.textContent'))
    end_workout()
    check('which goes with the workout as well', cdp.ev(f'{NOTICE}.hidden') is True)

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
    _, other_cookie = api('POST', '/api/auth/register', {'username': 'other', 'email': 'other@example.test', 'password': 'chalk-and-plates-42'})
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

    print('P9  reloading mid-workout on a connection that stalls instead of failing')
    open_tracker()
    start(0)
    cdp.pause(0.6)
    log_set(8)
    check('the set reaches the server first', wait_for(lambda: server_sets() == 1), server_sets())
    cdp.stall_paths = ['/api/workouts', '/api/active-session']
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    check('the workout is back on screen without waiting for the server', cdp.wait(ACTIVE, 6))
    shown = safe_ev("document.querySelectorAll('#completedSets li').length", 0)
    check('with its logged set', shown == 1, shown)
    check('the server really was left hanging', len(cdp.stalled) >= 1, cdp.stalled)
    cdp.stall_paths = []
    cdp.release_stalled()

    print('P10 the server copy still wins when the workout changed on another device')
    elsewhere = t.active_session()
    elsewhere['name'] = 'Changed Elsewhere'
    api('POST', '/api/active-session', {'session': elsewhere}, token)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    check("the other device's version replaces this device's", cdp.wait(f"{ACTIVE} && {TITLE} === 'Changed Elsewhere'"), safe_ev(TITLE))
    api('DELETE', '/api/active-session', token=token)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    check('a workout finished on another device goes away here', cdp.wait(HIDDEN), '')
    cdp.pause(0.8)
    check('and is not sent back to the server', server_sets() is None, server_sets())

    print('P11 another tab uploading the same queue never drops the workout behind')
    open_tracker()
    n = len(workouts())
    first = {'name': 'Tab Race One', 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': 'tab-race-1',
             'exercises': [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}]}]}
    second = {**first, 'name': 'Tab Race Two', 'clientId': 'tab-race-2'}
    # Stands in for a second tab flushing the same queue: its upload of the first workout finishes first and takes it
    # off the queue, before this tab's upload of the same workout comes back.
    cdp.ev(f"""(() => {{
      queuePendingWorkout({json.dumps(first)}); queuePendingWorkout({json.dumps(second)});
      const upload = window.fetch;
      window.fetch = (...args) => upload(...args).then(response => {{
        if (!window.__otherTab && String(args[0]).endsWith('/api/workouts') && args[1] && args[1].method === 'POST') {{
          window.__otherTab = true;
          writeLocal(localKey('pending'), readPendingWorkouts().filter(workout => workout.clientId !== 'tab-race-1'));
        }}
        return response;
      }});
    }})()""")
    flushed = cdp.ev('flushPendingWorkouts()')
    names = [w['name'] for w in workouts()]
    check('the flush finishes', flushed is True, flushed)
    check('both workouts reach the server, once each', names.count('Tab Race One') == 1 and names.count('Tab Race Two') == 1 and len(names) == n + 2, names[:5])
    check('nothing is left in the upload queue', safe_ev('readPendingWorkouts().length', -1) == 0, safe_ev('readPendingWorkouts()', []))

    print('P12 a workout the server keeps failing on does not hold up the ones behind it')
    open_tracker()
    n = len(workouts())
    stuck = {'name': 'Server Chokes', 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': 'chokes-1',
             'exercises': [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}]}]}
    behind = {**stuck, 'name': 'Behind The Choke', 'clientId': 'behind-choke-1'}
    # Stands in for a server bug that answers one workout with a 500, however often it is sent.
    cdp.ev(f"""(() => {{
      queuePendingWorkout({json.dumps(stuck)}); queuePendingWorkout({json.dumps(behind)});
      const upload = window.fetch;
      window.__chokes = 0;
      window.fetch = (...args) => args[1] && args[1].method === 'POST' && String(args[1].body).includes('chokes-1') && !window.__serverFixed
        ? (window.__chokes += 1, Promise.resolve(new Response('{{"error": "Internal server error."}}', {{ status: 500 }})))
        : upload(...args);
    }})()""")
    flushed = cdp.ev('flushPendingWorkouts()')
    names = [w['name'] for w in workouts()]
    check('the workout behind it is uploaded all the same', 'Behind The Choke' in names and 'Server Chokes' not in names and len(names) == n + 1, names[:5])
    check('while the failing one stays queued, not set aside', safe_ev('readPendingWorkouts().map(w => w.name)', []) == ['Server Chokes']
          and 'Server Chokes' not in safe_ev('readRejectedWorkouts().map(w => w.name)', []), safe_ev('readPendingWorkouts().map(w => w.name)', []))
    check('and the flush says something is still waiting, with a retry to come', flushed is False and cdp.ev('window.__chokes') >= 1
          and cdp.ev('pendingRetryCount') >= 1, [flushed, cdp.ev('window.__chokes'), cdp.ev('pendingRetryCount')])
    status = cdp.ev("document.getElementById('storageStatus').textContent")
    check('as the status line does', '1 workout waiting to sync' in status, status)
    cdp.ev('window.__serverFixed = true')
    # The retry itself runs on a timer that backs off; what matters here is that the next try sends it, whenever it comes.
    tried = cdp.ev("Promise.race([flushPendingWorkouts(), new Promise(done => setTimeout(() => done('still going after 20 s'), 20000))])")
    check('once the server takes it, the next try uploads it', tried is True
          and 'Server Chokes' in [w['name'] for w in workouts()] and safe_ev('readPendingWorkouts().length', -1) == 0,
          [tried, safe_ev('readPendingWorkouts().map(w => w.name)', [])])

    print('P13 a browser that will not save says so, rather than losing a workout on reload')
    open_tracker()
    storage = "!!document.getElementById('storageWarning')"
    check('no warning while the browser saves as it should', cdp.ev(storage) is False)
    cdp.ev("""(() => { window.__setItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function () { throw new DOMException('The quota has been exceeded.', 'QuotaExceededError'); }; })()""")
    start(0)
    cdp.pause(0.4)
    log_set(8)
    check('a set that could not be stored brings up a warning', cdp.ev(storage) is True
          and 'keep it open' in cdp.ev("document.getElementById('storageWarning').textContent"), safe_ev("document.body.firstElementChild.outerHTML", ''))
    check('the set is still held, and still reaches the server', safe_ev("document.querySelectorAll('#completedSets li').length", 0) == 1
          and wait_for(lambda: server_sets() == 1))
    # Something else held meanwhile, and never written again: it must not keep the warning up once storing works.
    cdp.ev("writeLocal('workout-tracker-held-test', 'kept')")
    cdp.ev('Storage.prototype.setItem = window.__setItem')
    log_set(8)
    check('once the browser saves again, the warning goes', cdp.wait(f'!{storage}') and safe_ev("readLocalActive().session.exercises[0].sets.length", 0) == 2)
    check('and whatever was held in memory meanwhile is stored too', cdp.ev("localStorage.getItem('workout-tracker-held-test')") == '"kept"'
          and cdp.ev('memoryStore.size') == 0, cdp.ev("localStorage.getItem('workout-tracker-held-test')"))
    cdp.ev("localStorage.removeItem('workout-tracker-held-test')")
    end_workout()

    print('P14 a workout written in the form is saved on the device first, and once')
    form_workout = lambda name: cdp.ev(f"document.getElementById('createWorkoutBtn').click(); document.getElementById('workoutName').value = '{name}';"
                                       " document.getElementById('exercise').value = 'Curl'; document.getElementById('weight').value = '30';"
                                       " document.getElementById('reps').value = '10'; document.getElementById('addBtn').click()")
    named = lambda name: [w for w in workouts() if w['name'] == name]
    open_tracker()
    form_workout('Form Offline')
    cdp.block_api = True
    cdp.ev("document.getElementById('saveBtn').click(); document.getElementById('saveBtn').click()")
    cdp.pause(0.8)
    fb = cdp.ev("document.getElementById('formFeedback').textContent") or ''
    check('saving offline says it is kept on this device', 'saved on this device' in fb, fb)
    check('a double tap queues it once', safe_ev("readPendingWorkouts().filter(w => w.name === 'Form Offline').length", -1) == 1,
          safe_ev("readPendingWorkouts().map(w => w.name)", None))
    check('with a clientId, so a retry cannot store it twice', bool(safe_ev("readPendingWorkouts().find(w => w.name === 'Form Offline')?.clientId", '')))
    check('and the form is closed', cdp.ev("document.getElementById('workoutBuilderCard').hidden") is True)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(1.0)
    check('it survives a reload', safe_ev("readPendingWorkouts().filter(w => w.name === 'Form Offline').length", -1) == 1)
    cdp.block_api = False
    check('it uploads once the server is back', wait_for(lambda: len(named('Form Offline')) == 1), len(named('Form Offline')))
    check('and the queue empties', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0), safe_ev('readPendingWorkouts().length', -1))
    check('one copy only', len(named('Form Offline')) == 1, len(named('Form Offline')))
    open_tracker()
    form_workout('Form Online')
    cdp.ev("document.getElementById('saveBtn').click(); document.getElementById('saveBtn').click()")
    check('online, a double tap saves it once too', wait_for(lambda: len(named('Form Online')) == 1) and (cdp.pause(1.0) or len(named('Form Online')) == 1),
          len(named('Form Online')))
    # Among the page's saved workouts, not necessarily on screen: it is dated noon today, and this suite has finished more
    # than the 10 the list shows since then.
    check('and the page has it without a reload', wait_for(lambda: safe_ev("savedWorkouts.some(w => w.name === 'Form Online')", False) is True))

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

    print('B   the rest bar drains as the rest runs out')
    left = "parseFloat(document.getElementById('restPanel').style.getPropertyValue('--rest-left'))"
    cdp.ev("document.getElementById('restResetBtn').click()")
    check('a fresh rest starts with a full bar', cdp.ev(left) == 1, cdp.ev(left))
    cdp.ev("document.getElementById('restToggleBtn').click(); window.__offset += 45000")
    cdp.pause(0.7)
    check('half the rest gone, half the bar', 0.45 <= cdp.ev(left) <= 0.52, cdp.ev(left))
    adjust(30)
    check('30 seconds more refills part of it', 0.78 <= cdp.ev(left) <= 0.86, cdp.ev(left))
    adjust(30)
    check('a rest stretched past its start keeps the bar full', 0.95 <= cdp.ev(left) <= 1, cdp.ev(left))
    cdp.ev('window.__offset += 200000')
    cdp.pause(0.7)
    check('and it is empty when the rest is over', cdp.ev(left) == 0, cdp.ev(left))

    print('E   End rest skips what is left, and a green flash marks a rest that is over')
    flash = "document.querySelectorAll('.rest-flash').length"
    end_btn = "document.getElementById('restEndBtn')"
    check('with the rest over there is nothing to end', cdp.ev(end_btn + '.disabled') is True)
    cdp.pause(1.2)
    check('the flash from a rest that ran out has cleared', cdp.ev(flash) == 0, cdp.ev(flash))
    cdp.ev("document.getElementById('restResetBtn').click()")
    cdp.ev("document.getElementById('restToggleBtn').click()")
    cdp.pause(0.3)
    check('a rest with time left can be ended', cdp.ev(end_btn + '.disabled') is False)
    cdp.ev('window.__osc = 0; window.__vib = []')
    cdp.ev(end_btn + '.click()')
    check('which ends it at once', cdp.ev(DISPLAY) == '0:00' and cdp.ev(TOGGLE) == 'Start rest', f'{cdp.ev(DISPLAY)} / {cdp.ev(TOGGLE)}')
    check('with the green flash', cdp.ev(flash) == 1, cdp.ev(flash))
    check('over the whole screen and out of the way of taps', cdp.ev("(f => getComputedStyle(f).pointerEvents + getComputedStyle(f).position)(document.querySelector('.rest-flash'))") == 'nonefixed')
    check('and the bar is empty', cdp.ev(left) == 0, cdp.ev(left))
    check('quietly, since you asked for it: no beep and no vibration', cdp.ev('window.__osc') == 0 and cdp.ev('window.__vib.length') == 0)
    check('then nothing is left to end', cdp.ev(end_btn + '.disabled') is True)
    cdp.pause(1.2)
    check('the flash clears itself away', cdp.ev(flash) == 0, cdp.ev(flash))
    cdp.ev("document.getElementById('restToggleBtn').click()")
    cdp.ev('window.__offset += 200000')
    cdp.pause(0.7)
    check('a rest that runs out flashes too, and beeps', cdp.ev(flash) == 1 and cdp.ev('window.__osc') >= 2, f"{cdp.ev(flash)} {cdp.ev('window.__osc')}")
    cdp.pause(1.2)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=740, deviceScaleFactor=1, mobile=True)
    cdp.ev("document.getElementById('restResetBtn').click()")
    cdp.pause(0.3)
    fit = cdp.ev("(() => { const panel = document.getElementById('restPanel').getBoundingClientRect(); "
                 "return [...document.querySelectorAll('#restPanel button')].every(b => { const r = b.getBoundingClientRect(); return r.left >= panel.left && r.right <= panel.right + 0.5; }); })()")
    check('on a phone every rest button still fits in the panel', fit is True)
    cdp.send('Emulation.clearDeviceMetricsOverride')
    end_workout()
