#!/usr/bin/env python3
"""Serve the app locally with three weeks of Wendler 5/3/1 already logged, to try it on realistic data:

    python scripts/demo-server.py             this checkout, until Ctrl+C
    python scripts/demo-server.py --follow    whatever CI last passed, rebuilt each time it passes again

Then open http://localhost:6769/ and sign in as wendler-test / Wendler-531-Test. Every start is a fresh database,
so whatever is logged in it is gone at the next one; data/workouts.db is never touched.

--follow keeps its own clone of the repository in data/preview and checks every minute whether `stable` has moved,
which it does once every test has passed on a push to main (.github/workflows/tests.yml). When it has, the clone
updates, the server restarts on the new code, and the training is logged again. `--branch main` rebuilds on every
push instead, whether its tests passed or not.
"""

import argparse
import contextlib
import http.client
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIEW_DIR = os.path.join(ROOT, 'data', 'preview')
USERNAME, EMAIL, PASSWORD = 'wendler-test', 'wendler-test@example.com', 'Wendler-531-Test'
DAY_MS = 86400000

# ---- Three weeks of Wendler 5/3/1 ---------------------------------------------------------------------------------
# Built as the app builds them (wendler531.workout in program-definitions.js, finishWorkout in script.js): warm-ups at
# 40, 50 and 60% of the training max, the week's three sets with a + set last, Boring But Big's 5 x 10 at 50%, then
# the day's assistance exercise. Every + set beats its target by a few reps. The cycle's deload week is still to do.
ROUNDING = 5
TRAINING_MAXES = {'press': 120, 'deadlift': 315, 'bench': 185, 'squat': 245}
LIFTS = [('press', 'Overhead Press', 'Press Day'), ('deadlift', 'Deadlift', 'Deadlift Day'),
         ('bench', 'Bench Press', 'Bench Day'), ('squat', 'Back Squat', 'Squat Day')]
WEEKS = [('5s week', [(65, 5), (75, 5), (85, 5)]), ('3s week', [(70, 3), (80, 3), (90, 3)]),
         ('5/3/1 week', [(75, 5), (85, 3), (95, 1)])]
WARMUPS = [(40, 5), (50, 5), (60, 3)]
# What Boring But Big adds after the day's 5 x 10: (name, sets, reps, weight logged, rest in seconds).
ASSISTANCE = {'press': ('Chin-up', 5, 10, 0, 90), 'deadlift': ('Hanging Leg Raise', 5, 15, 0, 60),
              'bench': ('Dumbbell Row', 5, 10, 50, 90), 'squat': ('Leg Curl', 5, 10, 90, 60)}
AMRAP_BONUS = [3, 2, 4]  # reps past the + set's target, week by week
NOTES = {2: 'Grip felt shaky on the deadlift set.', 7: 'Bench felt easy today, good pace.',
         11: 'Squat depth was solid all session.'}


def round_to_step(value, step):
    """roundToStep in program.js, with Math.round's halves going up where Python's round() goes to even."""
    rounded = max(step, math.floor(math.floor(value / step + 0.5) * step * 100 + 0.5) / 100)
    return int(rounded) if rounded == int(rounded) else rounded


def demo_training():
    """Twelve workouts, oldest first, every other day until two days ago, and the program as they leave it."""
    today_noon = time.mktime(time.localtime()[:3] + (12, 0, 0, 0, 0, -1)) * 1000
    days = [(week, day) for week in range(len(WEEKS)) for day in range(len(LIFTS))]
    workouts, done = [], {}
    for index, (week, day) in enumerate(days):
        key, lift, day_name = LIFTS[day]
        week_name, work = WEEKS[week]
        weight = lambda percent: round_to_step(TRAINING_MAXES[key] * percent / 100, ROUNDING)  # noqa: E731
        sets = [{'weight': weight(percent), 'reps': reps} for percent, reps in WARMUPS]
        sets += [{'weight': weight(percent), 'reps': reps + (AMRAP_BONUS[week] if number == len(work) - 1 else 0)}
                 for number, (percent, reps) in enumerate(work)]
        bbb = weight(50)
        name, count, reps, load, rest = ASSISTANCE[key]
        exercises = [
            {'name': lift, 'weight': sets[-1]['weight'], 'reps': sets[-1]['reps'], 'sets': sets, 'rest': 180},
            {'name': f'{lift} (BBB)', 'weight': bbb, 'reps': 10, 'sets': [{'weight': bbb, 'reps': 10} for _ in range(5)],
             'rest': 90},
            {'name': name, 'weight': load, 'reps': reps, 'sets': [{'weight': load, 'reps': reps} for _ in range(count)],
             'rest': rest},
        ]
        created = int(today_noon - (len(days) - index) * 2 * DAY_MS)
        workouts.append({
            'name': f'5/3/1 {day_name}', 'notes': NOTES.get(index, ''), 'exercises': exercises, 'createdAt': created,
            'clientId': f'demo-531-{index}', 'unit': 'lbs', 'duration': 3300 + day * 180,
            'program': {'name': 'Wendler 5/3/1', 'cycle': 1, 'week': week + 1,
                        'label': f'Cycle 1, week {week + 1} · {week_name}'},
        })
        done[f'{week}-{day}'] = {'at': created, 'skipped': False, 'hit': True,
                                 'amrap': {'weight': sets[-1]['weight'], 'reps': sets[-1]['reps'], 'target': work[-1][1]}}
    program = {'definition': 'wendler-531', 'unit': 'lbs', 'startedAt': workouts[0]['createdAt'], 'cycle': 1,
               'trainingMaxes': TRAINING_MAXES, 'stalls': {}, 'done': done, 'lastRollover': None,
               'options': {'tmPercent': 90, 'assistance': 'bbb', 'rounding': ROUNDING, 'warmups': True, 'deload': True}}
    return workouts, program


