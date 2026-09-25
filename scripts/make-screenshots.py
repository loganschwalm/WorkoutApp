#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/screenshots/.

Starts the real server on a throwaway database, fills it with six weeks of demo
training, and captures the pages with the same headless Chrome the tests use:

    pip install -r tests/requirements.txt
    python scripts/make-screenshots.py

It needs Chrome, Chromium or Edge (see tests/README.md) and never touches data/.
The demo data is fixed, so running it again only changes the pictures when the
app itself looks different.
"""

import base64
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.harness import LIGHT_DEVICE, AppServer, Chrome  # noqa: E402

OUT_DIR = os.path.join(ROOT, 'docs', 'screenshots')
DAY_MS = 86400000
DESKTOP = (1280, 800)
PHONE = (390, 844)

# Each workout type rotates every two days; every exercise gains a little each time it comes round.
# (exercise, first weight, increase per session, target reps)
PROGRAM = [
    ('Push Day', [('Bench Press', 155, 5, 8), ('Overhead Press', 95, 2.5, 8), ('Tricep Pushdown', 50, 5, 12)]),
    ('Pull Day', [('Deadlift', 225, 10, 5), ('Barbell Row', 135, 5, 8), ('Lat Pulldown', 110, 5, 10)]),
    ('Leg Day', [('Back Squat', 185, 10, 8), ('Romanian Deadlift', 155, 5, 10), ('Leg Press', 270, 10, 10)]),
]
SESSIONS = 18
NOTES = {13: 'Bench moved fast today. Try 5 more next time.', 16: 'Grip gave out on the last set.'}
TEMPLATE = {'id': 'custom-demo', 'name': 'Upper Power',
            'exercises': [{'name': 'Bench Press', 'reps': '5'}, {'name': 'Pull-up', 'reps': '8'},
                          {'name': 'Overhead Press', 'reps': '6'}]}


def demo_workouts():
    """SESSIONS finished workouts, oldest first, ending the day before today."""
    today_noon = time.mktime(time.localtime()[:3] + (12, 0, 0, 0, 0, -1)) * 1000
    workouts = []
    for session in range(SESSIONS):
        name, lifts = PROGRAM[session % len(PROGRAM)]
        round_number = session // len(PROGRAM)
        exercises = []
        for lift, start, step, reps in lifts:
            weight = start + step * round_number
            # The last set of every third round falls one rep short, as real sets do.
            last = reps - 1 if round_number % 3 == 2 else reps
            sets = [{'weight': weight, 'reps': reps}, {'weight': weight, 'reps': reps}, {'weight': weight, 'reps': last}]
            exercises.append({'name': lift, 'weight': weight, 'reps': last, 'sets': sets})
        workouts.append({'name': name, 'notes': NOTES.get(session, ''), 'exercises': exercises,
                         'createdAt': int(today_noon - (SESSIONS - session) * 2 * DAY_MS),
                         'clientId': f'demo-{session}'})
    return workouts


def shrink(path):
    """Recompress the PNG losslessly when Pillow is installed (it is for make-icons.py); skip it otherwise."""
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as image:
        image.load()
    image.save(path, optimize=True)


class Browser:
    def __init__(self, server, workdir):
        self.chrome = Chrome(os.path.join(workdir, 'profile'))
        self.cdp = self.chrome.connect(server.base_url)
        for domain in ('Page', 'Runtime', 'Network'):
            self.cdp.send(f'{domain}.enable')
        self.cdp.send('Emulation.setScrollbarsHidden', hidden=True)
        # The app follows the device's light or dark mode; the screenshots are light (the dark one sets it outright),
        # whatever this machine uses.
        self.cdp.send('Emulation.setEmulatedMedia', features=LIGHT_DEVICE)

    def viewport(self, size, phone=False):
        width, height = size
        self.cdp.send('Emulation.setDeviceMetricsOverride', width=width, height=height,
                      deviceScaleFactor=2, mobile=phone)

    def open(self, path, ready):
        self.cdp.goto(path)
        if not self.cdp.wait(ready, timeout=15):
            raise RuntimeError(f'{path} never became ready ({ready})')
        self.cdp.pause(0.8)  # transitions, fonts, the chart

    def edge(self, selector, side='bottom', index=0, margin=0):
        """Where an element's top or bottom sits on the page, in CSS pixels, plus a margin."""
        rect = f"document.querySelectorAll({selector!r})[{index}].getBoundingClientRect()"
        return self.cdp.ev(f'{rect}.{side} + window.scrollY') + margin

    def save(self, name, top=None, bottom=None):
        """The viewport, or the full-width slice of the page between top and bottom (CSS pixels)."""
        params = {'format': 'png'}
        if bottom is not None:
            top = max(0, top or 0)
            width = self.cdp.ev('document.documentElement.clientWidth')
            params.update(captureBeyondViewport=True,
                          clip={'x': 0, 'y': top, 'width': width, 'height': bottom - top, 'scale': 1})
        data = base64.b64decode(self.cdp.send('Page.captureScreenshot', **params)['result']['data'])
        path = os.path.join(OUT_DIR, name)
        with open(path, 'wb') as handle:
            handle.write(data)
        shrink(path)
        print(f'  {os.path.relpath(path, ROOT)}  ({os.path.getsize(path) // 1024} KB)')

    def close(self):
        self.cdp.close()
        self.chrome.stop()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix='workout-screenshots-')
    server = browser = None
    try:
        server = AppServer(os.path.join(workdir, 'demo.db'))
        _, cookie = server.api('POST', '/api/auth/register', {'username': 'alex', 'email': 'alex@example.test', 'password': 'demo-password'})
        token = cookie.split('session=')[1].split(';')[0]
        for workout in demo_workouts():
            server.api('POST', '/api/workouts', workout, token)
        server.api('PUT', '/api/state', {'templates': [TEMPLATE]}, token)

        browser = Browser(server, workdir)
        cdp = browser.cdp
        cdp.send('Network.setCookie', name='session', value=token, domain='127.0.0.1', path='/')
        tracker_ready = "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 5"
        print(f'Writing {os.path.relpath(OUT_DIR, ROOT)}/')

        # The tracker: templates and the most recent saved workouts.
        browser.viewport(DESKTOP)
        browser.open('/index.html', tracker_ready)
        browser.save('tracker.png', bottom=browser.edge('#savedWorkoutList .saved-workout', index=2, margin=1))

        # A workout in progress on a phone: two sets logged, rest timer running, last time's numbers shown.
        browser.viewport(PHONE, phone=True)
        browser.open('/index.html', tracker_ready)
        cdp.ev("document.querySelector('#templateList [data-template-action=start]').click()")
        cdp.pause(0.5)
        for _ in range(2):
            cdp.ev("document.getElementById('completeSetBtn').click()")
            cdp.pause(0.4)
        cdp.pause(1.6)  # let the rest timer count down a little
        # The whole workout card, from its name down to adding an exercise.
        browser.save('active-workout.png', top=browser.edge('#activeWorkout', 'top', margin=-16),
                     bottom=browser.edge('#activeWorkout', margin=16))

        # Settings on a phone.
        cdp.ev("window.scrollTo(0, 0); document.getElementById('settingsButton').click()")
        cdp.pause(0.5)
        browser.save('settings.png')
        cdp.ev("document.getElementById('cancelSettings').click()")
        cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn').click()")
        cdp.pause(0.5)

        # Progress, every workout type on one chart.
        browser.viewport(DESKTOP)
        browser.open('/progress.html', "document.querySelectorAll('#legend .legend-item').length >= 3")
        browser.save('progress.png', bottom=browser.edge('main .card', margin=40))

        # History in dark mode, down to the end of the second workout.
        server.api('PUT', '/api/state', {'settings': {'theme': 'dark'}}, token)
        browser.open('/history.html', "document.documentElement.dataset.theme === 'dark' && document.querySelectorAll('.history-workout').length >= 5")
        browser.save('history-dark.png', bottom=browser.edge('.history-workout', index=1, margin=1))
    finally:
        if browser:
            browser.close()
        if server:
            server.stop()
        time.sleep(0.5)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    main()
