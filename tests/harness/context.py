"""The fixture a suite runs against: a server, a browser, seed data and page helpers."""

import os
import shutil
import tempfile
import time

from .browser import Chrome
from .server import AppServer

DAY_MS = 86400000
ACCOUNT = {'username': 'tester', 'password': 'password123'}

# Element lookups the suites share.
ACTIVE = "!document.getElementById('activeWorkout').hidden"
HIDDEN = "document.getElementById('activeWorkout').hidden"
TITLE = "document.getElementById('activeWorkoutTitle').textContent"
DISPLAY = "document.getElementById('timerDisplay').textContent"
TOGGLE = "document.getElementById('restToggleBtn').textContent"


def exercise(name, weight, reps, sets):
    """Build an exercise payload. `sets` is a list of (reps, weight) pairs; empty means skipped."""
    return {'name': name, 'weight': weight, 'reps': reps,
            'sets': [{'reps': r, 'weight': w} for r, w in sets]}


class Checker:
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=''):
        self.results.append((name, bool(ok), detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f'  ({detail})' if detail and not ok else ''))

    @property
    def failures(self):
        return [r for r in self.results if not r[1]]


class AppTest:
    """Everything a suite body needs, wired together and torn down afterwards.

    Each suite gets a fresh server, an empty database, a clean browser profile and
    the same three seeded workouts, so suites cannot affect one another.
    """

    def __init__(self, frontend_dir=None, intercept=False, browser=True):
        self.workdir = tempfile.mkdtemp(prefix='workout-tests-')
        self.frontend_dir = frontend_dir
        self.checker = Checker()
        self.check = self.checker.check
        self.server = None
        self.browser = None
        self.cdp = None
        self.extra_servers = []
        try:
            self.server = AppServer(os.path.join(self.workdir, 'test.db'), frontend_dir)
            self.base_url = self.server.base_url
            self.port = self.server.port
            self.api = self.server.api
            self.raw = self.server.raw
            self.request = self.server.request
            self._register()
            self._seed()
            if browser:
                self.browser = Chrome(os.path.join(self.workdir, 'profile'))
                self.cdp = self.browser.connect(self.base_url)
                self._open_page(intercept)
        except Exception:
            self.close()
            raise

    def start_server(self, db_name, env=None):
        """Another server with its own database (and environment), stopped with the suite."""
        server = AppServer(os.path.join(self.workdir, db_name), self.frontend_dir, env)
        self.extra_servers.append(server)
        return server

    def db_path(self, db_name):
        return os.path.join(self.workdir, db_name)

    # ---- setup ------------------------------------------------------------

    def _register(self):
        _, cookie = self.api('POST', '/api/auth/register', ACCOUNT)
        self.token = cookie.split('session=')[1].split(';')[0]

    def _seed(self):
        # Ten days back so later seeds can be dated forward without reaching "today".
        self.t0 = int(time.time() * 1000) - 10 * DAY_MS
        self.W1 = self.seed('Seed Push', 0, [exercise('Bench Press', 100, 8, [(8, 100), (8, 100)]),
                                             exercise('Overhead Press', 60, 8, [(8, 60)])])
        self.W2 = self.seed('Seed Pull', 2, [exercise('Barbell Row', 80, 8, [(8, 80)])])
        self.W3 = self.seed('Seed Push', 4, [exercise('Bench Press', 105, 8, [(8, 105)]),
                                             exercise('Overhead Press', 62, 8, [(8, 62)])])

    def _open_page(self, intercept):
        for domain in ('Page', 'Runtime', 'Network'):
            self.cdp.send(f'{domain}.enable')
        if intercept:
            # Request stage for offline simulation; response stage for dropping a reply
            # after the server has already stored the workout.
            self.cdp.send('Fetch.enable', patterns=[
                {'urlPattern': '*/api/*', 'requestStage': 'Request'},
                {'urlPattern': '*/api/workouts', 'requestStage': 'Response'},
            ])
        self.set_cookie(self.token)

    # ---- data -------------------------------------------------------------

    ex = staticmethod(exercise)

    def seed(self, name, day_offset, exercises):
        """Store a finished workout straight through the API, dated `day_offset` days after t0."""
        body = {'name': name, 'notes': '', 'createdAt': self.t0 + day_offset * DAY_MS, 'exercises': exercises}
        created, _ = self.api('POST', '/api/workouts', body, self.token)
        return created['id']

    def workouts(self):
        return self.api('GET', '/api/workouts', token=self.token)[0]['workouts']

    def workout(self, workout_id):
        return next(w for w in self.workouts() if w['id'] == workout_id)

    def ids(self):
        return {w['id'] for w in self.workouts()}

    def active_session(self):
        return self.api('GET', '/api/active-session', token=self.token)[0]['session']

    def server_sets(self):
        """Total sets the server has for the in-progress workout, or None if there isn't one."""
        session = self.active_session()
        return None if session is None else sum(len(e['sets']) for e in session['exercises'])

    # ---- page -------------------------------------------------------------

    def safe_ev(self, expression, default=None):
        """Evaluate, returning `default` if the element or function is not there."""
        try:
            return self.cdp.ev(expression)
        except RuntimeError:
            return default

    def wait_for(self, predicate, timeout=12):
        """Poll a Python predicate (usually a server check) while the page keeps running."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            self.cdp.pause(0.3)
        return False

    def set_cookie(self, token):
        self.cdp.send('Network.setCookie', name='session', value=token, domain='127.0.0.1', path='/')

    def open_tracker(self):
        self.cdp.goto('/index.html')
        self.cdp.wait("document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
        self.cdp.pause(0.4)

    def start(self, index):
        """Start the nth built-in template (0 = Push Day, 1 = Pull Day, 2 = Leg Day)."""
        self.cdp.ev(f"document.querySelectorAll('#templateList [data-template-action=start]')[{index}].click()")

    def log_set(self, reps):
        self.cdp.ev(f"document.getElementById('completedReps').value = '{reps}'; "
                    "document.getElementById('completeSetBtn').click();")

    def finish_all(self):
        """Click through to the end of the workout."""
        for _ in range(8):
            if self.cdp.ev(HIDDEN):
                break
            self.cdp.ev("document.getElementById('nextExerciseBtn').click()")
            self.cdp.pause(0.25)

    def end_workout(self):
        # Accept the "End this workout?" prompt for this one click only. Replacing window.confirm
        # instead would bypass the harness's dialog stub for the rest of the page, so a later
        # `cdp.answer = False` would silently stop working. The click is synchronous, so the
        # prompt is asked before the answer is restored.
        self.cdp.ev("(() => { const previous = window.__answer; window.__answer = true; "
                    "document.getElementById('endWorkoutBtn').click(); window.__answer = previous; })()")
        self.cdp.pause(0.5)

    # ---- teardown ---------------------------------------------------------

    def close(self):
        if self.cdp:
            self.cdp.close()
        for part in (self.browser, self.server, *self.extra_servers):
            if part:
                part.stop()
        time.sleep(0.5)
        shutil.rmtree(self.workdir, ignore_errors=True)