# ---- The server ---------------------------------------------------------------------------------------------------

class DemoServer:
    """backend/server.py from app_dir on a fresh database, with the demo account signed up and its training logged."""

    def __init__(self, app_dir, port, db_path, log_path):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'something is already listening on port {port}: stop it, or pass --port')
        for suffix in ('', '-wal', '-shm'):
            with contextlib.suppress(FileNotFoundError):
                os.remove(db_path + suffix)
        self.port, self.log_path = port, log_path
        env = dict(os.environ, PORT=str(port), WORKOUT_DB=db_path, APP_ROOT=os.path.join(app_dir, 'frontend'),
                   ALLOW_REGISTRATION='1', PYTHONUNBUFFERED='1')
        self.log = open(log_path, 'w', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, os.path.join(app_dir, 'backend', 'server.py')], env=env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        try:
            self._await_ready()
            self._log_training()
        except BaseException:
            self.stop()
            raise

    def api(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/json', **({'Cookie': f'session={token}'} if token else {})}
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        if response.status >= 400:
            raise RuntimeError(f'{method} {path} answered {response.status}: {data.decode(errors="replace")}')
        return json.loads(data) if data else None, response.getheader('Set-Cookie')

    def _await_ready(self):
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f'the server exited with code {self.process.returncode}; see {self.log_path}')
            try:
                self.api('GET', '/api/auth/me')
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f'the server did not answer on port {self.port} within 20 seconds; see {self.log_path}')

    def _log_training(self):
        _, cookie = self.api('POST', '/api/auth/register', {'username': USERNAME, 'email': EMAIL, 'password': PASSWORD})
        token = cookie.split('session=')[1].split(';')[0]
        workouts, program = demo_training()
        for workout in workouts:
            self.api('POST', '/api/workouts', workout, token)
        self.api('PUT', '/api/state', {'program': program}, token)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        self.log.close()


def stamp():
    return time.strftime('%H:%M:%S')


def announce(server, commit):
    print(f'{stamp()} Serving {commit} at http://localhost:{server.port}/ - sign in as {USERNAME} / {PASSWORD}')


def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=300).stdout.strip()


# ---- Following CI -------------------------------------------------------------------------------------------------

def remote_head(repo, branch):
    """The commit the branch is on now, or None while it cannot be asked (no network, say)."""
    try:
        listing = git('ls-remote', repo, f'refs/heads/{branch}')
    except (OSError, subprocess.SubprocessError):
        return None
    return listing.split()[0] if listing else None


def check_out(repo, branch, clone):
    """The clone at the branch's newest commit, fetched afresh; returns that commit."""
    if not os.path.isdir(os.path.join(clone, '.git')):
        shutil.rmtree(clone, ignore_errors=True)
        git('clone', '--quiet', '--depth', '1', '--branch', branch, repo, clone)
    else:
        git('remote', 'set-url', 'origin', repo, cwd=clone)
        git('fetch', '--quiet', '--force', '--depth', '1', 'origin', branch, cwd=clone)
        git('checkout', '--quiet', '--force', '--detach', 'FETCH_HEAD', cwd=clone)
        git('clean', '--quiet', '-fdx', cwd=clone)
    return git('rev-parse', 'HEAD', cwd=clone)


def follow(args):
    clone = os.path.join(PREVIEW_DIR, 'app')
    db_path, log_path = os.path.join(PREVIEW_DIR, 'workouts.db'), os.path.join(PREVIEW_DIR, 'server.log')
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    server = served = None
    print(f'Following {args.branch} on {args.repo}, checking every {args.interval} seconds. Ctrl+C stops.')
    try:
        while True:
            head = remote_head(args.repo, args.branch)
            if head and head != served:
                if server:
                    server.stop()
                    server = None
                try:
                    served = check_out(args.repo, args.branch, clone)
                    server = DemoServer(clone, args.port, db_path, log_path)
                    announce(server, git('log', '-1', '--format=%h %s', cwd=clone))
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    # Tried again at the next check, so a busy port or a dropped connection sorts itself out.
                    served = None
                    print(f'{stamp()} Could not serve {head[:7]}: {error}')
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.stop()


def serve_checkout(args):
    workdir = tempfile.mkdtemp(prefix='workout-demo-')
    try:
        server = DemoServer(ROOT, args.port, os.path.join(workdir, 'workouts.db'), os.path.join(workdir, 'server.log'))
        try:
            announce(server, f'{git("log", "-1", "--format=%h %s")} (this checkout, with any uncommitted changes)')
            server.process.wait()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    # Commit subjects can hold characters a Windows console cannot show; they print as ? rather than stopping it.
    sys.stdout.reconfigure(line_buffering=True, errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--follow', action='store_true', help='serve what CI last passed, and rebuild when it passes again')
    parser.add_argument('--branch', default='stable', help='the branch --follow serves (default: stable)')
    parser.add_argument('--repo', help="the repository --follow clones (default: this checkout's origin)")
    parser.add_argument('--port', type=int, default=6769, help='the port to serve on (default: 6769)')
    parser.add_argument('--interval', type=int, default=60, help='seconds between checks with --follow (default: 60)')
    args = parser.parse_args()
    if args.follow:
        args.repo = args.repo or git('remote', 'get-url', 'origin')
        follow(args)
    else:
        serve_checkout(args)


if __name__ == '__main__':
    main()
