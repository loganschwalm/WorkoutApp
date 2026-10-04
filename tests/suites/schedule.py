"""The training schedule: choosing days in Settings, the Tracker's nudge, the planned days on History's calendar, and
reminders (turning them on from Settings, the test notification, and what the service worker does with a push)."""

import json
import os
import secrets
import sqlite3
import time

from ..harness import ACTIVE, PLAIN_HTTP_HOST, REPO_ROOT, load_server
from .push import PushService, decrypt_message

INTERCEPT = False

PASSWORD = 'chalk-and-plates-42'
DAY_MS = 86400000
# A Reddit PPL with its first day done, so what is next is Push (Bench), then Legs, Pull (Row), Push (Overhead Press), Legs.
PPL = {'definition': 'reddit-ppl', 'startedAt': 1000, 'cycle': 1, 'lastRollover': None,
       'trainingMaxes': {'deadlift': 225, 'row': 115, 'bench': 135, 'press': 85, 'squat': 185}, 'options': {'rounding': 5},
       'done': {'0-0': {'at': 2000, 'skipped': False, 'amrap': None, 'hit': None}}}


def run(t):
    cdp, check, api, token, wait_for = t.cdp, t.check, t.api, t.token, t.wait_for

    text, visible, field, click = t.text, t.visible, t.field, t.click

    def settings_open():
        return cdp.ev("!document.getElementById('settingsModal').hidden")

    def open_settings():
        if not settings_open():
            click('settingsButton')
            cdp.pause(0.5)

    def close_settings():
        if settings_open():
            click('doneSettings')
            cdp.pause(0.3)

    def stored_schedule():
        return cdp.ev('getWorkoutSettings().schedule')

    def tick(value, checked=True):
        """Choose or clear a training day the way a tap does."""
        cdp.ev(f"(() => {{ const box = document.querySelector('#scheduleDays input[value=\"{value}\"]'); if (box.checked !== {str(checked).lower()}) box.click(); }})()")
        cdp.pause(0.15)

    def server_schedule():
        return api('GET', '/api/state', token=token)[0]['settings'].get('schedule')

    def set_schedule(days, at='17:00'):
        """The schedule as this page has it, without going through Settings."""
        cdp.ev(f"saveLocalState('settings', {{ ...getWorkoutSettings(), schedule: {{ days: {json.dumps(days)}, time: '{at}' }} }}); window.dispatchEvent(new Event('settingschange'))")
        cdp.pause(0.2)

    def nudge(workouts='[]'):
        return cdp.ev(f'scheduleNudge({workouts})')

    today = None

    def weekday(offset):
        return cdp.ev(f"weekdayNames[(new Date().getDay() + {offset}) % 7]")

    def number(offset):
        return (today + offset) % 7

    def ago(days):
        return f'{{ createdAt: Date.now() - {days} * {DAY_MS} }}'

    # ------------------------------------------------------------------ S choosing the days
    print('S   choosing the training days in Settings')
    t.open_tracker()
    today = cdp.ev('new Date().getDay()')
    open_settings()
    values = cdp.ev("[...document.querySelectorAll('#scheduleDays input')].map(input => input.value)")
    labels = cdp.ev("[...document.querySelectorAll('#scheduleDays input')].map(input => input.getAttribute('aria-label'))")
    check('seven days to choose from, Monday first', values == ['1', '2', '3', '4', '5', '6', '0'] and labels[0] == 'Monday' and labels[-1] == 'Sunday', [values, labels])
    check('none chosen at first, and a time of 5pm', cdp.ev("document.querySelectorAll('#scheduleDays input:checked').length") == 0 and field('reminderTimeSetting') == '17:00')
    check('the schedule starts as no days', stored_schedule() == {'days': [], 'time': '17:00'}, stored_schedule())
    for day in (1, 3, 5):
        tick(day)
    check('the days chosen are kept at once, in order of the week', stored_schedule() == {'days': [1, 3, 5], 'time': '17:00'}, stored_schedule())
    cdp.ev("(() => { const input = document.getElementById('reminderTimeSetting'); input.value = '06:30'; input.dispatchEvent(new Event('change', { bubbles: true })); })()")
    cdp.pause(0.2)
    check('and so is the time', stored_schedule() == {'days': [1, 3, 5], 'time': '06:30'}, stored_schedule())
    cdp.ev("(() => { const input = document.getElementById('reminderTimeSetting'); input.value = ''; input.dispatchEvent(new Event('change', { bubbles: true })); })()")
    cdp.pause(0.2)
    check('a time cleared keeps the one there was', stored_schedule()['time'] == '06:30', stored_schedule())
    check('and reaches the server', wait_for(lambda: server_schedule() == {'days': [1, 3, 5], 'time': '06:30'}), server_schedule())
    tick(3, False)
    tick(0)
    check('days can be taken away and added', stored_schedule()['days'] == [0, 1, 5], stored_schedule())
    close_settings()
    t.open_tracker()
    open_settings()
    ticked = cdp.ev("[...document.querySelectorAll('#scheduleDays input:checked')].map(input => input.value)")
    check('a reload keeps them', sorted(ticked) == ['0', '1', '5'] and field('reminderTimeSetting') == '06:30', ticked)
    close_settings()
    wait_for(lambda: server_schedule() == {'days': [0, 1, 5], 'time': '06:30'})
    api('PUT', '/api/state', {'settings': {'schedule': {'days': [2, 4], 'time': '07:15'}}}, token)
    t.open_tracker()
    open_settings()
    check('days chosen on another device arrive', sorted(cdp.ev("[...document.querySelectorAll('#scheduleDays input:checked')].map(input => input.value)")) == ['2', '4']
          and field('reminderTimeSetting') == '07:15')
    close_settings()
    read = cdp.ev("scheduleFrom({ schedule: { days: [9, 'x', 2, 2, -1], time: 'late' } })")
    check('a schedule that is not one is read as the days that are, and the default time', read == {'days': [2], 'time': '17:00'}, read)
    check('and none at all as no days', cdp.ev('scheduleFrom({})') == {'days': [], 'time': '17:00'} and cdp.ev("scheduleFrom({ schedule: 'Mon' })") == {'days': [], 'time': '17:00'})
    api('PUT', '/api/state', {'settings': {}}, token)

    # ------------------------------------------------------------------ N the nudge
    print('N   the Tracker says what is planned')
    t.open_tracker()
    check('with no days chosen there is no nudge', not visible('scheduleCard'))
    set_schedule([today])
    check('on a training day, it says so', visible('scheduleCard') and text('scheduleText') == 'Today is a training day.', text('scheduleText'))
    check('with nothing to start while there is no program', not visible('scheduleStart'))
    set_schedule([number(1)])
    check('on a day to rest, tomorrow is said as tomorrow', text('scheduleText') == 'Rest day. Next up: tomorrow.', text('scheduleText'))
    set_schedule([number(2)])
    # (Three weeks of seeded workouts end six days ago, so a day to train five days ago would count as missed: the checks of
    # what is said, apart from what is on screen, give the workouts themselves.)
    check('and any later day by its name', nudge('[]') == {'text': f'Rest day. Next up: {weekday(2)}.', 'start': False}, nudge('[]'))

    set_schedule([today])
    done = nudge('[{ createdAt: Date.now() }]')
    check('done for today, with the next training day a week on', done == {'text': f'Done for today. Next up: {weekday(0)}.', 'start': False}, done)
    set_schedule([number(5), number(2)])
    missed = nudge(f'[{ago(3)}]')
    check('a training day missed by someone who was training is said, with the next one', missed == {
        'text': f"You missed {weekday(5)}'s workout. Train today instead, or carry on {weekday(2)}.", 'start': False}, missed)
    check('but not by someone who was not (a schedule only just chosen, or picked up after months)', nudge('[]')['text'].startswith('Rest day.')
          and nudge(f'[{ago(40)}]')['text'].startswith('Rest day.'), [nudge('[]'), nudge(f'[{ago(40)}]')])
    check('nor once they have trained since', nudge(f'[{ago(3)}, {ago(1)}]')['text'].startswith('Rest day.'), nudge(f'[{ago(3)}, {ago(1)}]'))
    set_schedule([today, number(5)])
    check('a missed day and a training day today are both said', nudge(f'[{ago(3)}]')['text'] == f'You missed {weekday(5)}. Today is a training day.', nudge(f'[{ago(3)}]'))

    # With a program, the next workout is planned for the next training day, and the one after for the day after.
    api('PUT', '/api/state', {'program': PPL}, token)
    t.open_tracker()
    set_schedule([today])
    check('with a program, today’s workout is named', text('scheduleText') == 'Today is a training day: Push (Bench).', text('scheduleText'))
    check('and can be started from the nudge', visible('scheduleStart') and text('scheduleStart') == 'Start Push (Bench)', text('scheduleStart'))
    check('Done for today says what the next training day brings', nudge('[{ createdAt: Date.now() }]')['text'] == f'Done for today. Next up: {weekday(0)}, Push (Bench).', nudge('[{ createdAt: Date.now() }]'))
    set_schedule([number(2), number(4)])
    check('the next training day gets the next workout', nudge('[]')['text'] == f'Rest day. Next up: {weekday(2)}, Push (Bench).', nudge('[]'))
    set_schedule([today])
    click('scheduleStart')
    cdp.wait(ACTIVE)
    cdp.pause(0.3)
    check('Start begins the program’s next workout', text('activeExerciseName') == 'Bench Press', text('activeExerciseName'))
    check('and the nudge is out of the way while it goes on', cdp.ev("getComputedStyle(document.getElementById('scheduleCard')).display") == 'none')
    t.end_workout()
    click('scheduleChange')
    cdp.pause(0.3)
    check('Change schedule opens Settings', settings_open())
    close_settings()

    # ------------------------------------------------------------------ H the calendar
    print('H   History marks the planned days')
    api('PUT', '/api/state', {'settings': {'schedule': {'days': [0, 1, 2, 3, 4, 5, 6], 'time': '17:00'}}, 'program': PPL}, token)
    cdp.console.clear()
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 3")
    cdp.pause(0.5)
    behind = (today + 6) % 7  # where today falls in a week that starts on Monday
    planned = cdp.ev("[...document.querySelectorAll('#trainingCalendar .calendar-day.planned')].map(day => day.getAttribute('aria-label'))")
    check('today and every day left of this week are planned', len(planned) == 7 - behind, planned)
    check('today’s square names its workout', 'planned: Push (Bench)' in planned[0], planned[0])
    check('and the next day’s the one after', len(planned) < 2 or 'planned: Legs' in planned[1], planned)
    check('planned days to come can be reached, and the rest of the days to come are only squares',
          cdp.ev("[...document.querySelectorAll('#trainingCalendar .calendar-day.future.planned')].every(day => day.tagName === 'BUTTON')") is True
          and cdp.ev("[...document.querySelectorAll('#trainingCalendar span.calendar-day.future')].every(day => day.getAttribute('aria-hidden') === 'true' && !day.classList.contains('planned'))") is True)
    cdp.ev("document.querySelector('#trainingCalendar .calendar-day.planned').click()")
    check('tapping one writes it out below the calendar', 'planned: Push (Bench)' in text('calendarDetail'), text('calendarDetail'))
    coming = cdp.ev("[...document.querySelectorAll('#comingUp li')].map(li => [...li.children].map(c => c.textContent))")
    check('Coming up lists six, from today, each with its workout', len(coming) == 6 and coming[0] == ['Today', 'Push (Bench)']
          and [row[1] for row in coming] == ['Push (Bench)', 'Legs', 'Pull (Row)', 'Push (Overhead Press)', 'Legs', 'Pull (Deadlift)'], coming)
    check('and the hint to choose days is gone', visible('comingUpBlock') and not visible('scheduleHint'))
    check('History loads with no errors', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
    api('POST', '/api/workouts', {'name': 'Just now', 'notes': '', 'createdAt': int(time.time() * 1000), 'exercises': [t.ex('Bench Press', 100, 5, [(5, 100)])]}, token)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 4")
    cdp.pause(0.5)
    planned = cdp.ev("[...document.querySelectorAll('#trainingCalendar .calendar-day.planned')].map(day => day.getAttribute('aria-label'))")
    coming = cdp.ev("[...document.querySelectorAll('#comingUp li')].map(li => [...li.children].map(c => c.textContent))")
    check('once today is trained it is no longer planned, and Coming up says it is done', len(planned) == 6 - behind and coming[0] == ['Today', 'Done'], [planned, coming[:2]])
    check('and tomorrow gets the workout that was due', coming[1][1] == 'Push (Bench)', coming[:2])
    api('PUT', '/api/state', {'settings': {'schedule': {'days': [], 'time': '17:00'}}}, token)
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 4")
    cdp.pause(0.5)
    check('with no days chosen, nothing is planned, and the page says where to choose', cdp.ev("document.querySelectorAll('#trainingCalendar .calendar-day.planned').length") == 0
          and not visible('comingUpBlock') and visible('scheduleHint'))
    api('PUT', '/api/state', {'program': None}, token)

    # A cardio session is a day's training as much as a lifting workout: the Tracker, which lists only the lifting, still says so.
    cardio_token = api('POST', '/api/auth/register', {'username': 'walker', 'email': 'walker@example.test', 'password': PASSWORD})[1].split('session=')[1].split(';')[0]
    api('PUT', '/api/state', {'settings': {'schedule': {'days': [today], 'time': '17:00'}}}, cardio_token)
    t.set_cookie(cardio_token)
    t.open_tracker()
    check('with nothing logged, today is a training day', text('scheduleText') == 'Today is a training day.', text('scheduleText'))
    api('POST', '/api/workouts', {'kind': 'cardio', 'name': 'Walk', 'notes': '', 'createdAt': int(time.time() * 1000), 'exercises': [],
                                  'duration': 900, 'cardio': {'activity': 'walk'}}, cardio_token)
    t.open_tracker()
    check('a cardio session logged today makes it done', text('scheduleText').startswith('Done for today.'), text('scheduleText'))
    t.set_cookie(t.token)

    # ------------------------------------------------------------------ R reminders
    print('R   reminders, from Settings to the notification')
    server = load_server()
    service = PushService()
    host = f'http://127.0.0.1:{service.server_address[1]}'
    other = t.start_server('reminders.db', {'PUSH_ALLOWED_HOSTS': '127.0.0.1', 'REMINDER_TICK_SECONDS': '0.4'})
    cookie = other.api('POST', '/api/auth/register', {'username': 'reminded', 'email': 'reminded@example.test', 'password': PASSWORD})[1]
    other_token = cookie.split('session=')[1].split(';')[0]
    t.set_cookie(other_token)
    private = secrets.randbelow(server.P256_N - 1) + 1
    public, auth = server.encode_point(*server.ec_multiply(private)), secrets.token_bytes(16)
    endpoint = f'{host}/push/browser'
    database = os.path.join(t.workdir, 'reminders.db')

    def subscriptions():
        db = sqlite3.connect(database)
        try:
            return db.execute('SELECT endpoint, tz, offset_minutes FROM push_subscriptions').fetchall()
        finally:
            db.close()

    def open_other(path='/index.html'):
        cdp.send('Page.navigate', url=other.base_url + path)
        time.sleep(0.4)
        cdp.wait("document.readyState === 'complete' && typeof pushProblem === 'function'")
        cdp.pause(0.6)

    # What a browser would give: a permission to ask for and a subscription to hand over, which this headless one cannot get
    # from a push service. The subscription's keys are real, so the server's messages to it can be read.
    stub = """(() => {
      window.__permission = 'default'; window.__sub = null; window.__calls = [];
      Object.defineProperty(Notification, 'permission', { get: () => window.__permission, configurable: true });
      Notification.requestPermission = () => { window.__calls.push('permission'); window.__permission = 'granted'; return Promise.resolve('granted'); };
      PushManager.prototype.getSubscription = () => Promise.resolve(window.__sub);
      PushManager.prototype.subscribe = options => {
        window.__calls.push('subscribe');
        window.__sub = { endpoint: %s, options: { applicationServerKey: options.applicationServerKey.buffer },
          toJSON() { return { endpoint: %s, keys: { p256dh: %s, auth: %s } }; },
          unsubscribe() { window.__calls.push('unsubscribe'); window.__sub = null; return Promise.resolve(true); } };
        return Promise.resolve(window.__sub);
      };
    })()""" % (json.dumps(endpoint), json.dumps(endpoint), json.dumps(server.b64url(public)), json.dumps(server.b64url(auth)))

    open_other()
    cdp.ev(stub)
    open_settings()
    check('Settings offers reminders on a browser that can show them', not cdp.ev("document.getElementById('remindSetting').disabled") and not cdp.ev("document.getElementById('remindSetting').checked")
          and 'even when the app is closed' in text('remindStatus') and not visible('testReminderButton'), text('remindStatus'))
    cdp.ev("window.__permission = 'denied'")
    close_settings()
    open_settings()
    check('where notifications are blocked, it says how to allow them', cdp.ev("document.getElementById('remindSetting').disabled") and 'blocked' in text('remindStatus'), text('remindStatus'))
    cdp.ev("window.__permission = 'default'")
    close_settings()
    open_settings()
    click('remindSetting')
    check('turning them on asks for permission and subscribes', wait_for(lambda: cdp.ev('window.__calls') == ['permission', 'subscribe']), cdp.ev('window.__calls'))
    check('and tells the server, with this phone’s clock', wait_for(lambda: len(subscriptions()) == 1) and subscriptions()[0][0] == endpoint
          and subscriptions()[0][1] == cdp.ev('Intl.DateTimeFormat().resolvedOptions().timeZone') and subscriptions()[0][2] == cdp.ev('0 - new Date().getTimezoneOffset()'), subscriptions())
    cdp.pause(0.3)
    check('the box is ticked, and says to choose days while there are none', cdp.ev("document.getElementById('remindSetting').checked") and 'Choose the days' in text('remindStatus'), text('remindStatus'))
    tick(1)
    check('choosing a day changes what it says', text('remindStatus') == 'Reminders are on for this device.', text('remindStatus'))
    check('and offers a test', visible('testReminderButton'))
    click('testReminderButton')
    check('the test reaches the push service', wait_for(lambda: len(service.to('browser')) == 1), len(service.received))
    message = json.loads(decrypt_message(server, service.to('browser')[0]['body'], private, public, auth))
    check('as a notification this device can read', message['title'] == 'Workout Tracker' and message['url'] == '/index.html', message)
    check('and the page says it was sent', wait_for(lambda: 'Sent to your device' in text('remindStatus')), text('remindStatus'))
    time.sleep(3.1)
    service.answers['/push/browser'] = [500]
    click('testReminderButton')
    check('a push service that refuses it is said to', wait_for(lambda: 'did not take it' in text('remindStatus')), text('remindStatus'))
    click('remindSetting')
    check('turning them off removes this device from the server', wait_for(lambda: subscriptions() == []) and 'unsubscribe' in cdp.ev('window.__calls') and cdp.ev('window.__sub') is None, subscriptions())
    cdp.pause(0.3)
    check('the box is clear, with no test to send', not cdp.ev("document.getElementById('remindSetting').checked") and not visible('testReminderButton'))
    check('the days stay chosen: they belong to the account, not the device', cdp.ev("[...document.querySelectorAll('#scheduleDays input:checked')].map(input => input.value)") == ['1'])
    close_settings()

    # A subscription this browser already has is told to the server again: once a day, and when the clock changes.
    cdp.ev("window.__permission = 'granted'; window.__calls = []")
    cdp.ev("PushManager.prototype.subscribe.call(null, { applicationServerKey: new Uint8Array(65) })")
    cdp.ev("localStorage.removeItem('workout-tracker-push-clock')")
    cdp.ev("syncPushDevice()")
    check('a subscription this browser has is told to the server again when it has not been today', wait_for(lambda: len(subscriptions()) == 1), subscriptions())
    db = sqlite3.connect(database)
    db.execute('DELETE FROM push_subscriptions')
    db.commit()
    db.close()
    cdp.ev("syncPushDevice()")
    cdp.pause(0.8)
    check('and not again the same day, with the same clock', subscriptions() == [])
    cdp.ev("localStorage.setItem('workout-tracker-push-clock', 'old')")
    cdp.ev("syncPushDevice()")
    check('but is when the clock changed', wait_for(lambda: len(subscriptions()) == 1), subscriptions())

    # Signing out stops this browser being sent the account's reminders.
    open_settings()
    click('signOutButton')
    check('signing out takes this browser off the account’s reminders', cdp.wait("location.pathname.endsWith('login.html')", timeout=10) and subscriptions() == [], subscriptions())

    # Where the browser has no secure context, reminders cannot work, and Settings says why.
    cookie = other.api('POST', '/api/auth/login', {'login': 'reminded', 'password': PASSWORD})[1]
    cdp.send('Network.setCookie', name='session', value=cookie.split('session=')[1].split(';')[0], domain=PLAIN_HTTP_HOST, path='/')
    cdp.send('Page.navigate', url=f'http://{PLAIN_HTTP_HOST}:{other.port}/index.html')
    cdp.wait("document.readyState === 'complete' && typeof pushProblem === 'function'")
    cdp.pause(0.6)
    open_settings()
    check('over plain HTTP, the box is off and Settings says it needs HTTPS', cdp.ev("document.getElementById('remindSetting').disabled") and 'HTTPS' in text('remindStatus'), text('remindStatus'))
    close_settings()

    # ------------------------------------------------------------------ W the service worker
    print('W   what the service worker does with a push')
    t.set_cookie(t.token)
    t.open_tracker()
    source = open(os.path.join(REPO_ROOT, 'frontend', 'sw.js'), encoding='utf-8').read()
    cdp.ev("window.__worker = (function (self) {\n" + source + "\n})")
    cdp.ev("""(() => {
      window.__listeners = {}; window.__shown = []; window.__opened = []; window.__focused = []; window.__navigated = []; window.__clients = [];
      const fake = { location: { origin: location.origin }, addEventListener(type, handler) { window.__listeners[type] = handler; }, skipWaiting() {},
        registration: { showNotification(title, options) { window.__shown.push({ title, options }); return Promise.resolve(); } },
        clients: { matchAll: () => Promise.resolve(window.__clients), openWindow(url) { window.__opened.push(url); return Promise.resolve(); }, claim() {} } };
      window.__worker(fake);
      window.__push = data => { let pending = []; window.__listeners.push({ data, waitUntil(promise) { pending.push(promise); } }); return Promise.all(pending); };
    })()""")
    cdp.ev("window.__push({ json: () => ({ title: 'Time to train', body: 'Today is a training day.', url: '/index.html', tag: 'training-day' }) })")
    cdp.pause(0.2)
    shown = cdp.ev('window.__shown')
    check('a push shows a notification, with the server’s words and a tag so a second replaces the first',
          len(shown) == 1 and shown[0]['title'] == 'Time to train' and shown[0]['options']['body'] == 'Today is a training day.' and shown[0]['options']['tag'] == 'training-day', shown)
    check('with the app’s icon, and the page it opens', shown[0]['options']['icon'] == '/icons/icon-192.png' and shown[0]['options']['data'] == {'url': '/index.html'}, shown[0]['options'])
    cdp.ev("window.__push({ json: () => ({ title: 'x', url: '//evil.example/' }) })")
    cdp.ev("window.__push({ json: () => ({ title: 'x', url: 'https://evil.example/' }) })")
    cdp.pause(0.2)
    check('a page to open that leads off the site is not taken', [item['options']['data']['url'] for item in cdp.ev('window.__shown')[1:]] == ['/index.html', '/index.html'])
    cdp.ev("window.__push(null)")
    cdp.ev("window.__push({ json: () => { throw new Error('not json'); }, text: () => 'plain words' })")
    cdp.pause(0.2)
    last = cdp.ev('window.__shown')[3:]
    check('a push with nothing in it, or not JSON, still shows one', last[0]['title'] == 'Workout Tracker' and last[1]['options']['body'] == 'plain words', last)

    def tap(clients):
        cdp.ev("window.__opened = []; window.__focused = []; window.__navigated = []")
        cdp.ev("window.__clients = " + clients)
        cdp.ev("(() => { let pending = []; const closed = []; window.__closed = closed; window.__listeners.notificationclick({ notification: { close() { closed.push(1); }, data: { url: '/progress.html' } }, waitUntil(p) { pending.push(p); } }); return Promise.all(pending); })()")
        cdp.pause(0.3)
        return cdp.ev('[window.__closed.length, window.__opened, window.__focused, window.__navigated]')

    nothing_open = tap('[]')
    check('tapping it opens the app when it is not open', nothing_open == [1, [f'{t.base_url}/progress.html'], [], []], nothing_open)
    window_stub = "[{ url: location.origin + '/index.html', focus() { window.__focused.push(1); return Promise.resolve(); }, navigate(url) { window.__navigated.push(url); return Promise.resolve(); } }]"
    already_open = tap(window_stub)
    check('and brings it forward, on the page the notification names, when it is', already_open == [1, [], [1], [f'{t.base_url}/progress.html']], already_open)
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
