#!/usr/bin/env python3
"""Run the browser test suites.

    python tests/run.py                  every suite, in parallel
    python tests/run.py gym_usability    one suite, in this process
    python tests/run.py --jobs 1         every suite, one at a time
    python tests/run.py --list           suite names

Each suite gets its own server, database and browser profile, so they are
independent and safe to run concurrently. Exit status is 0 only if every check
in every suite passed.
"""

import argparse
import importlib
import os
import shutil
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
    test = AppTest(frontend_dir=frontend, intercept=getattr(module, 'INTERCEPT', True))
    try:
        module.run(test)
    finally:
        test.close()
    results = test.checker.results
    passed = len(results) - len(test.checker.failures)
    print(f'{name}: {passed}/{len(results)} checks passed\n')
    return passed, len(results)


def run_in_parallel(names, jobs, frontend):
    """Run each suite in its own process, at most `jobs` at a time.

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
    try:
        queue, running, finished = list(names), [], {}
        while queue or running:
            while queue and len(running) < jobs:
                name = queue.pop(0)
                path = os.path.join(logdir, f'{name}.log')
                handle = open(path, 'w', encoding='utf-8')
                process = subprocess.Popen([sys.executable, os.path.abspath(__file__), name],
                                           stdout=handle, stderr=subprocess.STDOUT, env=env)
                running.append((name, process, handle, path))
                print(f'  ... {name} started', flush=True)
            for entry in list(running):
                name, process, handle, path = entry
                if process.poll() is None:
                    continue
                running.remove(entry)
                handle.close()
                finished[name] = (path, process.returncode)
                verdict = 'passed' if process.returncode == 0 else f'FAILED (exit {process.returncode})'
                print(f'  ... {name} {verdict}', flush=True)
            time.sleep(0.2)

        print()
        failed = []
        for name in names:
            path, code = finished[name]
            with open(path, encoding='utf-8', errors='replace') as handle:
                print(handle.read().rstrip('\n'))
            print()
            if code != 0:
                failed.append(name)
        return failed
    finally:
        shutil.rmtree(logdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('suite', nargs='?', help='run just this suite, in this process')
    parser.add_argument('--jobs', type=int, default=len(NAMES), help='suites to run at once (default: all)')
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

    failed = run_in_parallel(NAMES, max(1, args.jobs), frontend)
    print('=' * 60)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f'All {len(NAMES)} suites passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
