#!/usr/bin/env python3
"""Run the browser test suites.

    python tests/run.py                  every suite, a few at a time (at most 4)
    python tests/run.py gym_usability    one suite, in this process
    python tests/run.py --jobs 1         every suite, one at a time
    python tests/run.py --list           suite names

Each suite gets its own server, database and browser profile, so they are
independent and safe to run concurrently. Exit status is 0 only if every check
in every suite passed, and every suite ran some. A suite that runs longer than
--timeout seconds is stopped, with its server and browser, and counts as failed;
so does Ctrl-C, which stops them all.
"""

import argparse
import importlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ''):  # allow `python tests/run.py` as well as `-m tests.run`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import AppTest, find_chrome
from tests.suites import NAMES


def run_suite(name, frontend=None):
    """Run one suite in this process. Returns (passed, total)."""
    module = importlib.import_module(f'tests.suites.{name}')
    print(f'=== {name}')
    test = AppTest(frontend_dir=frontend, intercept=getattr(module, 'INTERCEPT', True),
                   browser=getattr(module, 'BROWSER', True), mail=getattr(module, 'MAIL', False))
    try:
        module.run(test)
    finally:
        test.close()
    results = test.checker.results
    passed = len(results) - len(test.checker.failures)
    print(f'{name}: {passed}/{len(results)} checks passed\n')
    if not results:
        # A suite whose checks never ran (a section skipped by an early return, say) has nothing to say it works.
        print(f'[FAIL] {name} ran no checks.\n')
        return 0, 1
    return passed, len(results)


def annotate(name, log):
    """On GitHub Actions, each failed check (or, for a suite that stopped, its last line) as an error annotation: shown on
    the run's page, and readable through the API by anyone, where the log itself needs the repository's admin."""
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    failures = [line for line in lines if line.startswith('[FAIL]')] or lines[-1:]
    for line in failures[:10]:
        # The workflow-command escapes for a message: %, then the line breaks.
        message = line[:500].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print(f'::error title={name}::{message}')


def stop_tree(process):
    """Stops a suite's process and the server and browser it started. On Linux and macOS it is asked to stop first (Ctrl-C, which
    lets the suite close them and remove its profile), then made to; Windows has no such asking, so its tree is ended at once."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def run_in_parallel(names, jobs, frontend, timeout):
    """Run each suite in its own process, at most `jobs` at a time, each for at most `timeout` seconds.

    Children write to files rather than pipes: a chatty suite would otherwise fill
    the OS pipe buffer and block forever, since the parent only reads after exit.
    """
    # Children write UTF-8 regardless of the console's code page (cp1252 on Windows); check
    # details contain characters such as the multiplication sign, and reading those back as
    # UTF-8 would otherwise crash the runner exactly when a check fails.
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if frontend:
        env['WORKOUT_TEST_FRONTEND'] = frontend
    logdir = tempfile.mkdtemp(prefix='workout-tests-run-')
    # Where the suites claim the ports they are given (see free_port), so no two are given the same one.
    ports = os.path.join(logdir, 'ports')
    os.mkdir(ports)
    env['WORKOUT_TEST_PORTS'] = ports
    running = []
    try:
        queue, finished = list(names), {}
        while queue or running:
            while queue and len(running) < jobs:
                name = queue.pop(0)
                path = os.path.join(logdir, f'{name}.log')
                handle = open(path, 'w', encoding='utf-8')
                # Its own process group, so stopping it (stop_tree) reaches the server and browser it started and nothing else.
                process = subprocess.Popen([sys.executable, os.path.abspath(__file__), name],
                                           stdout=handle, stderr=subprocess.STDOUT, env=env,
                                           start_new_session=(os.name != 'nt'))
                running.append((name, process, handle, path, time.time()))
                print(f'  ... {name} started', flush=True)
            for entry in list(running):
                name, process, handle, path, started = entry
                if process.poll() is None:
                    if time.time() - started < timeout:
                        continue
                    stop_tree(process)
                    handle.write(f'\n[FAIL] {name} was stopped after {timeout} seconds.\n')
                    handle.flush()
                    code = 124
                else:
                    code = process.returncode
                running.remove(entry)
                handle.close()
                finished[name] = (path, code)
                verdict = 'passed' if code == 0 else f'FAILED (exit {code})'
                print(f'  ... {name} {verdict}', flush=True)
            time.sleep(0.2)

        print()
        failed = []
        for name in names:
            path, code = finished[name]
            with open(path, encoding='utf-8', errors='replace') as handle:
                log = handle.read().rstrip('\n')
            print(log)
            print()
            if code != 0:
                failed.append(name)
                if os.environ.get('GITHUB_ACTIONS') == 'true':
                    annotate(name, log)
        return failed
    finally:
        # Reached with some still running only by Ctrl-C or an error here: none is left behind to hold a port or a browser.
        for _, process, handle, _, _ in running:
            stop_tree(process)
            handle.close()
        shutil.rmtree(logdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('suite', nargs='?', help='run just this suite, in this process')
    # Four is what CI runs. Every suite at once, as this once did, left each starved enough on an ordinary computer that
    # checks which wait a moment for something to happen failed that passed alone.
    parser.add_argument('--jobs', type=int, default=max(1, min(4, os.cpu_count() or 1)), help='suites to run at once (default: 4, or fewer cores)')
    parser.add_argument('--timeout', type=int, default=900, help='seconds a suite may run before it is stopped (default: 900)')
    parser.add_argument('--frontend', help='serve this directory instead of ./frontend')
    parser.add_argument('--list', action='store_true', help='list suite names and exit')
    args = parser.parse_args()

    if args.list:
        print('\n'.join(NAMES))
        return 0

    frontend = args.frontend or os.environ.get('WORKOUT_TEST_FRONTEND')

    try:
        find_chrome()
    except RuntimeError as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2

    if args.suite:
        if args.suite not in NAMES:
            print(f"ERROR: unknown suite {args.suite!r}. Known: {', '.join(NAMES)}", file=sys.stderr)
            return 2
        passed, total = run_suite(args.suite, frontend)
        return 0 if passed == total else 1

    failed = run_in_parallel(NAMES, max(1, args.jobs), frontend, args.timeout)
    print('=' * 60)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        if args.jobs > 1:
            print('A suite that fails here and passes run alone (python tests/run.py <name>) was starved: try --jobs 1 or fewer.')
        return 1
    print(f'All {len(NAMES)} suites passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
