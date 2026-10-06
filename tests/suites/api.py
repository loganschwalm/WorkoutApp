"""The HTTP API on its own, without a browser: bad input, racing uploads, redirects, database upgrades and accounts."""

import csv
import datetime
import gzip
import hashlib
import io
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from ..harness import REPO_ROOT, load_server

INTERCEPT = False
BROWSER = False
MAIL = True

# The schema version a database ends up at once every migration has run.
LATEST_SCHEMA = len(load_server().MIGRATIONS)

# The schema as it was before workouts had a client_id column, for the upgrade check.
OLD_SCHEMA = '''
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                           expires_at INTEGER NOT NULL);
    CREATE TABLE workouts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                           name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE active_sessions (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                                  payload TEXT NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE user_state (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                             settings_json TEXT NOT NULL DEFAULT '{}', templates_json TEXT NOT NULL DEFAULT '[]',
                             updated_at INTEGER NOT NULL);
'''


def run(t):
    check, api, token = t.check, t.api, t.token
    json_headers = {'Content-Type': 'application/json'}

    def request(*args, **kwargs):
        """t.request, but a dropped connection becomes a failed check instead of ending the suite."""
        try:
            return t.request(*args, **kwargs)
        except OSError as error:  # includes http.client.RemoteDisconnected
            return None, {}, f'no response: {error!r}'

    def workout(client_id, name='Race'):
        return {'name': name, 'notes': '', 'createdAt': int(time.time() * 1000), 'clientId': client_id,
                'exercises': [t.ex('Squat', 100, 5, [(5, 100)])]}

    # ------------------------------------------------------------------ A1 malformed bodies
    print('A1  malformed request bodies get a clear 4xx, not a dropped connection')
    cases = [
        ('broken JSON', 'POST', '/api/auth/login', b'{oops', 400),
        ('a JSON array', 'POST', '/api/auth/login', b'[1]', 400),
        ('a bare JSON string', 'POST', '/api/auth/register', b'"text"', 400),
        ('bytes that are not UTF-8', 'POST', '/api/auth/login', b'\xff\xfe\x00', 400),
        ('broken JSON, signed in', 'POST', '/api/workouts', b'{"name":', 400),
        ('an array as a workout', 'POST', '/api/workouts', b'[]', 400),
        ('an array as state', 'PUT', '/api/state', b'[]', 400),
        ('broken JSON as an active session', 'POST', '/api/active-session', b'{{', 400),
    ]
    for label, method, path, body, expected in cases:
        status, _, reply = request(method, path, body, json_headers, token=token)
        check(f'{label} -> {expected} with a message', status == expected and isinstance(reply, dict) and reply.get('error'),
              f'{status} {reply!r}')

    status, _, reply = request('POST', '/api/workouts', b'{}', {'Content-Length': 'lots'}, token=token)
    check('a nonsense Content-Length -> 400', status == 400, f'{status} {reply!r}')
    status, _, reply = request('POST', '/api/workouts', None, {'Content-Length': str(50 * 1024 * 1024)}, token=token)
    check('a 50 MB body is refused before it is read -> 413', status == 413 and reply.get('error'), f'{status} {reply!r}')
    n = len(t.workouts())
    check('none of that stored anything', n == 3, n)
    status, _, reply = request('GET', '/api/auth/me', token=token)
    check('the server is still answering normally', status == 200 and reply['user']['username'] == 'tester', f'{status} {reply!r}')

    # ------------------------------------------------------------------ A2 racing uploads
    print('A2  the same workout uploaded many times at once is stored once')
    # One burst rarely loses the race; before the unique index, 24 threads over 40 rounds duplicated in
    # most rounds. Eight rounds keeps this quick while still failing reliably if the guard regresses.
    rounds, width = 8, 24
    results = {}

    def burst(client_id):
        body = json.dumps(workout(client_id)).encode()
        barrier = threading.Barrier(width)
        answers = results.setdefault(client_id, [])

        def upload():
            barrier.wait()
            status, _, reply = request('POST', '/api/workouts', body, json_headers, token=token)
            answers.append((status, reply.get('id') if isinstance(reply, dict) else None))

        threads = [threading.Thread(target=upload) for _ in range(width)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    for index in range(rounds):
        burst(f'race-{index}')
    listed = t.workouts()
    copies = {client_id: [w['id'] for w in listed if w.get('clientId') == client_id] for client_id in results}
    check(f'{rounds} bursts of {width} identical uploads store exactly one copy each',
          all(len(ids) == 1 for ids in copies.values()), str({k: len(v) for k, v in copies.items()}))
    statuses = [sorted(s for s, _ in answers) for answers in results.values()]
    check('every upload was answered: one 201, the rest 200',
          all(s == [200] * (width - 1) + [201] for s in statuses), str(statuses[:2]))
    check('and every answer names the stored workout',
          all({i for _, i in results[k]} == set(copies[k]) for k in results), '')
    stored = [w for w in listed if w.get('clientId') == 'race-0']
    other_body = workout('race-0')
    _, cookie = api('POST', '/api/auth/register', {'username': 'racer', 'email': 'racer@example.test', 'password': 'chalk-and-plates-42'})
    other = cookie.split('session=')[1].split(';')[0]
    created, _ = api('POST', '/api/workouts', other_body, other)
    check('another account can still use the same clientId', created['id'] != stored[0]['id'] if stored else False, str(created))
    blank, _ = api('POST', '/api/workouts', workout('', 'No id A'), token)
    blank2, _ = api('POST', '/api/workouts', workout('', 'No id B'), token)
    check('workouts without a clientId are never merged', blank['id'] != blank2['id'], f'{blank} {blank2}')

    # ------------------------------------------------------------------ A3 upgrading an existing database
    print('A3  a database from before client_id upgrades in place')
    legacy_path = t.db_path('legacy.db')
    db = sqlite3.connect(legacy_path)
    db.executescript(OLD_SCHEMA)
    db.execute("INSERT INTO users (id, username, password_hash, created_at) VALUES (1, 'old', 'x$y', 0)")
    db.execute("INSERT INTO sessions VALUES ('legacy-token', 1, ?)", (int(time.time()) + 3600,))
    rows = [('Dup first', 'dup'), ('Dup second', 'dup'), ('Solo', 'solo'), ('No client id', None)]
    for index, (name, client_id) in enumerate(rows):
        payload = {'name': name, 'notes': '', 'exercises': [], 'createdAt': index}
        if client_id:
            payload['clientId'] = client_id
        db.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload) VALUES (1, ?, ?, ?, ?)',
                   (name, '', index, json.dumps(payload)))
    db.commit()
    db.close()

    legacy = t.start_server('legacy.db')
    listed = legacy.api('GET', '/api/workouts', token='legacy-token')[0]['workouts']
    check('the server starts and every old workout is still there', len(listed) == 4, len(listed))
    first_dup = min(w['id'] for w in listed if w['name'].startswith('Dup'))
    again, _ = legacy.api('POST', '/api/workouts', {'name': 'Dup retry', 'clientId': 'dup', 'exercises': []}, 'legacy-token')
    check('a retry of an already-duplicated upload maps to the first copy', again['id'] == first_dup, f"{again} vs {first_dup}")
    solo_id = next(w['id'] for w in listed if w['name'] == 'Solo')
    again, _ = legacy.api('POST', '/api/workouts', {'name': 'Solo retry', 'clientId': 'solo', 'exercises': []}, 'legacy-token')
    check('a retry of an old upload is recognised', again['id'] == solo_id, f'{again} vs {solo_id}')
    check('neither retry added a row', len(legacy.api('GET', '/api/workouts', token='legacy-token')[0]['workouts']) == 4)
    db = sqlite3.connect(legacy_path)
    stored = [row[0] for row in db.execute('SELECT token FROM sessions')]
    db.close()
    check("its sessions were rehashed in place, so the upgrade signed nobody out",
          stored == [hashlib.sha256(b'legacy-token').hexdigest()], stored)
    db = sqlite3.connect(legacy_path)
    indexes = [row[1] for row in db.execute("PRAGMA index_list('workouts')")]
    db.close()
    check('the unique index now exists', 'workouts_user_client' in indexes, str(indexes))

    # ------------------------------------------------------------------ A4 /frontend/ paths
    print('A4  old /frontend/ links redirect to the one real path')
    for path, expected in [('/frontend/index.html', '/index.html'),
                           ('/frontend/index.html?start=3', '/index.html?start=3'),
                           ('/frontend/', '/'),
                           ('/frontend', '/'),
                           ('/frontend/script.js', '/script.js'),
                           ('/frontend//evil.example/x', '/evil.example/x'),
                           ('/frontend/%5Cevil.example', '/%5Cevil.example'),
                           ('/frontend/\\\\evil.example', '/evil.example')]:
        status, location = t.raw('GET', path)
        check(f'{path} -> {expected}', status == 301 and location == expected, f'{status} {location}')
    status, _ = t.raw('GET', '/script.js')
    check('the real path is served directly', status == 200, status)
    for page in ('/index.html', '/cardio.html', '/progress.html', '/history.html'):
        status, location = t.raw('GET', page)
        check(f'signed out, {page} leads to signing in, and back', status == 303 and location == f'/login.html?next={page.replace("/", "%2F")}',
              f'{status} {location}')

    run_security(t, check, request)
    run_limits(t, check)
    run_sessions(t, check)
    run_connections(t, check)
    run_structure(t, check, request)
    run_accounts(t, check, request)
    run_admin(t, check, request)
    run_export(t, check, request)
    run_account_security(t, check, request)
    run_compression(t, check, request)
    run_deletion(t, check, request)
    run_state_merge(t, check, request)
    run_routes(t, check, request)
    run_bursts(t, check)


def login(server, username, password, headers=None):
    body = json.dumps({'username': username, 'password': password}).encode()
    return server.request('POST', '/api/auth/login', body, {'Content-Type': 'application/json', **(headers or {})})


def run_security(t, check, request):
    main = t.server
    db_path = t.db_path('test.db')

    def stored_hash(username, path=db_path):
        db = sqlite3.connect(path)
        row = db.execute('SELECT password_hash FROM users WHERE username = ?', (username,)).fetchone()
        db.close()
        return row[0] if row else None

    # ------------------------------------------------------------------ A5 registration switch
    print('A5  ALLOW_REGISTRATION=0 closes sign-up but not sign-in')
    check('registration is open by default', main.api('GET', '/api/auth/me')[0].get('registrationOpen') is True)
    opener = t.start_server('closed.db')
    opener.api('POST', '/api/auth/register', {'username': 'owner', 'email': 'owner@example.test', 'password': 'chalk-and-plates-42'})
    opener.stop()
    opener.process.wait(timeout=10)
    closed = t.start_server('closed.db', {'ALLOW_REGISTRATION': '0'})
    check('the server says registration is closed', closed.api('GET', '/api/auth/me')[0].get('registrationOpen') is False)
    status, _, reply = closed.request('POST', '/api/auth/register', json.dumps({'username': 'intruder', 'email': 'intruder@example.test', 'password': 'chalk-and-plates-42'}).encode(),
                                      {'Content-Type': 'application/json'})
    check('registering is refused with 403', status == 403 and 'turned off' in reply.get('error', ''), f'{status} {reply}')
    check('and no account was created', stored_hash('intruder', t.db_path('closed.db')) is None)
    status, headers, _ = login(closed, 'owner', 'chalk-and-plates-42')
    check('an existing account still signs in', status == 200 and 'session=' in headers.get('set-cookie', ''), status)

    # ------------------------------------------------------------------ A6 sign-in throttling
    print('A6  repeated failed sign-ins are slowed down')
    main.api('POST', '/api/auth/register', {'username': 'target', 'email': 'target@example.test', 'password': 'right-password'})
    statuses = [login(main, 'target', f'wrong-guess-{n}')[0] for n in range(5)]
    check('the first five wrong passwords are just refused', statuses == [401] * 5, statuses)
    status, headers, reply = login(main, 'target', 'wrong-guess-6')
    check('the sixth is told to wait, with Retry-After', status == 429 and int(headers.get('retry-after', 0)) > 800,
          f"{status} {headers.get('retry-after')} {reply}")
    status, _, _ = login(main, 'target', 'right-password')
    check('even the right password waits, so guessing cannot continue', status == 429, status)
    check('another username from the same address is unaffected', login(main, 'tester', 'chalk-and-plates-42')[0] == 200)
    check('a different case of the same username shares the limit', login(main, 'TARGET', 'wrong-guess-7')[0] == 429)

    # Each failed sign-in costs a full-strength hash (0.15 s here, more under load), so the window must
    # comfortably outlast five of them; the wait is then measured from the first failure. The server notes a
    # failure after hashing, just before it answers, so the clock starts once the first answer is back: timed
    # from before the request, a hash slowed by the other suites made the wait end with that failure still
    # inside the window.
    window = 8
    quick = t.start_server('quick.db', {'LOGIN_WINDOW': str(window)})
    quick.api('POST', '/api/auth/register', {'username': 'target', 'email': 'target@example.test', 'password': 'right-password'})
    login(quick, 'target', 'wrong-password-0')
    first_failure = time.monotonic()
    for n in range(1, 5):
        login(quick, 'target', f'wrong-password-{n}')
    check(f'with a {window} second window the limit applies too', login(quick, 'target', 'right-password')[0] == 429)
    time.sleep(max(0, first_failure + window + 0.5 - time.monotonic()))
    check('and lifts once the failures are older than the window', login(quick, 'target', 'right-password')[0] == 200)
    for n in range(4):
        login(quick, 'target', f'before-password-{n}')
    check('four failures and then the right password signs in', login(quick, 'target', 'right-password')[0] == 200)
    after = [login(quick, 'target', f'after-password-{n}')[0] for n in range(5)]
    check('that success forgot the four, so five more tries are each just refused', after == [401] * 5, after)

    # ------------------------------------------------------------------ A38 one address, many usernames
    print('A38 one address trying many usernames waits too, and signing in does not end that')
    spread = t.start_server('spread.db', {'LOGIN_ADDRESS_ATTEMPTS': '4', 'LOGIN_WINDOW': str(window)})
    for name in ('target', 'second'):
        spread.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'right-password'})
    statuses = [login(spread, 'target', 'wrong-guess')[0]]
    first_failure = time.monotonic()
    statuses += [login(spread, name, 'wrong-guess')[0] for name in ('second', 'nobody-1', 'nobody-2')]
    check('four wrong sign-ins, each a different username, are each just refused', statuses == [401] * 4, statuses)
    status, headers, reply = login(spread, 'nobody-3', 'wrong-guess')
    check('the fifth, under yet another username, is told to wait, saying why, with Retry-After', status == 429
          and 'from this address' in (reply or {}).get('error', '') and 0 < int(headers.get('retry-after', 0)) <= window + 1, f"{status} {headers.get('retry-after')} {reply}")
    check('and so is the right password for a real account', login(spread, 'second', 'right-password')[0] == 429)
    time.sleep(max(0, first_failure + window + 0.5 - time.monotonic()))
    check('it lifts once the failures are older than the window', login(spread, 'second', 'right-password')[0] == 200)
    statuses = [login(spread, f'nobody-{n}', 'wrong-guess')[0] for n in range(2)] + [login(spread, 'target', 'right-password')[0]]
    statuses += [login(spread, f'nobody-{n}', 'wrong-guess')[0] for n in range(2, 5)]
    check('signing into an account between guesses does not start the count again', statuses == [401, 401, 200, 401, 401, 429], statuses)
    spread.stop()
    unlimited = t.start_server('unlimited.db', {'LOGIN_ADDRESS_ATTEMPTS': '0'})
    statuses = [login(unlimited, f'nobody-{n}', 'wrong-guess')[0] for n in range(8)]
    check('LOGIN_ADDRESS_ATTEMPTS=0 turns it off, for a server behind a shared reverse proxy', statuses == [401] * 8, statuses)
    unlimited.stop()

    # ------------------------------------------------------------------ A39 behind a trusted reverse proxy
    print('A39 behind a proxy TRUSTED_PROXIES names, each person is limited apart; a header from anyone else is not believed')

    def guesses(server, forwarded, count):
        return [login(server, f'nobody-{n}', 'wrong-guess', {'X-Forwarded-For': forwarded})[0] for n in range(count)]
    # The suite's requests come from 127.0.0.1, which plays the proxy; 10.0.0.0/8 is a second proxy in front of it.
    proxied = t.start_server('proxied.db', {'TRUSTED_PROXIES': '127.0.0.1, 10.0.0.0/8', 'LOGIN_ADDRESS_ATTEMPTS': '3', 'LOGIN_WINDOW': '600'})
    statuses = guesses(proxied, '203.0.113.5', 4)
    check('one person behind the proxy waits after their own failures', statuses == [401, 401, 401, 429], statuses)
    check('and someone else behind it does not', guesses(proxied, '203.0.113.6', 1) == [401])
    check('an address the client wrote in front of the real one is not believed',
          guesses(proxied, '198.51.100.1, 203.0.113.5', 1) == [429])
    check('a further trusted proxy is looked past, to the client in front of it', guesses(proxied, '203.0.113.5, 10.1.2.3', 1) == [429])
    check('an address with a port, as some proxies write it, is the same address', guesses(proxied, '203.0.113.5:51234', 1) == [429])
    check('nonsense in the header leaves the request to the proxy’s own address, and answers as usual', guesses(proxied, 'unknown', 1) == [401])
    proxied.stop()
    direct = t.start_server('direct.db', {'LOGIN_ADDRESS_ATTEMPTS': '3', 'LOGIN_WINDOW': '600'})
    statuses = [login(direct, f'nobody-{n}', 'wrong-guess', {'X-Forwarded-For': f'203.0.113.{n}'})[0] for n in range(4)]
    check('without TRUSTED_PROXIES, a header naming a new address each time does not escape the limit', statuses == [401, 401, 401, 429], statuses)
    direct.stop()
    refused = subprocess.run([sys.executable, os.path.join(REPO_ROOT, 'backend', 'server.py')], env={**os.environ, 'TRUSTED_PROXIES': 'my-proxy',
                             'WORKOUT_DB': t.db_path('refused.db'), 'PORT': '0'}, capture_output=True, text=True, timeout=60)
    check('a TRUSTED_PROXIES that is not addresses stops the server from starting, saying why',
          refused.returncode != 0 and 'TRUSTED_PROXIES' in refused.stderr, f'{refused.returncode} {refused.stderr[-200:]}')

    # ------------------------------------------------------------------ A33 password hashing cannot take every core
    print('A33 a flood of sign-ins can only take a set number of cores, and signed-in pages stay quick')
    capped = t.start_server('capped.db', {'PASSWORD_HASHERS': '1', 'PASSWORD_HASH_WAIT': '0.3'})
    capped.api('POST', '/api/auth/register', {'username': 'regular', 'email': 'regular@example.test', 'password': 'chalk-and-plates-42'})
    _, cookie = capped.api('POST', '/api/auth/login', {'login': 'regular', 'password': 'chalk-and-plates-42'})
    token = cookie.split('session=')[1].split(';')[0]
    answers, quick = [], []

    def flood(n):
        answers.append(login(capped, f'nobody-{n}', 'chalk-and-plates-42'))

    threads = [threading.Thread(target=flood, args=(n,)) for n in range(12)]
    for thread in threads:
        thread.start()
    time.sleep(0.1)
    started = time.monotonic()
    status, _, _ = capped.request('GET', '/api/workouts', token=token)
    quick.append((status, time.monotonic() - started))
    for thread in threads:
        thread.join()
    statuses = sorted(answer[0] for answer in answers)
    busy = [answer for answer in answers if answer[0] == 503]
    check('with one hasher and twelve at once, the ones kept waiting are told the server is busy', busy and 401 in statuses
          and set(statuses) <= {401, 503}, statuses)
    check('with a Retry-After and a reason', busy and busy[0][1].get('retry-after') == '1' and 'busy' in busy[0][2].get('error', ''),
          busy and (busy[0][1].get('retry-after'), busy[0][2]))
    check('a signed-in page answers meanwhile, without waiting on the hashing', quick[0][0] == 200 and quick[0][1] < 0.5, quick)
    check('and once the flood is over, signing in works', login(capped, 'regular', 'chalk-and-plates-42')[0] == 200)
    capped.stop()

    # ------------------------------------------------------------------ A7 password hashes
    print('A7  password hashes use 600k iterations, and older hashes are upgraded on sign-in')
    stored = stored_hash('tester')
    check('a new account is hashed with PBKDF2-SHA256 at 600,000 iterations', stored.startswith('pbkdf2_sha256$600000$'), stored[:30])
    salt = 'legacysalt0123456789'
    legacy = f"{salt}${hashlib.pbkdf2_hmac('sha256', b'old-password', salt.encode(), 120000).hex()}"
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO users (username, password_hash, created_at) VALUES ('veteran', ?, 0)", (legacy,))
    db.commit()
    db.close()
    check('an account with an old-format hash can sign in', login(main, 'veteran', 'old-password')[0] == 200)
    upgraded = stored_hash('veteran')
    check('and its hash is upgraded in place', upgraded.startswith('pbkdf2_sha256$600000$') and upgraded != legacy, upgraded[:30])
    check('the upgraded hash still accepts the password', login(main, 'veteran', 'old-password')[0] == 200)
    check('and still refuses a wrong one', login(main, 'veteran', 'not-the-password')[0] == 401)

    def timed(username):
        started = time.perf_counter()
        login(main, username, 'some-wrong-password')
        return time.perf_counter() - started

    # Taken in turn, so a burst of load from the suites running beside this one slows both kinds alike, rather than all
    # of one kind: three of each in a row once measured 0.21 s against 0.48 s on a busy CI machine, for the same work.
    # An account of its own, since five wrong tries reach the sign-in limit, and later checks sign in as veteran.
    main.api('POST', '/api/auth/register', {'username': 'clockwatch', 'email': 'clockwatch@example.test', 'password': 'chalk-and-plates-42'})
    pairs = [(timed('clockwatch'), timed(f'nobody-{n}')) for n in range(5)]
    known = sorted(pair[0] for pair in pairs)[2]
    unknown = sorted(pair[1] for pair in pairs)[2]
    check('an unknown username takes about as long as a wrong password', unknown > known * 0.5,
          f'unknown {unknown:.3f}s, known {known:.3f}s')

    # ------------------------------------------------------------------ A8 cookies
    print('A8  the session cookie is marked Secure behind HTTPS')
    _, headers, _ = login(main, 'tester', 'chalk-and-plates-42')
    cookie = headers['set-cookie']
    check('plain HTTP: HttpOnly and SameSite, no Secure',
          'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Secure' not in cookie, cookie)
    _, headers, _ = login(main, 'tester', 'chalk-and-plates-42', {'X-Forwarded-Proto': 'https'})
    check('a proxy reporting HTTPS gets a Secure cookie', headers['set-cookie'].endswith('; Secure'), headers['set-cookie'])
    secure = t.start_server('secure.db', {'SECURE_COOKIES': '1'})
    secure.api('POST', '/api/auth/register', {'username': 'someone', 'email': 'someone@example.test', 'password': 'chalk-and-plates-42'})
    _, headers, _ = login(secure, 'someone', 'chalk-and-plates-42')
    check('SECURE_COOKIES=1 marks it Secure without a proxy', headers['set-cookie'].endswith('; Secure'), headers['set-cookie'])

    # ------------------------------------------------------------------ A9 expired sessions
    print('A9  expired sessions are deleted')
    tester_id = main.api('GET', '/api/auth/me', token=t.token)[0]['user']['id']
    db = sqlite3.connect(db_path)
    db.executemany('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)', [(f'stale-{n}', tester_id, 1000 + n) for n in range(5)])
    db.commit()
    db.close()
    login(main, 'tester', 'chalk-and-plates-42')
    db = sqlite3.connect(db_path)
    stale = db.execute("SELECT COUNT(*) FROM sessions WHERE token LIKE 'stale-%'").fetchone()[0]
    live = db.execute('SELECT COUNT(*) FROM sessions WHERE token = ?', (hashlib.sha256(t.token.encode()).hexdigest(),)).fetchone()[0]
    raw = db.execute('SELECT COUNT(*) FROM sessions WHERE token = ?', (t.token,)).fetchone()[0]
    db.close()
    check('signing in clears sessions that have expired', stale == 0, stale)
    check('and keeps the ones that have not', live == 1 and main.api('GET', '/api/auth/me', token=t.token)[0]['user'] is not None)
    check('a session is stored as a hash of its token, never the token itself', raw == 0, raw)

    # ------------------------------------------------------------------ A10 headers
    print('A10 every response carries the security headers and an exact content type')
    for path, token in [('/index.html', t.token), ('/login.html', None), ('/script.js', None), ('/api/auth/me', None),
                        ('/api/workouts', t.token), ('/no-such-file', None)]:
        status, headers, _ = request('GET', path, token=token)
        csp = headers.get('content-security-policy', '')
        check(f'{path} ({status}) has CSP, nosniff and frame protection',
              "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and headers.get('x-content-type-options') == 'nosniff'
              and headers.get('x-frame-options') == 'DENY',
              str({k: v for k, v in headers.items() if k.startswith(('content-security', 'x-'))}))
    for path, expected in [('/script.js', 'text/javascript'), ('/styles.css', 'text/css'), ('/login.html', 'text/html'),
                           ('/manifest.webmanifest', 'application/manifest+json'), ('/icons/icon-192.png', 'image/png')]:
        _, headers, _ = request('GET', path)
        check(f'{path} is served as {expected}', headers.get('content-type', '').startswith(expected), headers.get('content-type'))

    # ------------------------------------------------------------------ A11 directories and odd paths
    print('A11 no directory listings, and no redirects off-site')
    status, _, body = request('GET', '/icons/')
    check('/icons/ is not listed', status == 404 and b'Directory listing' not in (body if isinstance(body, bytes) else b''), status)
    for method in ('GET', 'HEAD'):
        for path in ('//evil.example', '//evil.example/', '///evil.example/', '/\\evil.example', '/%5Cevil.example', '/icons\\..\\'):
            status, headers, _ = request(method, path)
            location = headers.get('location', '')
            check(f'{method} {path} does not redirect to another site',
                  not location.startswith(('//', '/\\', 'http')) and '\\' not in location, f'{status} {location!r}')


def schema_of(path):
    db = sqlite3.connect(path)
    try:
        return {
            'version': db.execute('PRAGMA user_version').fetchone()[0],
            'journal': db.execute('PRAGMA journal_mode').fetchone()[0],
            'tables': sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")),
            'indexes': sorted(r[1] for r in db.execute("PRAGMA index_list('workouts')")),
            'columns': [r[1] for r in db.execute('PRAGMA table_info(workouts)')],
            'state_columns': [r[1] for r in db.execute('PRAGMA table_info(user_state)')],
            'user_columns': [r[1] for r in db.execute('PRAGMA table_info(users)')],
            'session_columns': [r[1] for r in db.execute('PRAGMA table_info(sessions)')],
            'user_indexes': sorted(r[1] for r in db.execute("PRAGMA index_list('users')")),
        }
    finally:
        db.close()


def run_limits(t, check):
    """What one address, or one account, can ask of a server that is open to anyone."""
    json_headers = {'Content-Type': 'application/json'}

    def post(server, path, body, token=None):
        headers = {**json_headers, **({'Cookie': f'session={token}'} if token else {})}
        return server.request('POST', path, json.dumps(body).encode(), headers)

    def make(server, name):
        return post(server, '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})

    def session_of(headers):
        return headers['set-cookie'].split('session=')[1].split(';')[0]

    # ------------------------------------------------------------------ A40 new accounts from one address
    print('A40 one address can only make so many accounts in an hour')
    open_door = t.start_server('registrations.db', {'REGISTRATIONS_PER_HOUR': '3'})
    statuses = [make(open_door, f'newcomer{n}')[0] for n in range(3)]
    check('three accounts are made', statuses == [200] * 3, statuses)
    status, headers, reply = make(open_door, 'newcomer3')
    check('the fourth is told to wait, saying why, with Retry-After', status == 429 and 'from this address' in reply.get('error', '')
          and int(headers.get('retry-after', 0)) > 3000, f"{status} {headers.get('retry-after')} {reply}")
    check('and no account was made', post(open_door, '/api/auth/login', {'login': 'newcomer3', 'password': 'chalk-and-plates-42'})[0] == 401)
    check('signing in to one already made is not held up', post(open_door, '/api/auth/login', {'login': 'newcomer0', 'password': 'chalk-and-plates-42'})[0] == 200)
    open_door.stop()
    crowd = t.start_server('registrations-unlimited.db', {'REGISTRATIONS_PER_HOUR': '0'})
    check('REGISTRATIONS_PER_HOUR=0 turns it off', [make(crowd, f'crowd{n}')[0] for n in range(8)] == [200] * 8)
    crowd.stop()
    behind = t.start_server('registrations-proxied.db', {'REGISTRATIONS_PER_HOUR': '1', 'TRUSTED_PROXIES': '127.0.0.1'})
    statuses = []
    for n, person in enumerate(('203.0.113.1', '203.0.113.2', '203.0.113.1')):
        status, _, _ = behind.request('POST', '/api/auth/register', json.dumps({'username': f'proxied{n}', 'email': f'proxied{n}@example.test', 'password': 'chalk-and-plates-42'}).encode(),
                                      {**json_headers, 'X-Forwarded-For': person})
        statuses.append(status)
    check('behind a trusted proxy each person has a limit of their own', statuses == [200, 200, 429], statuses)
    behind.stop()

    # ------------------------------------------------------------------ A41 reset emails
    print('A41 reset emails are limited per address that asks, and per email in a day, whether or not an account uses it')
    mailed = t.start_server('reset-limits.db', {**t.mail.env, 'RESET_ADDRESS_EMAILS': '4'})
    make(mailed, 'resetter')
    statuses = [post(mailed, '/api/auth/forgot-password', {'email': f'person{n}@example.test'})[0] for n in range(4)]
    check('four emails to four addresses are accepted', statuses == [200] * 4, statuses)
    status, headers, reply = post(mailed, '/api/auth/forgot-password', {'email': 'resetter@example.test'})
    check('a fifth, to whichever address, is told to wait, saying why, with Retry-After', status == 429 and 'from this address' in reply.get('error', '')
          and int(headers.get('retry-after', 0)) > 3000, f"{status} {headers.get('retry-after')} {reply}")
    check('and nothing was sent to it', not t.mail.to('resetter@example.test'))
    mailed.stop()
    # The hour's limit stops a sixth ask in the hour; what a day adds is its own count, which a clock a day wide can only show here.
    server = load_server()
    now = time.monotonic()
    server.reset_daily_throttle.events['ghost@example.test'] = [now - n * 3600 for n in range(10)]
    check('a daily limit holds after ten asks spread over the day, though no one hour held more than one',
          server.reset_daily_throttle.retry_after('ghost@example.test') > 0 and server.reset_throttle.retry_after('ghost@example.test') == 0)

    # ------------------------------------------------------------------ A42 what an account may keep
    print('A42 an account keeps only so many workouts, each only so large, and one import runs at a time')
    small = t.start_server('workout-limits.db', {'MAX_WORKOUTS': '5'})
    token = session_of(make(small, 'keeper')[1])

    def save(body):
        return post(small, '/api/workouts', body, token)

    def kept():
        return small.api('GET', '/api/workouts', token=token)[0]['workouts']
    statuses = [save({'name': f'Day {n}', 'clientId': f'keep-{n}', 'exercises': []})[0] for n in range(5)]
    check('five workouts are kept', statuses == [201] * 5, statuses)
    status, _, reply = save({'name': 'One too many', 'clientId': 'keep-5', 'exercises': []})
    check('the sixth is refused with 400, which a phone takes to mean it is kept on the device', status == 400 and 'at most 5' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = save({'name': 'Day 0', 'clientId': 'keep-0', 'exercises': []})
    check('a retry of one already kept is still answered, with its id', status == 200 and reply.get('id'), f'{status} {reply}')
    check('and the account holds five', len(kept()) == 5, len(kept()))
    status, _, _ = small.request('DELETE', f"/api/workouts/{kept()[0]['id']}", headers={'Cookie': f'session={token}'})
    check('deleting one makes room for another', status == 200 and save({'name': 'Room again', 'clientId': 'keep-6', 'exercises': []})[0] == 201)
    new_ones = [{'name': f'Imported {n}', 'createdAt': 1_700_000_000_000 + n, 'exercises': []} for n in range(2)]
    status, _, reply = post(small, '/api/import', {'format': 'workout-tracker-export', 'workouts': new_ones}, token)
    check('an import that would pass the limit is refused whole', status == 400 and 'at most 5' in reply.get('error', ''), f'{status} {reply}')
    check('and added none of its workouts', len(kept()) == 5, len(kept()))
    small.stop()

    big = t.start_server('workout-size.db')
    token = session_of(make(big, 'heavy')[1])
    bulky = {'name': 'Bulky', 'exercises': [], 'padding': 'x' * (300 * 1024)}
    status, _, reply = post(big, '/api/workouts', bulky, token)
    check('a workout over 256 KB is refused with 413', status == 413 and '256 KB' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = post(big, '/api/import', {'format': 'workout-tracker-export', 'workouts': [bulky]}, token)
    check('and so is an import holding one, naming which', status == 400 and 'Workout 1' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = post(big, '/api/workouts', {'name': 'Fine', 'notes': 'n' * 100_000, 'exercises': []}, token)
    check('a workout with the longest notes allowed is far under it', status == 201, f'{status} {reply}')

    # While one import is being read another is told to come back. The first sends its headers and then nothing, so the
    # server waits on it as it would on a slow upload.
    host, port = big.base_url.replace('http://', '').split(':')
    slow = socket.create_connection((host, int(port)), timeout=10)
    slow.sendall((f'POST /api/import HTTP/1.1\r\nHost: x\r\nCookie: session={token}\r\nContent-Type: application/json\r\n'
                  f'Content-Length: 1000\r\n\r\n').encode())
    time.sleep(0.5)
    status, headers, reply = post(big, '/api/import', {'format': 'workout-tracker-export', 'workouts': []}, token)
    check('a second import meanwhile is told to try again, with Retry-After', status == 503 and int(headers.get('retry-after', 0)) > 0, f'{status} {reply}')
    slow.close()
    deadline = time.time() + 15
    while time.time() < deadline:
        status = post(big, '/api/import', {'format': 'workout-tracker-export', 'workouts': []}, token)[0]
        if status == 200:
            break
        time.sleep(0.3)
    check('and once the first has gone, imports are taken again', status == 200, status)
    big.stop()

    # ------------------------------------------------------------------ A43 the address it listens on
    print('A43 HOST says which address the server listens on')
    local = t.start_server('local-only.db', {'HOST': '127.0.0.1'})
    check('with HOST=127.0.0.1 it answers on that address', local.api('GET', '/api/auth/me')[0].get('registrationOpen') is True)
    local.stop()
    refused = subprocess.run([sys.executable, os.path.join(REPO_ROOT, 'backend', 'server.py')], env={**os.environ, 'HOST': 'no.such.host.invalid',
                             'WORKOUT_DB': t.db_path('bad-host.db'), 'PORT': '0'}, capture_output=True, text=True, timeout=60)
    check('a HOST that is not an address of this machine stops it from starting, rather than listening somewhere else', refused.returncode != 0, refused.returncode)


def run_sessions(t, check):
    """The devices signed in to an account: listed, signed out one at a time or all but this one, and their reminders with them."""
    json_headers = {'Content-Type': 'application/json'}
    desktop = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    phone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
    laptop = 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0'
    server = t.start_server('devices.db', {'PUSH_ALLOWED_HOSTS': 'push.example.test'})

    def call(method, path, body=None, token=None):
        headers = {**json_headers, **({'Cookie': f'session={token}'} if token else {})}
        return server.request(method, path, json.dumps(body).encode() if body is not None else None, headers)

    def sign_in(login, agent, password='chalk-and-plates-42'):
        status, headers, _ = server.request('POST', '/api/auth/login', json.dumps({'login': login, 'password': password}).encode(),
                                            {**json_headers, 'User-Agent': agent})
        assert status == 200, status
        return headers['set-cookie'].split('session=')[1].split(';')[0]

    def register(name, agent):
        status, headers, _ = server.request('POST', '/api/auth/register', json.dumps({'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'}).encode(),
                                            {**json_headers, 'User-Agent': agent})
        assert status == 200, status
        return headers['set-cookie'].split('session=')[1].split(';')[0]

    def signed_in(token):
        return call('GET', '/api/auth/me', token=token)[2].get('user') is not None

    # ------------------------------------------------------------------ A44 devices signed in
    print('A44 the devices signed in to an account are listed, and signed out one at a time, or all but this one')
    here = register('walker', desktop)
    other = register('bystander', desktop)
    phone_token, laptop_token = sign_in('walker', phone), sign_in('walker@example.test', laptop)
    status, _, reply = call('GET', '/api/account/sessions', token=here)
    devices = reply['sessions'] if isinstance(reply, dict) else []
    check('the account lists its three devices', status == 200 and len(devices) == 3, f'{status} {reply}')
    check('each is named by its browser and system, as a person would say it',
          sorted(device['label'] for device in devices) == ['Chrome on Windows', 'Firefox on Linux', 'Safari on iPhone'], [device['label'] for device in devices])
    check('and says where from and when', all(device['address'] == '127.0.0.1' and abs(device['createdAt'] - time.time() * 1000) < 60_000
                                              and abs(device['lastUsed'] - time.time() * 1000) < 60_000 for device in devices), devices)
    check('the one asking is marked, and only that one', [device['label'] for device in devices if device['current']] == ['Chrome on Windows'], devices)
    check('the newest is first', [device['label'] for device in devices][0] == 'Firefox on Linux', devices)
    check('none of it holds anything that could sign in as the device', all(set(device) == {'id', 'label', 'address', 'createdAt', 'lastUsed', 'remembered', 'current'} for device in devices))
    check('another account lists only its own', [device['label'] for device in call('GET', '/api/account/sessions', token=other)[2]['sessions']] == ['Chrome on Windows'])
    ids = {device['label']: device['id'] for device in devices}

    status, _, reply = call('POST', '/api/account/sessions/revoke', {'id': ids['Chrome on Windows']}, here)
    check('signing out the device in use is refused, pointing to Sign out', status == 400 and 'Sign out' in reply.get('error', '') and signed_in(here), f'{status} {reply}')
    for label, body in (('a name', {'id': 'phone'}), ('no id', {}), ('a truth', {'id': True})):
        check(f'{label} instead of an id is a 400', call('POST', '/api/account/sessions/revoke', body, here)[0] == 400)
    other_id = call('GET', '/api/account/sessions', token=other)[2]['sessions'][0]['id']
    status, _, reply = call('POST', '/api/account/sessions/revoke', {'id': other_id}, here)
    check('a device of another account is not here to sign out, and is left signed in', status == 200 and reply == {'signedOut': 0} and signed_in(other), f'{status} {reply}')

    status, _, reply = call('POST', '/api/account/sessions/revoke', {'id': ids['Safari on iPhone']}, here)
    check('signing out the phone ends its session and no other', status == 200 and reply == {'signedOut': 1} and not signed_in(phone_token) and signed_in(laptop_token) and signed_in(here), f'{status} {reply}')
    check('asking again for it is not an error, and has nothing to do', call('POST', '/api/account/sessions/revoke', {'id': ids['Safari on iPhone']}, here)[2] == {'signedOut': 0})
    check('the list shows two', len(call('GET', '/api/account/sessions', token=here)[2]['sessions']) == 2)
    status, _, reply = call('POST', '/api/account/sessions/sign-out-others', {}, here)
    check('Sign out everywhere else ends the others, and says how many', status == 200 and reply == {'signedOut': 1} and not signed_in(laptop_token) and signed_in(here), f'{status} {reply}')
    check('and it is the only device left', [device['current'] for device in call('GET', '/api/account/sessions', token=here)[2]['sessions']] == [True])
    check('with nothing to sign out it says so', call('POST', '/api/account/sessions/sign-out-others', {}, here)[2] == {'signedOut': 0})

    db = sqlite3.connect(t.db_path('devices.db'))
    db.execute('UPDATE sessions SET last_used = 1000 WHERE token = ?', (hashlib.sha256(here.encode()).hexdigest(),))
    db.commit()
    call('GET', '/api/auth/me', token=here)
    used = db.execute('SELECT last_used FROM sessions WHERE token = ?', (hashlib.sha256(here.encode()).hexdigest(),)).fetchone()[0]
    db.close()
    check('using a device brings its last-used time up to date', abs(used - time.time()) < 60, used)
    recent = int(time.time()) - 30
    db = sqlite3.connect(t.db_path('devices.db'))
    db.execute('UPDATE sessions SET last_used = ? WHERE token = ?', (recent, hashlib.sha256(here.encode()).hexdigest()))
    db.commit()
    db.close()
    call('GET', '/api/auth/me', token=here)
    check('but not on every request, which would write each time', call('GET', '/api/account/sessions', token=here)[2]['sessions'][0]['lastUsed'] == recent * 1000)

    # ------------------------------------------------------------------ A44b reminders go with the session
    print('A44b reminders set up on a device stop when it is signed out')
    module = load_server()

    def subscribe(token, name):
        private = secrets.randbelow(module.P256_N - 1) + 1
        body = {'endpoint': f'https://push.example.test/{name}', 'keys': {'p256dh': module.b64url(module.encode_point(*module.ec_multiply(private))),
                                                                          'auth': module.b64url(secrets.token_bytes(16))}, 'timeZone': 'UTC', 'utcOffset': 0}
        return call('POST', '/api/push/subscribe', body, token)[0]

    def reminders():
        db = sqlite3.connect(t.db_path('devices.db'))
        rows = sorted(row[0].rsplit('/', 1)[1] for row in db.execute('SELECT endpoint FROM push_subscriptions'))
        db.close()
        return rows
    first, second, third = sign_in('walker', desktop), sign_in('walker', phone), sign_in('walker', laptop)
    check('three devices set up reminders', [subscribe(first, 'one'), subscribe(second, 'two'), subscribe(third, 'three')] == [200] * 3 and reminders() == ['one', 'three', 'two'], reminders())
    listed = {device['label']: device['id'] for device in call('GET', '/api/account/sessions', token=first)[2]['sessions'] if not device['current']}
    call('POST', '/api/account/sessions/revoke', {'id': listed['Safari on iPhone']}, first)
    check('signing one device out stops its reminders only', reminders() == ['one', 'three'], reminders())
    call('POST', '/api/account/sessions/sign-out-others', {}, first)
    check('signing out the others stops theirs, and keeps this device’s', reminders() == ['one'], reminders())
    second, third = sign_in('walker', phone), sign_in('walker', laptop)
    subscribe(second, 'two')
    subscribe(third, 'three')
    status, _, _ = call('POST', '/api/account/password', {'currentPassword': 'chalk-and-plates-42', 'newPassword': 'rowing-machine-17'}, first)
    check('changing the password signs the others out, and their reminders with them', status == 200 and reminders() == ['one'], f'{status} {reminders()}')
    call('POST', '/api/auth/logout', {}, first)
    check('signing out stops this device’s own', reminders() == [])
    # A subscription from before it was tied to a session has none recorded: it is left alone, and tied the next time its phone says hello.
    again = sign_in('walker', desktop, 'rowing-machine-17')
    subscribe(again, 'old')
    db = sqlite3.connect(t.db_path('devices.db'))
    db.execute("UPDATE push_subscriptions SET session_hash = ''")
    db.commit()
    db.close()
    call('POST', '/api/account/sessions/sign-out-others', {}, again)
    check('a reminder from before sessions were recorded is not guessed at', reminders() == ['old'], reminders())
    subscribe(again, 'old')
    check('and is tied to the session that says hello', sqlite3.connect(t.db_path('devices.db')).execute('SELECT session_hash FROM push_subscriptions').fetchone()[0]
          == hashlib.sha256(again.encode()).hexdigest())

    print('A44c what a browser is called')
    label = module.device_label
    for agent, expected in ((desktop, 'Chrome on Windows'), (phone, 'Safari on iPhone'), (laptop, 'Firefox on Linux'),
                            ('Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0', 'Edge on Windows'),
                            ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 CriOS/126.0 Mobile/15E148 Safari/604.1', 'Chrome on iPhone'),
                            ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36', 'Chrome on Android'),
                            ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15', 'Safari on Mac'),
                            ('curl/8.4.0', 'Browser'), ('', 'Browser'), (None, 'Browser')):
        check(f'{(agent or "no User-Agent")[:48]!r} is {expected}', label(agent) == expected, label(agent))
    check('whatever the header says, the name stays short and from a fixed set', len(label('x' * 100_000 + 'Firefox/ Windows')) < 40)
    server.stop()


def run_connections(t, check):
    """What the server says about itself, and how many connections it takes and for how long."""
    module = load_server()

    # ------------------------------------------------------------------ A45 what the server tells everyone
    print('A45 the server does not say which Python it runs')
    for method, path in (('GET', '/api/auth/me'), ('GET', '/login.html'), ('GET', '/no-such-file'), ('POST', '/api/auth/login')):
        _, headers, _ = t.server.request(method, path, b'{}' if method == 'POST' else None, {'Content-Type': 'application/json'})
        check(f'{method} {path} says what it is, and no version', headers.get('server') == 'workout-tracker', headers.get('server'))

    # ------------------------------------------------------------------ A46 open connections
    print('A46 only so many connections are open at once, and a request has only so long to arrive')

    def connect(server):
        return socket.create_connection(('127.0.0.1', server.port), timeout=10)

    def read_all(sock, wait=10):
        sock.settimeout(wait)
        data = b''
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return data
                data += chunk
        except OSError:
            return data

    def answers(server):
        sock = connect(server)
        sock.sendall(b'GET /login.html HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
        head = read_all(sock)
        sock.close()
        return head

    crowded = t.start_server('crowded.db', {'MAX_CONNECTIONS': '3', 'HEADER_TIMEOUT': '60'})
    held = [connect(crowded) for _ in range(3)]
    time.sleep(0.5)
    refused = answers(crowded)
    check('past the ceiling a connection is told 503, with Retry-After, and closed', refused.startswith(b'HTTP/1.1 503 ') and b'Retry-After: 5' in refused and refused.endswith(b'The server is busy. Try again.'), refused[:120])
    held.pop().close()
    deadline = time.time() + 5
    served = b''
    while time.time() < deadline and not served.startswith(b'HTTP/1.1 200 '):
        served = answers(crowded)
        time.sleep(0.2)
    check('and one that closes makes room for the next', served.startswith(b'HTTP/1.1 200 '), served[:60])
    for sock in held:
        sock.close()
    deadline = time.time() + 5
    while time.time() < deadline and not all(answers(crowded).startswith(b'HTTP/1.1 200 ') for _ in range(3)):
        time.sleep(0.2)
    check('once they all go the server answers as ever', all(answers(crowded).startswith(b'HTTP/1.1 200 ') for _ in range(3)))
    crowded.stop()

    hurried = t.start_server('hurried.db', {'HEADER_TIMEOUT': '2'})
    sock = connect(hurried)
    started = time.monotonic()
    data = read_all(sock)
    check('a connection that sends nothing is closed when its headers are due, not at the 30 seconds of silence', data == b'' and 1.5 < time.monotonic() - started < 6, f'{data!r} {time.monotonic() - started:.1f}s')
    sock.close()

    sock = connect(hurried)
    started = time.monotonic()
    closed_after = None
    try:
        sock.sendall(b'GET /login.html HTTP/1.1\r\nHost: x\r\n')
        # One byte every half second: never silent for long, but never done either.
        for byte in b'X-Slow: ' + b'a' * 40:
            time.sleep(0.5)
            sock.sendall(bytes([byte]))
            if time.monotonic() - started > 12:
                break
    except OSError:
        closed_after = time.monotonic() - started
    check('and so is one that dribbles them in, which the silence timeout never catches', closed_after is not None and closed_after < 8, closed_after)
    sock.close()

    sock = connect(hurried)
    sock.sendall(b'GET /login.html HTTP/1.1\r\nHost: x\r\n')
    time.sleep(1)
    sock.sendall(b'Connection: close\r\n\r\n')
    check('while a request whose headers arrive in two parts, in time, is answered', read_all(sock).startswith(b'HTTP/1.1 200 '))
    sock.close()

    sock = connect(hurried)
    # A sign-in, which reads its body before it says anything: a request answered without reading it would not show the wait.
    body = b'{"login":"nobody","password":"wrong-password"}'
    sock.sendall(b'POST /api/auth/login HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n' % len(body) + body[:8])
    time.sleep(3)
    sock.sendall(body[8:])
    check('and once the headers are in, the body is not held to the headers’ deadline', b'HTTP/1.1 401' in read_all(sock))
    sock.close()
    hurried.stop()

    check('a request with no body has a minute from its headers to its answer', module.request_allowance(None) == 60 and module.request_allowance('0') == 60)
    check('a body adds the time it needs at 20 KB a second', module.request_allowance('1000000') == 60 + 50)
    check('up to a fifteen minute most, which a 32 MB import reaches', module.request_allowance(str(32 * 1024 * 1024)) == 900)
    check('and a length that is not a number counts as none', module.request_allowance('lots') == 60 and module.request_allowance('-5') == 60)


def run_structure(t, check, request):
    token = t.token
    json_headers = {'Content-Type': 'application/json'}
    tables = ['active_sessions', 'password_resets', 'push_subscriptions', 'server_keys', 'sessions', 'user_state', 'users', 'workout_versions', 'workouts']

    # ------------------------------------------------------------------ A12 schema at startup
    print('A12 the schema is created and versioned at startup, in WAL mode')
    t.start_server('fresh.db')  # the harness only asks /api/auth/me, which never opens the database
    schema = schema_of(t.db_path('fresh.db'))
    check('a new database has every table before any request touches it', schema['tables'] == tables, schema['tables'])
    check('it is at the latest schema version', schema['version'] == LATEST_SCHEMA, schema['version'])
    check('with the client_id column and its unique index',
          'client_id' in schema['columns'] and 'workouts_user_client' in schema['indexes'], schema)
    check('with a column for the training program', 'program_json' in schema['state_columns'], schema['state_columns'])
    check('and one for notes kept with each exercise', 'notes_json' in schema['state_columns'], schema['state_columns'])
    check('and one for goals', 'goals_json' in schema['state_columns'], schema['state_columns'])
    check('and one for bodyweight', 'bodyweight_json' in schema['state_columns'], schema['state_columns'])
    check('and one for the muscle and equipment of each exercise', 'library_json' in schema['state_columns'], schema['state_columns'])
    parts = load_server().STATE_PARTS
    db = sqlite3.connect(t.db_path('fresh.db'))
    columns = {row[1]: row for row in db.execute('PRAGMA table_info(user_state)')}
    db.close()
    problems = [name for name, part in parts.items() if part.column not in columns or not columns[part.column][3] or columns[part.column][4] != f"'{part.empty}'"]
    check('every part of the account’s state (STATE_PARTS) has its column, which cannot be null and starts as the part’s empty value', not problems, problems)
    check('and the table has no column that is not one of them', set(columns) - {'user_id', 'updated_at'} == {part.column for part in parts.values()}, sorted(columns))

    # A part added to the table is all that takes: a copy of the server with one more entry, and its column, loads, stores,
    # checks, merges and imports it, with nothing else changed.
    extended = load_server()
    extended.STATE_PARTS['readings'] = extended.StatePart('readings_json', '{}', {'depth': 1}, extended.keyed_collection('readings', 3, 'readings', lambda key, entry: None),
                                                          extended.add_missing('readings', 3), 'readings')
    shutil.copy(t.db_path('fresh.db'), t.db_path('extended.db'))
    db = sqlite3.connect(t.db_path('extended.db'))
    db.row_factory = sqlite3.Row
    db.execute("ALTER TABLE user_state ADD COLUMN readings_json TEXT NOT NULL DEFAULT '{}'")
    loaded = extended.load_state(db, 1)
    extended.store_state(db, 1, {**loaded, 'readings': {'a': 1}})
    stored = extended.load_state(db, 1)
    db.close()
    refused = None
    try:
        extended.validate_state({'readings': {'a': 1, 'b': 2, 'c': 3, 'd': 4}})
    except extended.BadRequest as error:
        refused = str(error)
    check('a part added to the table is loaded, empty, and stored', loaded['readings'] == {} and stored['readings'] == {'a': 1} and list(stored)[-1] == 'readings', [loaded, stored])
    check('checked, in its own words', refused == 'readings must be an object of up to 3 readings.', refused)
    check('merged with its own spec', extended.merge_part('readings', [{}], {'a': 1}, {'b': 2}) == {'b': 2, 'a': 1})
    imported = extended.STATE_PARTS['readings'].take({'a': 1}, {'a': 9, 'b': 2})
    check('and imported, adding only what the account has none of', imported == ({'a': 1, 'b': 2}, 1), imported)
    try:
        extended.STATE_PARTS['readings'].take({'a': 1, 'b': 2}, {'c': 3, 'd': 4})
        over = None
    except extended.BadRequest as error:
        over = str(error)
    check('or refusing what would take it past its limit', over == 'Importing these readings would take the account past 3.', over)
    check('with an email for each account, and its unique index',
          'email' in schema['user_columns'] and 'users_email' in schema['user_indexes'], schema)
    check('and whether each session was remembered', 'remember' in schema['session_columns'], schema['session_columns'])
    check('in write-ahead-log mode', schema['journal'] == 'wal', schema['journal'])
    legacy = schema_of(t.db_path('legacy.db'))
    check('the database from before client_id (A3) is at the latest version too', legacy['version'] == LATEST_SCHEMA, legacy['version'])
    check('and has the training program, exercise notes, goals, bodyweight and exercise library columns',
          {'program_json', 'notes_json', 'goals_json', 'bodyweight_json', 'library_json'} <= set(legacy['state_columns']), legacy['state_columns'])
    check('and the email column, and the table of reset codes',
          'email' in legacy['user_columns'] and 'password_resets' in legacy['tables'], legacy)
    check('and the remembered column on its sessions', 'remember' in legacy['session_columns'], legacy['session_columns'])
    check('and the tables of push subscriptions and the server’s own keys', {'push_subscriptions', 'server_keys'} <= set(legacy['tables']), legacy['tables'])
    check('and the index workouts are read in, and the table of their versions', 'workouts_user_created' in legacy['indexes'] and 'workout_versions' in legacy['tables'], legacy)

    # A database written by the release before migrations were numbered: client_id already there, version 0.
    path = t.db_path('unversioned.db')
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA + '''
        ALTER TABLE workouts ADD COLUMN client_id TEXT;
        CREATE UNIQUE INDEX workouts_user_client ON workouts(user_id, client_id);
        INSERT INTO users VALUES (1, 'kept', 'x$y', 0);
        INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (1, 'Kept', '', 0, '{"exercises": []}', 'k1');
    ''')
    db.close()
    t.start_server('unversioned.db')
    schema = schema_of(path)
    db = sqlite3.connect(path)
    kept = db.execute("SELECT name, client_id FROM workouts").fetchall()
    db.close()
    check('an unversioned database that already has client_id upgrades cleanly',
          schema['version'] == LATEST_SCHEMA and schema['columns'].count('client_id') == 1 and kept == [('Kept', 'k1')], f'{schema} {kept}')

    path = t.db_path('newer.db')
    db = sqlite3.connect(path)
    db.execute('PRAGMA user_version = 99')
    db.close()
    try:
        t.start_server('newer.db')
        refused = False
    except RuntimeError:
        refused = True
    after = schema_of(path)
    check('a database from a newer release is refused rather than touched',
          refused and after['version'] == 99 and after['tables'] == [] and after['journal'] == 'delete', after)

    # ------------------------------------------------------------------ A13 concurrency
    print('A13 requests keep working while the database is busy')
    holder = sqlite3.connect(t.db_path('test.db'), isolation_level=None)
    holder.execute('BEGIN EXCLUSIVE')
    started = time.monotonic()
    status, _, reply = request('GET', '/api/workouts', token=token)
    elapsed = time.monotonic() - started
    holder.execute('ROLLBACK')
    check('reads are answered at once while another connection holds the write lock',
          status == 200 and elapsed < 2, f'{status} after {elapsed:.1f}s')

    def hold_write_lock(seconds):
        blocker = sqlite3.connect(t.db_path('test.db'), isolation_level=None)
        blocker.execute('BEGIN IMMEDIATE')
        time.sleep(seconds)
        blocker.execute('COMMIT')
        blocker.close()

    blocker = threading.Thread(target=hold_write_lock, args=(1.5,))
    blocker.start()
    time.sleep(0.2)
    started = time.monotonic()
    body = json.dumps({'name': 'Waited', 'exercises': [], 'clientId': 'waited-1'}).encode()
    status, _, _ = request('POST', '/api/workouts', body, json_headers, token=token)
    elapsed = time.monotonic() - started
    blocker.join()
    check('a write waits for the lock instead of failing', status == 201 and elapsed >= 1, f'{status} after {elapsed:.1f}s')

    # ------------------------------------------------------------------ A14 workout validation
    print('A14 workouts are checked before they are stored')

    def good(**changes):
        workout = {'name': 'Valid', 'notes': '', 'createdAt': int(time.time() * 1000),
                   'exercises': [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}]}]}
        workout.update(changes)
        return workout

    def exercise(**changes):
        return [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}], **changes}]

    # A cardio session, as the Cardio page saves one.
    def cardio(**changes):
        session = {'kind': 'cardio', 'name': 'Run', 'notes': '', 'createdAt': int(time.time() * 1000), 'exercises': [], 'duration': 1680,
                   'cardio': {'activity': 'run', 'distance': 3.1, 'distanceUnit': 'mi', 'calories': 310, 'heartRate': 152}}
        session.update(changes)
        return session

    before = len(t.workouts())
    refused = [
        ('a name that is a number', good(name=5)),
        ('notes that are a list', good(notes=['x'])),
        ('a createdAt that is text', good(createdAt='yesterday')),
        ('a createdAt that is true', good(createdAt=True)),
        ('a createdAt far in the future', good(createdAt=10 ** 15)),
        ('no exercises at all', {k: v for k, v in good().items() if k != 'exercises'}),
        ('exercises that are text', good(exercises='squat')),
        ('an exercise that is not an object', good(exercises=['squat'])),
        ('an exercise name that is a number', good(exercises=exercise(name=3))),
        ('a weight that is a word', good(exercises=exercise(weight='heavy'))),
        ('a negative weight', good(exercises=exercise(weight=-5))),
        ('reps that are an object', good(exercises=exercise(reps={}))),
        ('sets that are text', good(exercises=exercise(sets='3x5'))),
        ('a set weight that is a word', good(exercises=exercise(sets=[{'weight': 'abc', 'reps': 5}]))),
        ('a clientId that is a number', good(clientId=7)),
        ('a program that is text', good(program='Wendler 5/3/1')),
        ('a program label that is a number', good(program={'name': 'Wendler 5/3/1', 'label': 2})),
        ('a 2000-character name', good(name='x' * 2000)),
        ('a superset group that is a number', good(exercises=exercise(group=1))),
        ('an effort that is a word', good(exercises=exercise(sets=[{'weight': 100, 'reps': 5, 'rir': 'easy'}]))),
        ('an effort below zero', good(exercises=exercise(sets=[{'weight': 100, 'reps': 5, 'rir': -1}]))),
        ('an effort above ten', good(exercises=exercise(sets=[{'weight': 100, 'reps': 5, 'rir': 11}]))),
        ('a kind that is neither strength nor cardio', cardio(kind='yoga')),
        ('a cardio session with no cardio', {k: v for k, v in cardio().items() if k != 'cardio'}),
        ('a cardio session that names no activity', cardio(cardio={'activity': ' '})),
        ('a cardio session with no time', {k: v for k, v in cardio().items() if k != 'duration'}),
        ('a cardio session of no time', cardio(duration=0)),
        ('a negative distance', cardio(cardio={'activity': 'run', 'distance': -1, 'distanceUnit': 'mi'})),
        ('a distance as text', cardio(cardio={'activity': 'run', 'distance': '3.1', 'distanceUnit': 'mi'})),
        ('a distance in yards', cardio(cardio={'activity': 'run', 'distance': 3, 'distanceUnit': 'yd'})),
        ('a heart rate of 500', cardio(cardio={'activity': 'run', 'heartRate': 500})),
        ('calories that are a word', cardio(cardio={'activity': 'run', 'calories': 'lots'})),
        ('a treadmill incline of 50%', cardio(cardio={'activity': 'run', 'incline': 50})),
        ('a damper of 0', cardio(cardio={'activity': 'rower', 'damper': 0})),
        ('a resistance level that is text', cardio(cardio={'activity': 'bike', 'resistance': 'hard'})),
    ]
    for label, body in refused:
        status, _, reply = request('POST', '/api/workouts', json.dumps(body).encode(), json_headers, token=token)
        check(f'refused: {label}', status == 400 and isinstance(reply, dict) and reply.get('error'), f'{status} {reply}')
    check('none of them was stored', len(t.workouts()) == before, f'{before} -> {len(t.workouts())}')

    accepted = [
        ('what a finished workout sends', good()),
        ('what the workout form sends (text, empty weight, no sets)',
         good(exercises=[{'name': 'Curl', 'weight': '', 'reps': '10'}, {'name': 'Row', 'weight': '72.5', 'reps': '8'}])),
        ('a skipped exercise (empty set list)', good(exercises=exercise(sets=[]))),
        ('no exercises (an empty list)', good(exercises=[])),
        ('a missing name, notes and createdAt', {'exercises': []}),
        ('a workout from a training program',
         good(program={'name': 'Wendler 5/3/1', 'cycle': 1, 'week': 2, 'label': 'Cycle 1, week 2 · 3s week'})),
        ('a superset, and each set with the reps it had left',
         good(exercises=exercise(group='s1', sets=[{'weight': 100, 'reps': 5, 'rir': 2}, {'weight': 100, 'reps': 5, 'rir': 0}]))),
        ('a cardio session', cardio()),
        ('a cardio session with only its time', cardio(name='Elliptical', cardio={'activity': 'elliptical'})),
        ('a rowing session in metres, at a damper and stroke rate',
         cardio(name='Rowing machine', cardio={'activity': 'rower', 'distance': 5000, 'distanceUnit': 'm', 'damper': 6, 'strokeRate': 26})),
        ('a treadmill walk downhill',
         cardio(name='Walk', cardio={'activity': 'walk', 'incline': -2.5})),
        ('a bike at a resistance and cadence', cardio(name='Exercise bike', cardio={'activity': 'bike', 'resistance': 8, 'cadence': 85})),
    ]
    for label, body in accepted:
        status, _, reply = request('POST', '/api/workouts', json.dumps(body).encode(), json_headers, token=token)
        check(f'accepted: {label}', status == 201, f'{status} {reply}')

    # ------------------------------------------------------------------ A15 editing and deleting
    print('A15 editing a workout that is missing, or not yours, is a 404')
    mine = t.W1
    _, cookie = t.api('POST', '/api/auth/register', {'username': 'neighbour', 'email': 'neighbour@example.test', 'password': 'chalk-and-plates-42'})
    neighbour = cookie.split('session=')[1].split(';')[0]
    theirs, _ = t.api('POST', '/api/workouts', good(name='Theirs'), neighbour)
    for label, path in [('an id that does not exist', '/api/workouts/999999'),
                        ('an id that is not a number', '/api/workouts/abc'),
                        ("another account's workout", f"/api/workouts/{theirs['id']}")]:
        status, _, reply = request('PUT', path, json.dumps(good(name='Hijack')).encode(), json_headers, token=token)
        check(f'PUT {label} -> 404', status == 404, f'{status} {reply}')
    their_name = next(w['name'] for w in t.api('GET', '/api/workouts', token=neighbour)[0]['workouts'])
    check("and the other account's workout is unchanged", their_name == 'Theirs', their_name)
    status, _, _ = request('PUT', f'/api/workouts/{mine}', json.dumps(good(name='Renamed')).encode(), json_headers, token=token)
    check('PUT your own workout -> 200', status == 200 and t.workout(mine)['name'] == 'Renamed', status)
    status, _, _ = request('PUT', f'/api/workouts/{mine}', json.dumps(good(exercises='bad')).encode(), json_headers, token=token)
    check('an invalid edit is refused and changes nothing',
          status == 400 and isinstance(t.workout(mine)['exercises'], list), status)
    check('DELETE with an id that is not a number -> 404', request('DELETE', '/api/workouts/abc', token=token)[0] == 404)

    # ------------------------------------------------------------------ A16 state and active session
    print('A16 settings, templates and the active session are checked too')
    template = {'id': 'custom-1', 'name': 'Ok', 'exercises': [{'name': 'Row', 'reps': '8'}]}
    for label, body, expected in [
        ('settings that are a list', {'settings': []}, 400),
        ('templates that are an object', {'templates': {}}, 400),
        ('a template without exercises', {'templates': [{'id': 'x', 'name': 'No list'}]}, 400),
        ('a template name that is a number', {'templates': [{**template, 'name': 1}]}, 400),
        ('valid settings and templates', {'settings': {'restDuration': 60}, 'templates': [template]}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('only the valid state was stored', state['templates'] == [template] and state['settings'].get('restDuration') == 60, state)
    check('no training program until one is set up', state.get('program', 'missing') is None, state)
    program = {'definition': 'wendler-531', 'startedAt': 1, 'cycle': 1, 'trainingMaxes': {'press': 100, 'deadlift': 300, 'bench': 200, 'squat': 250},
               'options': {'assistance': 'bbb'}, 'done': {'0-0': {'at': 2, 'amrap': {'weight': 85, 'reps': 9, 'target': 5}}}}
    for label, body, expected in [
        ('a program that is a list', {'program': []}, 400),
        ('a program without training maxes', {'program': {'definition': 'wendler-531'}}, 400),
        ('a program with no definition', {'program': {k: v for k, v in program.items() if k != 'definition'}}, 400),
        ('a training max that is a word', {'program': {**program, 'trainingMaxes': {'bench': 'heavy'}}}, 400),
        ('a negative training max', {'program': {**program, 'trainingMaxes': {'bench': -5}}}, 400),
        ('program options that are a list', {'program': {**program, 'options': []}}, 400),
        ('missed sessions that are a list', {'program': {**program, 'stalls': []}}, 400),
        ('a valid program', {'program': program}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('the valid program is stored as sent', state.get('program') == program, state.get('program'))
    t.api('PUT', '/api/state', {'settings': {'restDuration': 75}}, token)
    state = t.api('GET', '/api/state', token=token)[0]
    check('saving only settings leaves the program alone', state.get('program') == program and state['templates'] == [template], state)
    built = {'definition': 'custom', 'startedAt': 1, 'cycle': 1, 'trainingMaxes': {}, 'name': 'Upper/Lower',
             'days': [{'name': 'Upper A', 'template': 'custom-1'}, {'name': 'Lower', 'template': 'built-in-2'}]}
    for label, body, expected in [
        ('a built program with a name that is a number', {'program': {**built, 'name': 5}}, 400),
        ('a built program whose days are not a list', {'program': {**built, 'days': {'Upper': 'custom-1'}}}, 400),
        ('a built program of 8 days', {'program': {**built, 'days': [{'name': f'Day {n}', 'template': 'custom-1'} for n in range(8)]}}, 400),
        ('a built program with a day of no template', {'program': {**built, 'days': [{'name': 'Upper A', 'template': ''}]}}, 400),
        ('a valid built program', {'program': built}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    check('the built program is stored as sent', t.api('GET', '/api/state', token=token)[0].get('program') == built)
    status, _, _ = request('PUT', '/api/state', json.dumps({'program': None}).encode(), json_headers, token=token)
    state = t.api('GET', '/api/state', token=token)[0]
    for label, body, expected in [
        ('notes that are a list', {'exerciseNotes': []}, 400),
        ('a note that is a number', {'exerciseNotes': {'squat': 5}}, 400),
        ('a note over 2000 characters', {'exerciseNotes': {'squat': 'x' * 2001}}, 400),
        ('valid exercise notes', {'exerciseNotes': {'squat': 'Safeties on 7', 'bench press': 'Grip on the rings'}}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('the notes are stored, and nothing else changed', state.get('exerciseNotes') == {'squat': 'Safeties on 7', 'bench press': 'Grip on the rings'}
          and state['templates'] == [template] and state['settings'].get('restDuration') == 75, state)
    good_goal = {'name': 'Bench Press', 'target': 225, 'unit': 'lbs', 'by': '2026-12-01'}
    kilo_goal = {'name': 'Squat', 'target': 100.5, 'unit': 'kg', 'by': ''}
    for label, body, expected in [
        ('goals that are a list', {'goals': []}, 400),
        ('a goal that is a number', {'goals': {'squat': 5}}, 400),
        ('a goal with no name', {'goals': {'squat': {**good_goal, 'name': ''}}}, 400),
        ('a goal with a target of zero', {'goals': {'squat': {**good_goal, 'target': 0}}}, 400),
        ('a goal with a target of text', {'goals': {'squat': {**good_goal, 'target': '225'}}}, 400),
        ('a goal in stones', {'goals': {'squat': {**good_goal, 'unit': 'st'}}}, 400),
        ('a goal with a day that is not a date', {'goals': {'squat': {**good_goal, 'by': 'soon'}}}, 400),
        ('valid goals, one with no day', {'goals': {'bench press': good_goal, 'squat': kilo_goal}}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('the goals are stored, and nothing else changed', state.get('goals') == {'bench press': good_goal, 'squat': kilo_goal}
          and state['exerciseNotes'] == {'squat': 'Safeties on 7', 'bench press': 'Grip on the rings'} and state['templates'] == [template], state)
    status, _, _ = request('PUT', '/api/state', json.dumps({'goals': {}}).encode(), json_headers, token=token)
    check('an empty set of goals clears them', status == 200 and t.api('GET', '/api/state', token=token)[0]['goals'] == {})
    weighed = {'2026-09-28': {'weight': 181.4, 'unit': 'lbs'}, '2026-09-29': {'weight': 82.2, 'unit': 'kg'}}
    for label, body, expected in [
        ('bodyweight that is a list', {'bodyweight': []}, 400),
        ('a bodyweight on a day that is not a date', {'bodyweight': {'yesterday': {'weight': 180, 'unit': 'lbs'}}}, 400),
        ('a bodyweight on a day that does not exist', {'bodyweight': {'2026-02-30': {'weight': 180, 'unit': 'lbs'}}}, 400),
        ('a bodyweight of zero', {'bodyweight': {'2026-09-29': {'weight': 0, 'unit': 'lbs'}}}, 400),
        ('a bodyweight as text', {'bodyweight': {'2026-09-29': {'weight': '180', 'unit': 'lbs'}}}, 400),
        ('a bodyweight of 2001', {'bodyweight': {'2026-09-29': {'weight': 2001, 'unit': 'lbs'}}}, 400),
        ('a bodyweight in stones', {'bodyweight': {'2026-09-29': {'weight': 13, 'unit': 'st'}}}, 400),
        ('valid bodyweights, in either unit', {'bodyweight': weighed}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('the bodyweights are stored, and nothing else changed', state.get('bodyweight') == weighed and state['goals'] == {}
          and state['templates'] == [template], state)
    library = {'landmine press': {'name': 'Landmine Press', 'muscle': 'shoulders', 'equipment': 'other'},
               'squat': {'name': 'Squat', 'muscle': '', 'equipment': 'machine'}}
    for label, body, expected in [
        ('an exercise library that is a list', {'exerciseLibrary': []}, 400),
        ('an exercise that is text', {'exerciseLibrary': {'squat': 'quads'}}, 400),
        ('an exercise with no name', {'exerciseLibrary': {'squat': {'name': ' ', 'muscle': 'quads'}}}, 400),
        ('an exercise for a muscle the app does not offer', {'exerciseLibrary': {'squat': {'name': 'Squat', 'muscle': 'legs'}}}, 400),
        ('an exercise done with equipment the app does not offer', {'exerciseLibrary': {'squat': {'name': 'Squat', 'equipment': 'sandbag'}}}, 400),
        ('valid exercises, one leaving its muscle to the guess', {'exerciseLibrary': library}, 200),
    ]:
        status, _, reply = request('PUT', '/api/state', json.dumps(body).encode(), json_headers, token=token)
        check(f'PUT /api/state with {label} -> {expected}', status == expected, f'{status} {reply}')
    state = t.api('GET', '/api/state', token=token)[0]
    check('the exercises are stored, and nothing else changed', state.get('exerciseLibrary') == library and state['bodyweight'] == weighed
          and state['templates'] == [template], state)
    check('a null program ends it', status == 200 and state.get('program', 'missing') is None and state['settings'].get('restDuration') == 75, f'{status} {state}')
    for label, session, expected in [('text', 'running', 400), ('a list', [], 400), ('null', None, 200),
                                     ('an object', {'name': 'Push', 'exercises': [], 'currentIndex': 0}, 200)]:
        status, _, reply = request('POST', '/api/active-session', json.dumps({'session': session}).encode(), json_headers, token=token)
        check(f'an active session that is {label} -> {expected}', status == expected, f'{status} {reply}')


def run_accounts(t, check, request):
    main, mail = t.server, t.mail
    db_path = t.db_path('test.db')

    def post(path, body, token=None, server=main):
        """(status, headers, reply) for a JSON body; a dropped connection is a failed check, as with `request`."""
        if server is not main:
            return server.request('POST', path, json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=token)
        return request('POST', path, json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=token)

    def session_of(headers):
        cookie = headers.get('set-cookie', '')
        return cookie.split('session=')[1].split(';')[0] if 'session=' in cookie else None

    def me(token=None):
        return main.api('GET', '/api/auth/me', token=token)[0]

    def sign_in(login, password):
        return post('/api/auth/login', {'login': login, 'password': password})[0]

    def code_for(address, count):
        return mail.code(mail.wait(address, count))

    def other_code(code, n=1):
        return f'{(int(code) + n) % 10 ** 6:06d}'

    def reset(address, code, password):
        return post('/api/auth/reset-password', {'email': address, 'code': code, 'password': password})

    # ------------------------------------------------------------------ A17 emails
    print('A17 accounts have an email, and sign in with it or with the username')
    for label, body in [
        ('no email', {'username': 'nomail', 'password': 'chalk-and-plates-42'}),
        ('an email with no @', {'username': 'bad1', 'email': 'bad.example.test', 'password': 'chalk-and-plates-42'}),
        ('an email with two @', {'username': 'bad2', 'email': 'a@b@example.test', 'password': 'chalk-and-plates-42'}),
        ('an email with a space in it', {'username': 'bad3', 'email': 'a b@example.test', 'password': 'chalk-and-plates-42'}),
        ('an email with no dot after the @', {'username': 'bad4', 'email': 'a@localhost', 'password': 'chalk-and-plates-42'}),
        ('an email that is a number', {'username': 'bad5', 'email': 5, 'password': 'chalk-and-plates-42'}),
        ('a username with an @ in it', {'username': 'me@home', 'email': 'me@example.test', 'password': 'chalk-and-plates-42'}),
    ]:
        status, _, reply = post('/api/auth/register', body)
        check(f'registering with {label} -> 400', status == 400 and isinstance(reply, dict) and reply.get('error'), f'{status} {reply}')
    status, headers, reply = post('/api/auth/register', {'username': 'mailer', 'email': ' Mailer@Example.TEST ', 'password': 'chalk-and-plates-42'})
    check('an account is created with its email, trimmed and in lowercase',
          status == 200 and reply['user']['email'] == 'mailer@example.test', f'{status} {reply}')
    mailer = session_of(headers)
    check('/api/auth/me includes the email', me(mailer)['user'] == reply['user'], me(mailer))
    status, _, reply = post('/api/auth/register', {'username': 'copycat', 'email': 'MAILER@example.test', 'password': 'chalk-and-plates-42'})
    check('the same email in another case is refused -> 409', status == 409 and 'email' in reply.get('error', ''), f'{status} {reply}')
    for label, typed in [('the email', 'mailer@example.test'), ('the email in capitals', 'MAILER@EXAMPLE.TEST'), ('the username', 'mailer')]:
        status, _, reply = post('/api/auth/login', {'login': typed, 'password': 'chalk-and-plates-42'})
        check(f'signs in with {label}', status == 200 and reply['user']['username'] == 'mailer', f'{status} {reply}')
    status, _, _ = login(main, 'mailer@example.test', 'chalk-and-plates-42')
    check('a page from before emails, sending it as username, signs in too', status == 200, status)
    check('the email with a wrong password -> 401', sign_in('mailer@example.test', 'wrong-password') == 401)
    # Two requests can both pass the "already taken?" look-ups before either writes; the unique indexes then refuse the second,
    # which must be told as a 409 like the look-ups' own refusal, not as a server error.
    outcomes = []

    def register_same(n, username, email):
        outcomes.append(post('/api/auth/register', {'username': username, 'email': email, 'password': 'chalk-and-plates-42'})[0])

    for label, names in [('username', lambda n: ('dupe', f'dupe{n}@example.test')), ('email', lambda n: (f'dupe-b{n}', 'dupe-b@example.test'))]:
        outcomes.clear()
        racers = [threading.Thread(target=register_same, args=(n, *names(n))) for n in range(6)]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join()
        check(f'six accounts made at once with the same {label}: one is made, the rest are refused -> 409',
              sorted(outcomes) == [200] + [409] * 5, outcomes)
    post('/api/auth/register', {'username': 'limited', 'email': 'limited@example.test', 'password': 'right-password'})
    for n in range(5):
        sign_in('limited@example.test', f'wrong-guess-{n}')
    check('failures by email and by username share one limit', sign_in('limited', 'right-password') == 429)
    status, headers, reply = post('/api/auth/login', {'login': 'veteran', 'password': 'old-password'})
    veteran = session_of(headers)
    check('an account from before emails (A7) signs in with its username, and has no email',
          status == 200 and reply['user']['email'] is None, f'{status} {reply}')

    # ------------------------------------------------------------------ A18 changing the email
    print('A18 an email is added or changed with the password')
    for label, body, expected in [
        ('a wrong password', {'email': 'veteran@example.test', 'password': 'not-the-password'}, 403),
        ('an invalid email', {'email': 'veteran', 'password': 'old-password'}, 400),
        ("another account's email", {'email': 'Mailer@example.test', 'password': 'old-password'}, 409),
    ]:
        status, _, reply = post('/api/account/email', body, veteran)
        check(f'{label} -> {expected}', status == expected and reply.get('error'), f'{status} {reply}')
    check('none of them changed the email, or ended the session', me(veteran)['user']['email'] is None, me(veteran))
    check('signed out -> 401', post('/api/account/email', {'email': 'veteran@example.test', 'password': 'old-password'})[0] == 401)
    status, _, reply = post('/api/account/email', {'email': 'Veteran@Example.test', 'password': 'old-password'}, veteran)
    check('the right password saves it', status == 200 and reply['user']['email'] == 'veteran@example.test'
          and me(veteran)['user']['email'] == 'veteran@example.test', f'{status} {reply}')
    check('and the account then signs in with it', sign_in('veteran@example.test', 'old-password') == 200)
    guesses = [post('/api/account/email', {'email': 'v2@example.test', 'password': f'guess-{n}'}, veteran)[0] for n in range(5)]
    status = post('/api/account/email', {'email': 'v2@example.test', 'password': 'old-password'}, veteran)[0]
    check('guessing the password here is limited like signing in', guesses == [403] * 5 and status == 429, f'{guesses} {status}')

    # ------------------------------------------------------------------ A19 password reset
    print('A19 a forgotten password is reset with a code sent by email')
    check('the server says reset by email is available', me().get('passwordReset') is True, me())
    plain = t.start_server('nomail.db')
    check('a server without SMTP_HOST says it is not', plain.api('GET', '/api/auth/me')[0].get('passwordReset') is False)
    status, _, reply = post('/api/auth/forgot-password', {'email': 'tester@example.test'}, server=plain)
    check('and refuses to send a code -> 404', status == 404 and 'not set up' in reply.get('error', ''), f'{status} {reply}')

    status, _, nobody_reply = post('/api/auth/forgot-password', {'email': 'nobody@example.test'})
    check('an address with no account -> 200', status == 200 and nobody_reply == {'ok': True}, f'{status} {nobody_reply}')
    status, _, reply = post('/api/auth/forgot-password', {'email': 'MAILER@example.test'})
    check("an account's address gets the very same reply", status == 200 and reply == nobody_reply, f'{status} {reply}')
    check('an address that is not one -> 400', post('/api/auth/forgot-password', {'email': 'mailer'})[0] == 400)
    message = mail.wait('mailer@example.test', 1)
    code = mail.code(message)
    check('an email arrives with a 6-digit code', code is not None, message.get_content() if message else 'no email')
    check('from SMTP_FROM, naming the account', message is not None and 'tracker@example.test' in message['From']
          and '"mailer"' in message.get_content(), str(message and message['From']))
    check('and nothing was sent for the address with no account', not mail.to('nobody@example.test'))

    status, _, wrong_reply = reset('mailer@example.test', other_code(code), 'new-password-1')
    check('a wrong code -> 400', status == 400 and wrong_reply.get('error'), f'{status} {wrong_reply}')
    status, _, reply = reset('nobody@example.test', code, 'new-password-1')
    check('in the same words as an address with no account', status == 400 and reply == wrong_reply, f'{status} {reply}')
    status, _, reply = reset('mailer@example.test', code[:5], 'new-password-1')
    check('a code that is not 6 digits -> 400', status == 400 and '6-digit' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = reset('mailer@example.test', code, 'short')
    check('a new password under 8 characters -> 400', status == 400 and '8+' in reply.get('error', ''), f'{status} {reply}')
    status, headers, reply = reset('mailer@example.test', f'{code[:3]} {code[3:]}', 'new-password-1')
    check('the right code, even typed with a space, sets the password and signs in',
          status == 200 and reply['user']['username'] == 'mailer' and session_of(headers), f'{status} {reply}')
    fresh = session_of(headers)
    check('the new session works', (me(fresh)['user'] or {}).get('username') == 'mailer', me(fresh))
    check('every older session is signed out', me(mailer)['user'] is None)
    check('the old password no longer signs in', sign_in('mailer', 'chalk-and-plates-42') == 401)
    check('the new one does', sign_in('mailer@example.test', 'new-password-1') == 200)
    check('the code works only once', reset('mailer@example.test', code, 'new-password-2')[0] == 400)

    post('/api/auth/forgot-password', {'email': 'mailer@example.test'})
    code = code_for('mailer@example.test', 2)
    guesses = [reset('mailer@example.test', other_code(code, n + 1), 'new-password-2')[0] for n in range(5)]
    status = reset('mailer@example.test', code, 'new-password-2')[0]
    check('after five wrong codes the right one no longer works', guesses == [400] * 5 and status == 400, f'{guesses} {status}')
    post('/api/auth/forgot-password', {'email': 'mailer@example.test'})
    code = code_for('mailer@example.test', 3)
    status, headers, _ = reset('mailer@example.test', code, 'new-password-2')
    check('but a new code does', status == 200, status)
    mailer = session_of(headers)

    post('/api/auth/forgot-password', {'email': 'mailer@example.test'})
    code = code_for('mailer@example.test', 4)
    db = sqlite3.connect(db_path)
    db.execute("UPDATE password_resets SET expires_at = ? WHERE user_id = (SELECT id FROM users WHERE username = 'mailer')", (int(time.time()) - 1,))
    db.commit()
    db.close()
    check('an expired code is refused', reset('mailer@example.test', code, 'new-password-3')[0] == 400)

    post('/api/auth/forgot-password', {'email': 'mailer@example.test'})
    code = code_for('mailer@example.test', 5)
    status, _, reply = post('/api/account/email', {'email': 'mailer2@example.test', 'password': 'new-password-2'}, mailer)
    check('changing the email cancels a code sent to the old one',
          status == 200 and reset('mailer@example.test', code, 'new-password-3')[0] == 400
          and reset('mailer2@example.test', code, 'new-password-3')[0] == 400, f'{status} {reply}')

    statuses = [post('/api/auth/forgot-password', {'email': 'ghost@example.test'})[0] for _ in range(5)]
    status, headers, reply = post('/api/auth/forgot-password', {'email': 'ghost@example.test'})
    check('a sixth code for one address within the hour is refused, with Retry-After',
          statuses == [200] * 5 and status == 429 and int(headers.get('retry-after', 0)) > 3000, f'{statuses} {status} {reply}')
    check('even when no account uses it, so the limit says nothing about which do', not mail.to('ghost@example.test'))

    status, _, _ = post('/api/auth/forgot-password', {'email': 'limited@example.test'})
    code = code_for('limited@example.test', 1)
    check('another address is unaffected', status == 200 and code is not None, status)
    check('a reset lifts the sign-in wait (A17) from this address', reset('limited@example.test', code, 'reset-password')[0] == 200
          and sign_in('limited', 'reset-password') == 200)
    # The new password is hashed between checking the code and using it up, so two requests can both find it right.
    post('/api/auth/forgot-password', {'email': 'limited@example.test'})
    code = code_for('limited@example.test', 2)
    raced = {}
    racers = [threading.Thread(target=lambda word=word: raced.__setitem__(word, reset('limited@example.test', code, word)[0]))
              for word in ('first-racer', 'second-racer')]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join()
    winner = next((word for word, status in raced.items() if status == 200), None)
    check('the right code sent twice at once still works only once', sorted(raced.values()) == [200, 400]
          and sign_in('limited', winner) == 200, raced)

    # ------------------------------------------------------------------ A32 guessing across codes
    print('A32 wrong codes are counted per address across every code, ten a day')
    post('/api/auth/register', {'username': 'guessed', 'email': 'guessed@example.test', 'password': 'chalk-and-plates-42'})
    post('/api/auth/forgot-password', {'email': 'guessed@example.test'})
    first = code_for('guessed@example.test', 1)
    wrong = [reset('guessed@example.test', other_code(first, n), 'new-password-1')[0] for n in range(1, 6)]
    # A new code used to start the tries over; now the wrong ones so far still count.
    post('/api/auth/forgot-password', {'email': 'guessed@example.test'})
    second = code_for('guessed@example.test', 2)
    wrong += [reset('guessed@example.test', other_code(second, n), 'new-password-1')[0] for n in range(1, 6)]
    status, headers, reply = reset('guessed@example.test', second, 'new-password-1')
    check('after ten wrong codes in a day, even the right one waits', wrong == [400] * 10 and status == 429
          and int(headers.get('retry-after', 0)) > 80000 and 'Too many wrong codes' in reply.get('error', ''), f'{wrong} {status} {reply}')
    check('saying how long, in hours', reply.get('error', '').endswith('Try again in 24 hours.'), reply)
    check('and the password is unchanged', sign_in('guessed', 'chalk-and-plates-42') == 200)
    ghost_wrong = [reset('nobody-here@example.test', f'{n:06d}', 'new-password-1')[0] for n in range(10)]
    status, _, ghost_reply = reset('nobody-here@example.test', '000000', 'new-password-1')
    check('an address with no account is limited the same way, so the limit says nothing about which have one',
          ghost_wrong == [400] * 10 and status == 429 and ghost_reply.get('error') == reply.get('error'), f'{ghost_wrong} {status} {ghost_reply}')

    # ------------------------------------------------------------------ A34 what a new account's details must be
    print('A34 a new username, email and password follow the rules, and existing accounts keep what they have')

    def register(username, email, password='chalk-and-plates-42'):
        return post('/api/auth/register', {'username': username, 'email': email, 'password': password})

    for label, username, words in [
        ('33 characters', 'u' * 33, '32 characters or fewer'),
        ('a tab in it', 'tab\tbed', 'invisible or control'),
        ('a zero-width space in it', 'zero​width', 'invisible or control'),
        ('a no-break space in it', 'no break', 'invisible or control'),
    ]:
        status, _, reply = register(username, f'user{len(label)}@example.test')
        check(f'a username with {label} is refused, saying why', status == 400 and words in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = register('x' * 32, 'longest@example.test')
    check('32 characters is fine', status == 200, f'{status} {reply}')
    status, _, reply = register('Jo Lifter', 'jo@example.test')
    check('and so is a space between words', status == 200, f'{status} {reply}')

    for label, email in [
        ('a one-letter top-level domain', 'short@example.c'),
        ('a top-level domain of digits', 'digits@example.123'),
        ('two dots in a row', 'two..dots@example.test'),
        ('a dot to start', '.dot@example.test'),
        ('a dot before the @', 'dot.@example.test'),
        ('a domain label starting with a hyphen', 'hyphen@-example.test'),
        ('a domain label ending with a hyphen', 'hyphen@example-.test'),
        ('two dots in the domain', 'dots@example..test'),
        ('an underscore in the domain', 'under@exa_mple.test'),
        ('a comma', 'com,ma@example.test'),
        ('an accented letter', 'josé@example.test'),
        ('a local part of 65 characters', 'l' * 65 + '@example.test'),
        ('255 characters in all', 'x@' + 'a' * 63 + '.' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 56 + '.test'),
    ]:
        status, _, reply = register(f'mail{len(email)}', email)
        check(f'an email with {label} is refused', status == 400 and 'valid email' in reply.get('error', ''), f'{status} {reply}')
    check('(that last one is 255 characters)', len('x@' + 'a' * 63 + '.' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 56 + '.test') == 255)
    for n, email in enumerate(['first.last+gym@mail.example.co.uk', "o'brien@example.test", 'user@xn--bcher-kva.example',
                               'x@' + 'a' * 63 + '.' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 55 + '.test',
                               'l' * 64 + '@example.test', 'Digits1@Sub-Domain2.Example.test']):
        status, _, reply = register(f'goodmail{n}', email)
        check(f'a real address is taken: {email[:40]}', status == 200 and reply['user']['email'] == email.lower(), f'{status} {reply}')

    for label, username, email, password, words in [
        ('7 characters', 'short1', 'short1@example.test', 'abc-de7', '8+'),
        ('129 characters', 'long1', 'long1@example.test', 'abcdefgh-' * 14 + 'abc', '128 characters or fewer'),
        ('only 4 different characters', 'variety1', 'variety1@example.test', 'abababcdcdcd', '5 different characters'),
        ('a common one', 'common1', 'common1@example.test', 'password1', 'too common'),
        ('a common one in capitals', 'common2', 'common2@example.test', 'PassWord123', 'too common'),
        ('a run of keys', 'run1', 'run1@example.test', '12345678', 'too common'),
        ('a run of keys backwards', 'run2', 'run2@example.test', 'hgfedcba', 'too common'),
        ('the username in it', 'deadlifter', 'dl@example.test', 'I-am-DeadLifter-99', 'username or email'),
        ('the name of the email in it', 'squatter', 'benchqueen@example.test', 'benchqueen-2026', 'username or email'),
    ]:
        status, _, reply = register(username, email, password)
        check(f'a password with {label} is refused, saying why', status == 400 and words in reply.get('error', ''), f'{status} {reply}')
    status, headers, reply = register('passphrase', 'phrase@example.test', 'correct horse battery staple')
    check('a few words together are fine', status == 200, f'{status} {reply}')
    phrase = session_of(headers)
    status, _, reply = register('maxlength', 'maxlength@example.test', 'abcdefgh-' * 14 + 'ab')
    check('and so are 128 characters', status == 200, f'{status} {reply}')

    status, _, reply = post('/api/account/password', {'currentPassword': 'correct horse battery staple', 'newPassword': 'letmein123'}, phrase)
    check('changing to a common password is refused', status == 400 and 'too common' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = post('/api/account/password', {'currentPassword': 'correct horse battery staple', 'newPassword': 'passphrase-again'}, phrase)
    check('and to one with the username in it', status == 400 and 'username or email' in reply.get('error', ''), f'{status} {reply}')
    check('neither changed it', sign_in('passphrase', 'correct horse battery staple') == 200)
    status, _, reply = post('/api/account/email', {'email': 'phrase@example.c', 'password': 'correct horse battery staple'}, phrase)
    check('changing to an address that is not a real one is refused', status == 400 and 'valid email' in reply.get('error', ''), f'{status} {reply}')

    # Accounts from before the rules: a long username, a weak password and an email the rules now refuse.
    db = sqlite3.connect(db_path)
    salt = 'oldaccountsalt'
    weak = hashlib.pbkdf2_hmac('sha256', b'password1', salt.encode(), 1000).hex()
    db.execute('INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, 0)',
               ('a-username-from-before-the-limit-of-32', 'veteran@mail.x', f'pbkdf2_sha256$1000${salt}${weak}'))
    db.commit()
    db.close()
    check('an older account with a long username and a weak password still signs in',
          sign_in('a-username-from-before-the-limit-of-32', 'password1') == 200)
    check('and with its older email too', sign_in('veteran@mail.x', 'password1') == 200)
    status, _, _ = post('/api/auth/forgot-password', {'email': 'veteran@mail.x'})
    code = code_for('veteran@mail.x', 1) if status == 200 else None
    check('a reset code still reaches that email', status == 200 and code is not None, status)
    status, _, reply = reset('veteran@mail.x', code, 'qwerty123')
    check('but the new password has to follow the rules', status == 400 and 'too common' in reply.get('error', ''), f'{status} {reply}')
    status, _, reply = reset('veteran@mail.x', code, 'a-username-from-before-the-limit-of-32!')
    check('the username in it too, which is checked once the code is right', status == 400 and 'username or email' in reply.get('error', ''),
          f'{status} {reply}')
    status, _, reply = reset('veteran@mail.x', code, 'stronger than before')
    check('and the code still works for one that does', status == 200, f'{status} {reply}')


def run_admin(t, check, request):
    main, mail = t.server, t.mail
    db_path = t.db_path('test.db')

    def post(path, body, token=None):
        return request('POST', path, json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=token)

    def sign_in(login, password):
        return post('/api/auth/login', {'login': login, 'password': password})

    def me(token):
        return main.api('GET', '/api/auth/me', token=token)[0]['user']

    def session_of(headers):
        return headers.get('set-cookie', '').split('session=')[1].split(';')[0]

    # ------------------------------------------------------------------ A20 the admin commands
    print('A20 an admin manages accounts from the command line while the server runs')
    db = sqlite3.connect(db_path)
    db.execute("UPDATE users SET email = NULL WHERE username = 'racer'")
    db.commit()
    count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    db.close()
    status, out, err = main.admin('users')
    lines = out.splitlines()
    check('users lists every account, one a line', status == 0 and len(lines) == count, f'{status} {len(lines)} of {count} {err}')
    check('with its email, or that it has none',
          any(line.split(maxsplit=1) == ['tester', 'tester@example.test'] for line in lines)
          and any(line.split(maxsplit=1) == ['racer', '(no email)'] for line in lines), out)

    _, headers, _ = sign_in('tester', 'chalk-and-plates-42')
    other_session = session_of(headers)
    post('/api/auth/forgot-password', {'email': 'tester@example.test'})
    code = mail.code(mail.wait('tester@example.test', 1))
    status, out, err = main.admin('reset-password', 'tester', stdin='admin-chosen-1\n')
    check('reset-password sets the password typed in', status == 0 and 'tester' in out, f'{status} {out!r} {err!r}')
    check('the old password no longer signs in', sign_in('tester', 'chalk-and-plates-42')[0] == 401)
    check('the new one does', sign_in('tester', 'admin-chosen-1')[0] == 200)
    check('every session of the account was signed out', me(other_session) is None and me(t.token) is None)
    status, _, _ = post('/api/auth/reset-password', {'email': 'tester@example.test', 'code': code, 'password': 'emailed-code-1'})
    check('and a reset code emailed before it stops working', status == 400, status)
    status, out, err = main.admin('reset-password', 'TESTER@example.test', stdin='admin-chosen-2\n')
    check('the account can be named by its email too', status == 0 and sign_in('tester', 'admin-chosen-2')[0] == 200, f'{status} {err!r}')

    for label, args, stdin, words in [
        ('an account that does not exist', ('reset-password', 'nobody'), 'admin-chosen-3\n', 'No account'),
        ('a password under 8 characters', ('reset-password', 'tester'), 'short\n', '8+'),
        ('no password at all', ('reset-password', 'tester'), '', '8+'),
        ('one of the most common passwords', ('reset-password', 'tester'), 'Password1\n', 'too common'),
        ('a run of keys', ('reset-password', 'tester'), '123456789\n', 'too common'),
        ('the username in it', ('reset-password', 'tester'), 'tester-lifts-daily\n', 'username or email'),
    ]:
        status, out, err = main.admin(*args, stdin=stdin)
        check(f'refused, saying why: {label}', status == 1 and words in err, f'{status} {out!r} {err!r}')
    check('and none of them changed the password', sign_in('tester', 'admin-chosen-2')[0] == 200)

    status, out, err = main.admin('set-email', 'tester', ' Tester.New@Example.TEST ')
    signed_in, _, reply = sign_in('tester.new@example.test', 'admin-chosen-2')
    check('set-email changes the email, in lowercase, and the account signs in with it',
          status == 0 and signed_in == 200 and reply['user']['email'] == 'tester.new@example.test', f'{status} {out!r} {err!r} {reply}')
    for label, email, words in [('an address that is not one', 'tester', 'valid email'),
                                ("another account's email", 'mailer2@example.test', 'already uses')]:
        status, out, err = main.admin('set-email', 'tester', email)
        check(f'set-email refuses {label}', status == 1 and words in err, f'{status} {out!r} {err!r}')
    status, out, err = main.admin('set-email', 'racer', 'racer@example.test')
    check('and adds one to an account that had none', status == 0 and 'racer@example.test' in main.admin('users')[1], f'{status} {err!r}')

    missing = t.db_path('no-such.db')
    status, out, err = main.admin('users', env={'WORKOUT_DB': missing})
    check('pointed at a database that does not exist, it says so', status == 1 and 'no database' in err.lower(), f'{status} {err!r}')
    check('and does not create one', not os.path.exists(missing))

    # ------------------------------------------------------------------ A21 idle connections
    print('A21 a connection that stops sending is closed after REQUEST_TIMEOUT seconds')
    quick = t.start_server('timeout.db', {'REQUEST_TIMEOUT': '2'})

    def closed_after(first_bytes):
        """Seconds until the server closes a connection that sends `first_bytes` and then nothing, or None."""
        connection = socket.create_connection(('127.0.0.1', quick.port))
        connection.settimeout(10)
        started = time.monotonic()
        try:
            if first_bytes:
                connection.sendall(first_bytes)
            return time.monotonic() - started if connection.recv(1) == b'' else None
        except OSError:
            return None
        finally:
            connection.close()

    elapsed = closed_after(b'')
    check('one that sends nothing', elapsed is not None and 1.5 < elapsed < 6, elapsed)
    elapsed = closed_after(b'GET /login.html HTTP/1.1\r\nHost: 127.0.0.1\r\n')
    check('one that stops halfway through a request', elapsed is not None and 1.5 < elapsed < 6, elapsed)
    check('and the server goes on answering', quick.raw('GET', '/login.html')[0] == 200)

    # ------------------------------------------------------------------ A36 stopping
    # On Windows a SIGTERM sent with os.kill ends the process outright, so there is no handler to check.
    if hasattr(signal, 'SIGKILL'):
        print('A36 SIGTERM (docker stop, systemctl stop) stops the server at once, cleanly')
        stopping = t.start_server('stopping.db')
        stopping.process.send_signal(signal.SIGTERM)
        try:
            status = stopping.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            status = None
        check('it exits within seconds, with status 0', status == 0, status)


def run_export(t, check, request):
    json_headers = {'Content-Type': 'application/json'}

    def register(name):
        _, cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})
        return cookie.split('session=')[1].split(';')[0]

    def utc_ms(*when):
        return int(datetime.datetime(*when, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    def import_file(data, token):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        return request('POST', '/api/import', body, json_headers, token=token)

    def workouts_of(token):
        return t.api('GET', '/api/workouts', token=token)[0]['workouts']

    print('A23 an account is exported whole, as JSON and as a spreadsheet')
    source = register('exporter')
    # From a finished session (it has a clientId), in kilograms, with a timed exercise and a skipped one; its name looks
    # like a spreadsheet formula. Then one from the workout form, which has no clientId and no sets.
    finished = {'name': '=SUM(A1) Push', 'notes': 'felt strong', 'createdAt': utc_ms(2026, 3, 10, 2), 'clientId': 'export-1',
                'unit': 'kg', 'duration': 3000,
                'exercises': [t.ex('Bench Press', 80, 5, [(5, 80), (5, 82.5)]),
                              {'name': 'Plank', 'weight': '', 'reps': '60', 'timed': True, 'sets': [{'weight': '', 'reps': 45}]},
                              t.ex('Dips', 0, 10, [])]}
    formed = {'name': 'Form Workout', 'notes': '', 'createdAt': utc_ms(2026, 3, 12, 12), 'exercises': [{'name': 'Squat', 'weight': '100', 'reps': '5'}]}
    for workout in (formed, finished):
        t.api('POST', '/api/workouts', workout, source)
    state = {'settings': {'restDuration': 120, 'unit': 'kg'},
             'templates': [{'id': 'custom-1', 'name': 'Mine', 'exercises': [{'name': 'Row', 'reps': '8'}]}],
             'program': {'definition': 'wendler531', 'unit': 'kg', 'trainingMaxes': {'squat': 100}},
             'exerciseNotes': {'bench press': 'Grip on the rings', 'squat': 'Safeties on 7'},
             'goals': {'bench press': {'name': 'Bench Press', 'target': 100, 'unit': 'kg', 'by': ''},
                       'squat': {'name': 'Squat', 'target': 140, 'unit': 'kg', 'by': '2027-01-01'}},
             'bodyweight': {'2026-03-01': {'weight': 82.5, 'unit': 'kg'}, '2026-03-08': {'weight': 82.1, 'unit': 'kg'}},
             'exerciseLibrary': {'thruster': {'name': 'Thruster', 'muscle': 'quads', 'equipment': 'barbell'},
                                 'squat': {'name': 'Squat', 'muscle': '', 'equipment': 'machine'}}}
    t.api('PUT', '/api/state', state, source)

    status, headers, export = request('GET', '/api/export', token=source)
    check('the JSON export is a file to save', status == 200 and headers.get('content-type', '').startswith('application/json')
          and 'attachment; filename="workout-tracker-' in headers.get('content-disposition', ''), f"{status} {headers.get('content-disposition')}")
    check('it says what it is', isinstance(export, dict) and export.get('format') == 'workout-tracker-export' and export.get('version') == 1,
          str(export)[:200])
    names = [w['name'] for w in export.get('workouts', [])] if isinstance(export, dict) else []
    check('every workout, oldest first', names == ['=SUM(A1) Push', 'Form Workout'], names)
    check("without this server's ids", all('id' not in w for w in export.get('workouts', [])))
    check('as it was saved: sets, unit, notes, duration and clientId', names and export['workouts'][0]['exercises'] == finished['exercises']
          and export['workouts'][0]['unit'] == 'kg' and export['workouts'][0]['notes'] == 'felt strong'
          and export['workouts'][0]['duration'] == 3000 and export['workouts'][0]['clientId'] == 'export-1', export.get('workouts', [None])[0])
    check('with the templates, program, settings, exercise notes, goals, bodyweight and exercise library',
          export.get('templates') == state['templates'] and export.get('program') == state['program'] and export.get('settings') == state['settings']
          and export.get('exerciseNotes') == state['exerciseNotes'] and export.get('goals') == state['goals']
          and export.get('bodyweight') == state['bodyweight'] and export.get('exerciseLibrary') == state['exerciseLibrary'], export.get('exerciseLibrary'))
    check('and whose account it was', export.get('account') == {'username': 'exporter', 'email': 'exporter@example.test'}, export.get('account'))

    # Five hours behind UTC, 02:00 UTC on the 10th is still the 9th.
    status, headers, body = request('GET', '/api/export.csv?offset=-300', token=source)
    check('the CSV export is a file to save', status == 200 and headers.get('content-type', '').startswith('text/csv')
          and 'workout-tracker-sets-' in headers.get('content-disposition', ''), f"{status} {headers.get('content-type')}")
    text = body.decode('utf-8') if isinstance(body, bytes) else ''
    check('it starts with a byte-order mark, so Excel reads it as UTF-8', text.startswith('﻿'))
    rows = list(csv.reader(io.StringIO(text.lstrip('﻿'))))
    check('with a header row', rows[:1] == [['Date', 'Workout', 'Exercise', 'Set', 'Weight', 'Unit', 'Reps', 'Seconds', 'Distance', 'Distance unit', 'Calories',
                                         'Average heart rate', 'Floors', 'Incline (%)', 'Resistance level', 'Incline level', 'Cadence (rpm)',
                                         'Damper', 'Stroke rate (spm)', 'Level']], rows[:1])
    blank = [''] * 12
    check('one row per logged set, in the time zone asked for', ["2026-03-09", "'=SUM(A1) Push", 'Bench Press', '1', '80', 'kg', '5', ''] + blank in rows
          and ["2026-03-09", "'=SUM(A1) Push", 'Bench Press', '2', '82.5', 'kg', '5', ''] + blank in rows, rows)
    check('a timed set under Seconds', ["2026-03-09", "'=SUM(A1) Push", 'Plank', '1', '', 'kg', '', '45'] + blank in rows, rows)
    check('no rows for a skipped exercise', not any(row[2] == 'Dips' for row in rows[1:]), rows)
    check('an exercise saved without sets as one row', ['2026-03-12', 'Form Workout', 'Squat', '', '100', 'lbs', '5', ''] + blank in rows, rows)
    check("a name that looks like a formula stays text", all(row[1] != '=SUM(A1) Push' for row in rows), rows)
    status, _, _ = request('GET', '/api/export')
    check('signed out, there is nothing to export', status == 401, status)

    print('A24 importing adds what is missing and never duplicates or overwrites')
    target = register('importer')
    t.api('POST', '/api/workouts', {'name': 'Already Mine', 'notes': '', 'exercises': [{'name': 'Curl', 'weight': 20, 'reps': 10}]}, target)
    t.api('PUT', '/api/state', {'exerciseNotes': {'squat': 'My own squat note'},
                                'goals': {'squat': {'name': 'Squat', 'target': 300, 'unit': 'lbs', 'by': ''}},
                                'bodyweight': {'2026-03-08': {'weight': 180, 'unit': 'lbs'}},
                                'exerciseLibrary': {'squat': {'name': 'Squat', 'muscle': 'glutes', 'equipment': ''}}}, target)
    status, _, result = import_file(export, target)
    check('an export imports into another account', status == 200 and result == {'workouts': 2, 'alreadyHere': 0, 'templates': 1, 'settings': True,
                                                                                  'program': True, 'notes': 1, 'goals': 1, 'bodyweights': 1,
                                                                                  'exercises': 1},
          f'{status} {result}')
    mine = {w['name']: w for w in workouts_of(target)}
    check('its workouts arrive as they were, beside what was there',
          set(mine) == {'Already Mine', 'Form Workout', '=SUM(A1) Push'} and mine['=SUM(A1) Push']['exercises'] == finished['exercises']
          and mine['=SUM(A1) Push']['createdAt'] == finished['createdAt'], sorted(mine))
    imported_state = t.api('GET', '/api/state', token=target)[0]
    check('with the templates, program and settings', {k: imported_state[k] for k in ('settings', 'templates', 'program')}
          == {k: state[k] for k in ('settings', 'templates', 'program')}, imported_state)
    check("and the notes for exercises that had none, keeping the account's own",
          imported_state['exerciseNotes'] == {'squat': 'My own squat note', 'bench press': 'Grip on the rings'}, imported_state['exerciseNotes'])
    check("and the goals for exercises that had none, keeping the account's own",
          imported_state['goals'] == {'squat': {'name': 'Squat', 'target': 300, 'unit': 'lbs', 'by': ''},
                                      'bench press': state['goals']['bench press']}, imported_state['goals'])
    check("and the bodyweight for days that had none, keeping the account's own",
          imported_state['bodyweight'] == {'2026-03-08': {'weight': 180, 'unit': 'lbs'}, '2026-03-01': {'weight': 82.5, 'unit': 'kg'}},
          imported_state['bodyweight'])
    check("and the muscle and equipment of exercises that had none, keeping the account's own",
          imported_state['exerciseLibrary'] == {'squat': {'name': 'Squat', 'muscle': 'glutes', 'equipment': ''},
                                                'thruster': state['exerciseLibrary']['thruster']}, imported_state['exerciseLibrary'])
    status, _, result = import_file(export, target)
    check('importing the same file again adds nothing', status == 200 and result == {'workouts': 0, 'alreadyHere': 2, 'templates': 0,
                                                                                     'settings': False, 'program': False, 'notes': 0, 'goals': 0,
                                                                                     'bodyweights': 0, 'exercises': 0}, f'{status} {result}')
    check('so nothing is there twice', len(workouts_of(target)) == 3, len(workouts_of(target)))
    status, _, result = import_file(export, source)
    check('nor into the account it came from, even the workout with no clientId', status == 200 and result['workouts'] == 0
          and len(workouts_of(source)) == 2, f'{status} {result}')
    other = {**export, 'settings': {'restDuration': 30}, 'program': {'definition': 'ppl', 'trainingMaxes': {}},
             'templates': [{'id': 'custom-2', 'name': 'Theirs', 'exercises': [{'name': 'Lunge', 'reps': '10'}]}], 'workouts': []}
    status, _, result = import_file(other, target)
    after = t.api('GET', '/api/state', token=target)[0]
    check("an account's own settings and program are kept; new templates are added",
          status == 200 and result['templates'] == 1 and after['settings'] == state['settings'] and after['program'] == state['program']
          and [template['name'] for template in after['templates']] == ['Mine', 'Theirs'], f'{status} {result} {after}')

    print('A25 a file that is not an export, or has a bad workout, imports nothing')
    before = len(workouts_of(target))
    for label, data in [('some other JSON', {'format': 'something-else', 'workouts': []}),
                        ('no workouts list', {'format': 'workout-tracker-export'}),
                        ('not JSON at all', b'Date,Workout\n'),
                        ('a bad workout among good ones', {'workouts': [{'name': 'Good', 'exercises': []}, {'name': 5, 'exercises': []}]})]:
        status, _, reply = import_file(data, target)
        check(f'{label} -> 400 with a message', status == 400 and isinstance(reply, dict) and reply.get('error'), f'{status} {reply!r}')
    status, _, reply = import_file({'workouts': [{'name': 'Good', 'exercises': []}, {'name': 5, 'exercises': []}]}, target)
    check('the message names the workout', 'Workout 2' in (reply or {}).get('error', ''), reply)
    check('and not even the good workout was stored', len(workouts_of(target)) == before, len(workouts_of(target)))
    status, _, _ = import_file(export, None)
    check('signed out, nothing is imported', status == 401, status)
    # Bigger than any other request may be: many workouts with long notes, about 2 MB.
    big = {'workouts': [{'name': f'Big {n}', 'notes': 'x' * 5000, 'createdAt': utc_ms(2025, 1, 1) + n, 'clientId': f'big-{n}',
                         'exercises': [{'name': 'Squat', 'weight': 100, 'reps': 5}]} for n in range(400)]}
    status, _, result = import_file(big, target)
    check('a whole account of several megabytes is accepted', status == 200 and result['workouts'] == 400, f'{status} {result}')
    status, _, reply = request('POST', '/api/import', None, {'Content-Length': str(50 * 1024 * 1024)}, token=target)
    check('but not an unlimited one -> 413', status == 413, f'{status} {reply!r}')

    print('A35 cardio sessions are exported as rows of their own, and imported like any workout')
    runner = register('runner')
    run = {'kind': 'cardio', 'name': 'Run', 'notes': 'Hills', 'createdAt': utc_ms(2026, 4, 2, 2), 'clientId': 'cardio-1', 'exercises': [], 'duration': 1680,
           'cardio': {'activity': 'run', 'distance': 3.1, 'distanceUnit': 'mi', 'calories': 310, 'heartRate': 152}}
    stairs = {'kind': 'cardio', 'name': 'Stair climber', 'notes': '', 'createdAt': utc_ms(2026, 4, 3, 12), 'clientId': 'cardio-2', 'exercises': [],
              'duration': 900, 'cardio': {'activity': 'stairs', 'floors': 60, 'level': 8}}
    for session in (run, stairs):
        t.api('POST', '/api/workouts', session, runner)
    status, _, body = request('GET', '/api/export.csv?offset=-300', token=runner)
    rows = list(csv.reader(io.StringIO((body.decode('utf-8') if isinstance(body, bytes) else '').lstrip('﻿'))))
    check('a session is one row: its time under Seconds, then its distance and unit, calories and heart rate',
          ['2026-04-01', 'Run', 'Run', '', '', '', '', '1680', '3.1', 'mi', '310', '152', ''] + [''] * 7 in rows, rows)
    check('and floors and the level for the stair climber, with no distance unit where there is no distance',
          ['2026-04-03', 'Stair climber', 'Stair climber', '', '', '', '', '900', '', '', '', '', '60', '', '', '', '', '', '', '8'] in rows, rows)
    _, _, export = request('GET', '/api/export', token=runner)
    kept = {w['name']: w for w in export.get('workouts', [])} if isinstance(export, dict) else {}
    check('the JSON export keeps each session as it was saved', kept.get('Run', {}).get('cardio') == run['cardio']
          and kept.get('Run', {}).get('kind') == 'cardio' and kept.get('Stair climber', {}).get('duration') == 900, kept)
    elsewhere = register('runner-elsewhere')
    status, _, result = import_file(export, elsewhere)
    brought = {w['name']: w for w in workouts_of(elsewhere)}
    check('and an import brings them in, once', status == 200 and result['workouts'] == 2 and brought.get('Run', {}).get('cardio') == run['cardio'],
          f'{status} {result}')
    status, _, result = import_file(export, elsewhere)
    check('a second time adding nothing', status == 200 and result['workouts'] == 0 and len(workouts_of(elsewhere)) == 2, f'{status} {result}')


def run_account_security(t, check, request):
    main = t.server
    db_path = t.db_path('test.db')
    json_headers = {'Content-Type': 'application/json'}

    def post(path, body, token=None, headers=None):
        return request('POST', path, json.dumps(body).encode(), {**json_headers, **(headers or {})}, token=token)

    def session_of(headers):
        cookie = headers.get('set-cookie', '')
        return cookie.split('session=')[1].split(';')[0] if 'session=' in cookie else None

    def register(name, password='first-password'):
        return session_of(post('/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': password})[1])

    def sign_in(login, password):
        status, headers, _ = post('/api/auth/login', {'login': login, 'password': password})
        return status, session_of(headers)

    def me(token):
        return main.api('GET', '/api/auth/me', token=token)[0]['user']

    def expires_at(token):
        db = sqlite3.connect(db_path)
        row = db.execute('SELECT expires_at FROM sessions WHERE token = ?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        db.close()
        return row[0] if row else None

    def set_expires_at(token, when):
        db = sqlite3.connect(db_path)
        db.execute('UPDATE sessions SET expires_at = ? WHERE token = ?', (when, hashlib.sha256(token.encode()).hexdigest()))
        db.commit()
        db.close()

    # ------------------------------------------------------------------ A26 changing the password
    print('A26 the password is changed with the current one, and other devices are signed out')
    here = register('changer')
    other_device = sign_in('changer', 'first-password')[1]
    for label, body, expected in [
        ('a wrong current password', {'currentPassword': 'not-the-password', 'newPassword': 'second-password'}, 403),
        ('a new password under 8 characters', {'currentPassword': 'first-password', 'newPassword': 'short'}, 400),
    ]:
        status, _, reply = post('/api/account/password', body, here)
        check(f'{label} -> {expected} with a message', status == expected and reply.get('error'), f'{status} {reply}')
    check('neither changed it, or signed anything out', sign_in('changer', 'first-password')[0] == 200 and me(other_device) is not None)
    check('signed out -> 401', post('/api/account/password', {'currentPassword': 'first-password', 'newPassword': 'second-password'})[0] == 401)
    status, _, reply = post('/api/account/password', {'currentPassword': 'first-password', 'newPassword': 'second-password'}, here)
    check('the right current password changes it', status == 200, f'{status} {reply}')
    check('the reply counts the other sessions signed out', isinstance(reply, dict) and reply.get('signedOut') == 2, reply)
    check('this session stays signed in', me(here) is not None and me(here)['username'] == 'changer')
    check('the other devices are signed out', me(other_device) is None)
    check('the old password no longer signs in', sign_in('changer', 'first-password')[0] == 401)
    check('the new one does', sign_in('changer', 'second-password')[0] == 200)
    guesser = register('guesser')
    guesses = [post('/api/account/password', {'currentPassword': f'guess-{n}', 'newPassword': 'whatever-new'}, guesser)[0] for n in range(5)]
    status = post('/api/account/password', {'currentPassword': 'first-password', 'newPassword': 'whatever-new'}, guesser)[0]
    check('guessing the current password is limited like signing in', guesses == [403] * 5 and status == 429, f'{guesses} {status}')

    # ------------------------------------------------------------------ A27 sessions last from their last use
    print('A27 a session lasts 30 days from when it was last used')
    regular = register('regular')
    status, headers, _ = request('GET', '/api/auth/me', token=regular)
    check('a session used the day it started is left as it is', status == 200 and 'set-cookie' not in headers, headers.get('set-cookie'))
    now = int(time.time())
    set_expires_at(regular, now + 10 * 86400)
    status, headers, reply = request('GET', '/api/auth/me', token=regular)
    cookie = headers.get('set-cookie', '')
    check('one used 20 days in is renewed to a full 30 days', abs(expires_at(regular) - (now + 30 * 86400)) < 60, expires_at(regular) - now)
    check('and its cookie is sent again, to last as long', f'session={regular};' in cookie and 'Max-Age=2592000' in cookie and 'HttpOnly' in cookie, cookie)
    check('the answer is otherwise the same', status == 200 and reply['user']['username'] == 'regular', reply)
    status, headers, _ = request('GET', '/api/auth/me', token=regular)
    check('using it again the same day sends no cookie', 'set-cookie' not in headers, headers.get('set-cookie'))
    set_expires_at(regular, now + 5 * 86400)
    status, headers, _ = request('GET', '/index.html', token=regular)
    check('opening a page renews it too', status == 200 and f'session={regular};' in headers.get('set-cookie', ''), headers.get('set-cookie'))
    set_expires_at(regular, now - 60)
    status, headers, reply = request('GET', '/api/auth/me', token=regular)
    check('an expired session stays expired', reply['user'] is None and 'set-cookie' not in headers, f"{reply} {headers.get('set-cookie')}")

    # ------------------------------------------------------------------ A27b "Remember me"
    print('A27b without "Remember me" a session ends with the browser, and after half a day unused')
    register('rememberer')

    def remembered(token):
        db = sqlite3.connect(db_path)
        row = db.execute('SELECT remember FROM sessions WHERE token = ?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        db.close()
        return row[0] if row else None

    def sign_in_as(login, **extra):
        status, headers, reply = post('/api/auth/login', {'login': login, 'password': 'first-password', **extra})
        return status, headers.get('set-cookie', ''), session_of(headers), reply

    now = int(time.time())
    for label, extra in [('saying nothing, as pages from before the box do', {}), ('remember: true', {'remember': True})]:
        status, cookie, token, _ = sign_in_as('rememberer', **extra)
        check(f'signing in {label} lasts 30 days, and the cookie outlives the browser',
              status == 200 and 'Max-Age=2592000' in cookie and 'HttpOnly' in cookie, cookie)
        check(f'and the server keeps it 30 days ({label})', abs(expires_at(token) - (now + 30 * 86400)) < 60 and remembered(token) == 1, expires_at(token) - now)
    status, cookie, forgotten, _ = sign_in_as('rememberer', remember=False)
    check('remember: false is still a sign-in', status == 200 and me(forgotten)['username'] == 'rememberer', status)
    check('its cookie has no Max-Age, so the browser drops it when it closes', 'Max-Age' not in cookie and 'Expires' not in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie, cookie)
    check('and the server drops it after half a day', abs(expires_at(forgotten) - (now + 12 * 3600)) < 60 and remembered(forgotten) == 0, expires_at(forgotten) - now)
    for bad in ('yes', 1, 0, None, 'false', []):
        status, _, reply = post('/api/auth/login', {'login': 'rememberer', 'password': 'first-password', 'remember': bad})
        check(f'remember: {bad!r} is refused rather than guessed at -> 400', status == 400 and 'remember' in reply.get('error', ''), f'{status} {reply}')
    status, headers, _ = post('/api/auth/login', {'login': 'rememberer', 'password': 'wrong-password', 'remember': False})
    check('a wrong password gets no cookie either way', status == 401 and 'set-cookie' not in headers, status)
    status, headers, _ = post('/api/auth/register', {'username': 'forgetful', 'email': 'forgetful@example.test', 'password': 'first-password', 'remember': False})
    cookie = headers.get('set-cookie', '')
    check('creating an account without it gives the same short session', status == 200 and 'Max-Age' not in cookie and remembered(session_of(headers)) == 0, f'{status} {cookie}')
    status, headers, _ = post('/api/auth/register', {'username': 'mindful', 'email': 'mindful@example.test', 'password': 'first-password', 'remember': True})
    check('creating one with it gives the long one', status == 200 and 'Max-Age=2592000' in headers.get('set-cookie', ''), headers.get('set-cookie'))
    check('and so does saying nothing', remembered(register('saying-nothing')) == 1)

    # Renewed on its own clock: once an hour of the half day has gone, and still without a Max-Age.
    set_expires_at(forgotten, now + 12 * 3600 - 30 * 60)
    status, headers, _ = request('GET', '/api/auth/me', token=forgotten)
    check('one used half an hour in is left as it is', status == 200 and 'set-cookie' not in headers, headers.get('set-cookie'))
    set_expires_at(forgotten, now + 2 * 3600)
    status, headers, _ = request('GET', '/api/auth/me', token=forgotten)
    cookie = headers.get('set-cookie', '')
    check('one used ten hours in is renewed to a full half day', abs(expires_at(forgotten) - (now + 12 * 3600)) < 60, expires_at(forgotten) - now)
    check('and its cookie is sent again, still ending with the browser', f'session={forgotten};' in cookie and 'Max-Age' not in cookie, cookie)
    set_expires_at(forgotten, now - 60)
    status, headers, reply = request('GET', '/api/auth/me', token=forgotten)
    check('one unused for half a day is signed out', reply['user'] is None and 'set-cookie' not in headers, f"{reply} {headers.get('set-cookie')}")
    check('while a remembered one from the same account carries on', me(token) is not None)

    # ------------------------------------------------------------------ A28 changes asked for by other pages
    print('A28 changes asked for by another page on the same site are refused')
    owner = register('forgery-target')
    session = {'name': 'In Progress', 'exercises': [], 'currentIndex': 0}
    post('/api/active-session', {'session': session}, owner)
    before = len(main.api('GET', '/api/workouts', token=owner)[0]['workouts'])
    forged = [
        ('plain text wiping the workout in progress', 'POST', '/api/active-session', b'{"session":null}', {'Content-Type': 'text/plain'}, 415),
        ('a form adding a workout', 'POST', '/api/workouts', b'name=Forged&exercises=', {'Content-Type': 'application/x-www-form-urlencoded'}, 415),
        ('a body with no type at all', 'POST', '/api/workouts', b'{"name":"Forged","exercises":[]}', {}, 415),
        ('JSON from another page on the same site', 'POST', '/api/workouts', b'{"name":"Forged","exercises":[]}',
         {**json_headers, 'Sec-Fetch-Site': 'same-site'}, 403),
        ('JSON from another site', 'PUT', '/api/state', b'{"settings":{}}', {**json_headers, 'Sec-Fetch-Site': 'cross-site'}, 403),
        ('a delete from another page on the same site', 'DELETE', '/api/active-session', None, {'Sec-Fetch-Site': 'same-site'}, 403),
        ('signing out from another page on the same site', 'POST', '/api/auth/logout', None, {'Sec-Fetch-Site': 'same-site'}, 403),
    ]
    for label, method, path, body, headers, expected in forged:
        status, _, reply = request(method, path, body, headers, token=owner)
        check(f'{label} -> {expected}', status == expected and isinstance(reply, dict) and reply.get('error'), f'{status} {reply!r}')
    after = main.api('GET', '/api/active-session', token=owner)[0]['session']
    check('the workout in progress is untouched', after == session, after)
    check('no workout was added', len(main.api('GET', '/api/workouts', token=owner)[0]['workouts']) == before)
    check('and the session is still signed in', me(owner) is not None)
    status, _, _ = post('/api/workouts', {'name': 'Mine', 'exercises': []}, owner, {'Sec-Fetch-Site': 'same-origin'})
    check("the site's own pages still make changes", status == 201, status)
    status, _, _ = request('GET', '/api/workouts', None, {'Sec-Fetch-Site': 'cross-site'}, token=owner)
    check('reading is not refused (the browser keeps the answer from another site)', status == 200, status)


def run_compression(t, check, request):
    gz = {'Accept-Encoding': 'gzip, deflate, br'}
    frontend = os.path.join(REPO_ROOT, 'frontend')

    def register(name):
        cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    print('A29 text is sent gzipped to browsers that take it')
    with open(os.path.join(frontend, 'script.js'), 'rb') as file:
        script = file.read()
    status, headers, body = request('GET', '/script.js', None, gz)
    check('a script is gzipped', status == 200 and headers.get('content-encoding') == 'gzip' and 'Accept-Encoding' in headers.get('vary', ''),
          f"{status} {headers.get('content-encoding')} {headers.get('vary')}")
    check('to a fraction of its size', isinstance(body, bytes) and len(body) < len(script) / 2 and headers.get('content-length') == str(len(body)),
          f"{len(body) if isinstance(body, bytes) else body!r} of {len(script)}")
    check('and unpacks to the file exactly', isinstance(body, bytes) and gzip.decompress(body) == script)
    check('with its type and date as before', headers.get('content-type') == 'text/javascript; charset=utf-8' and headers.get('last-modified'), headers)
    status, _, body = request('GET', '/script.js', None, {**gz, 'If-Modified-Since': headers.get('last-modified', '')})
    check('an unchanged script is still a 304', status == 304 and not body, status)
    status, headers, body = request('GET', '/script.js')
    check('a client that does not ask for gzip gets the file as it is', status == 200 and 'content-encoding' not in headers and body == script, headers.get('content-encoding'))
    status, headers, _ = request('GET', '/script.js', None, {'Accept-Encoding': 'gzip;q=0, identity'})
    check('nor one that refuses it', status == 200 and 'content-encoding' not in headers, headers.get('content-encoding'))
    status, headers, _ = request('GET', '/icons/icon-192.png', None, gz)
    check('images, already compressed, go as they are', status == 200 and 'content-encoding' not in headers, headers.get('content-encoding'))
    busy = register('compressed')
    status, headers, body = request('GET', '/', None, gz, token=busy)
    check('the Tracker page at / is gzipped too', status == 200 and headers.get('content-encoding') == 'gzip'
          and b'<title>Workout Tracker</title>' in gzip.decompress(body), f"{status} {headers.get('content-encoding')}")
    status, headers, _ = request('GET', '/progress.html', None, gz)
    check('and signed out, the redirect to sign in is unchanged', status == 303, status)

    for n in range(10):
        t.api('POST', '/api/workouts', {'name': f'Workout {n}', 'notes': 'Felt good. ' * 10, 'exercises': [t.ex('Squat', 100 + n, 5, [(5, 100 + n)] * 5)]}, busy)
    plain = request('GET', '/api/workouts', token=busy)
    status, headers, body = request('GET', '/api/workouts', None, gz, token=busy)
    check('the workouts list is gzipped', status == 200 and headers.get('content-encoding') == 'gzip' and headers.get('content-length') == str(len(body)),
          f"{status} {headers.get('content-encoding')}")
    check('and unpacks to the same JSON', isinstance(body, bytes) and json.loads(gzip.decompress(body)) == plain[2])
    status, headers, _ = request('GET', '/api/auth/me', None, gz, token=busy)
    check('a small answer is not worth gzipping', status == 200 and 'content-encoding' not in headers, headers.get('content-encoding'))
    status, headers, body = request('GET', '/api/export.csv', None, gz, token=busy)
    check('an export is gzipped on its way too', status == 200 and headers.get('content-encoding') == 'gzip'
          and gzip.decompress(body).decode('utf-8').lstrip('﻿').startswith('Date,Workout'), f"{status} {headers.get('content-encoding')}")

    print('A29b the keep-awake video is served in byte ranges, as Safari needs to play it')
    with open(os.path.join(frontend, 'media', 'keep-awake.mp4'), 'rb') as file:
        video = file.read()
    size = len(video)
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, gz)
    check('the whole video, saying ranges can be asked for', status == 200 and body == video and headers.get('accept-ranges') == 'bytes'
          and headers.get('content-type') == 'video/mp4' and headers.get('content-length') == str(size) and 'content-encoding' not in headers,
          f"{status} {headers}")
    check('with the same security headers as everything else', "default-src 'self'" in headers.get('content-security-policy', '')
          and headers.get('x-content-type-options') == 'nosniff', headers)
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, {'Range': 'bytes=0-1'})
    check("Safari's first ask, the first two bytes -> 206 with just those", status == 206 and body == video[:2]
          and headers.get('content-range') == f'bytes 0-1/{size}' and headers.get('content-length') == '2', f"{status} {headers.get('content-range')} {body!r}")
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, {'Range': 'bytes=100-'})
    check('from a byte to the end', status == 206 and body == video[100:] and headers.get('content-range') == f'bytes 100-{size - 1}/{size}',
          headers.get('content-range'))
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, {'Range': 'bytes=-10'})
    check('the last ten bytes', status == 206 and body == video[-10:] and headers.get('content-range') == f'bytes {size - 10}-{size - 1}/{size}',
          headers.get('content-range'))
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, {'Range': f'bytes=0-{size + 500}'})
    check('a range past the end stops at the end', status == 206 and body == video, headers.get('content-range'))
    status, headers, _ = request('GET', '/media/keep-awake.mp4', None, {'Range': f'bytes={size}-'})
    check('one starting past the end -> 416, saying the size', status == 416 and headers.get('content-range') == f'bytes */{size}', f"{status} {headers.get('content-range')}")
    status, headers, body = request('GET', '/media/keep-awake.mp4', None, {'Range': 'bytes=0-1,5-9'})
    check('several ranges at once get the whole video, which HTTP allows', status == 200 and body == video, status)
    status, headers, body = request('HEAD', '/media/keep-awake.mp4', None, {'Range': 'bytes=0-1'})
    check('HEAD answers the same headers with no body', status == 206 and not body and headers.get('content-length') == '2', f"{status} {body!r}")
    status, _, _ = request('GET', '/media/no-such.mp4', None, {'Range': 'bytes=0-1'})
    check('a video that is not there -> 404', status == 404, status)
    status, headers, _ = request('GET', '/media/../../backend/server.py.mp4')
    check('and a path cannot climb out of the frontend', status == 404, status)


def run_deletion(t, check, request):
    main = t.server
    json_headers = {'Content-Type': 'application/json'}

    def post(path, body, token=None):
        return request('POST', path, json.dumps(body).encode(), json_headers, token=token)

    def session_of(headers):
        cookie = headers.get('set-cookie', '')
        return cookie.split('session=')[1].split(';')[0] if 'session=' in cookie else None

    def register(name):
        return session_of(post('/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1])

    def me(token):
        return main.api('GET', '/api/auth/me', token=token)[0]['user']

    def rows_of(user_id):
        db = sqlite3.connect(t.db_path('test.db'))
        counts = {table: db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id = ?', (user_id,)).fetchone()[0]
                  for table in ('sessions', 'workouts', 'active_sessions', 'user_state')}
        counts['users'] = db.execute('SELECT COUNT(*) FROM users WHERE id = ?', (user_id,)).fetchone()[0]
        db.close()
        return counts

    print('A30 an account is deleted, with everything in it, with its password')
    leaver = register('leaver')
    leaver_id = me(leaver)['id']
    other_device = session_of(post('/api/auth/login', {'login': 'leaver', 'password': 'chalk-and-plates-42'})[1])
    main.api('POST', '/api/workouts', {'name': 'Mine', 'exercises': [t.ex('Squat', 100, 5, [(5, 100)])]}, leaver)
    main.api('PUT', '/api/state', {'settings': {'restDuration': 120}, 'templates': [], 'program': None}, leaver)
    main.api('POST', '/api/active-session', {'session': {'name': 'Going', 'exercises': [], 'currentIndex': 0}}, leaver)
    status, _, reply = post('/api/account/delete', {'password': 'wrong-password'}, leaver)
    check('a wrong password -> 403, and nothing is deleted', status == 403 and reply.get('error') and me(leaver) is not None
          and rows_of(leaver_id)['workouts'] == 1, f'{status} {reply}')
    check('signed out -> 401', post('/api/account/delete', {'password': 'chalk-and-plates-42'})[0] == 401)
    status, headers, reply = post('/api/account/delete', {'password': 'chalk-and-plates-42'}, leaver)
    check('the right password deletes it', status == 200, f'{status} {reply}')
    check('and clears the cookie', 'session=;' in headers.get('set-cookie', '') and 'Max-Age=0' in headers.get('set-cookie', ''), headers.get('set-cookie'))
    check('with every workout, setting, session and workout in progress', rows_of(leaver_id) == {'sessions': 0, 'workouts': 0, 'active_sessions': 0,
                                                                                                  'user_state': 0, 'users': 0}, rows_of(leaver_id))
    check('so no device is signed in to it any more', me(leaver) is None and me(other_device) is None)
    check('and it no longer signs in', post('/api/auth/login', {'login': 'leaver', 'password': 'chalk-and-plates-42'})[0] == 401)
    check('its username and email are free again', register('leaver') is not None)
    guesser = register('careful')
    guesses = [post('/api/account/delete', {'password': f'guess-{n}'}, guesser)[0] for n in range(5)]
    status = post('/api/account/delete', {'password': 'chalk-and-plates-42'}, guesser)[0]
    check('guessing the password here is limited like signing in', guesses == [403] * 5 and status == 429 and me(guesser) is not None, f'{guesses} {status}')

    print('A31 an admin deletes an account from the command line')
    register('removable')
    main.api('POST', '/api/workouts', {'name': 'Theirs', 'exercises': [t.ex('Row', 80, 8, [(8, 80)])]}, register('removable2'))
    code, out, err = main.admin('delete-user', 'removable')
    check('without a terminal to ask at, it needs --yes', code == 1 and '--yes' in err and 'Nothing was changed' in err and
          main.admin('users')[1].count('removable ') == 1, f'{code} {out!r} {err!r}')
    code, out, err = main.admin('delete-user', 'removable2@example.test', '--yes')
    check('with --yes it deletes it, by username or email, and says how much went', code == 0 and out.strip() == 'Deleted removable2 and their 1 workout.',
          f'{code} {out!r} {err!r}')
    check('and the account is gone', 'removable2' not in main.admin('users')[1])
    code, _, err = main.admin('delete-user', 'nobody-here', '--yes')
    check('an account that does not exist -> an error', code == 1 and 'No account' in err, err)


def run_state_merge(t, check, request):
    """Two devices changing the account state from the same copy (PATCH /api/state): both changes kept, the later winning
    only where both changed the same thing, and a program's runs never mixed."""
    print('A37 changes to the account state from two devices are merged, not lost')
    api = t.api
    _, cookie = api('POST', '/api/auth/register', {'username': 'two-devices', 'email': 'two@example.test', 'password': 'chalk-and-plates-42'})
    me = cookie.split('session=')[1].split(';')[0]

    def stored():
        return api('GET', '/api/state', token=me)[0]

    def patch(body):
        return api('PATCH', '/api/state', body, me)[0]

    def start_from(part, value):
        api('PUT', '/api/state', {part: value}, me)
        return value

    def status_of(body, headers=None):
        return request('PATCH', '/api/state', json.dumps(body).encode(), {'Content-Type': 'application/json', **(headers or {})}, token=me)[0]

    base = start_from('settings', {'unit': 'lbs', 'restDuration': 90, 'weeklyGoal': 3})
    patch({'settings': {'base': base, 'value': {**base, 'restDuration': 120}}})
    merged = patch({'settings': {'base': base, 'value': {**base, 'unit': 'kg'}}})
    check('settings changed on two devices from the same copy keep both changes', merged['settings'] == {'unit': 'kg', 'restDuration': 120, 'weeklyGoal': 3}, merged['settings'])
    check('and the server keeps the merge', stored()['settings'] == merged['settings'], stored()['settings'])
    merged = patch({'settings': {'base': base, 'value': {**base, 'restDuration': 150}}})
    check('the same setting changed on both: the later change wins, and the rest stay', merged['settings'] == {'unit': 'kg', 'restDuration': 150, 'weeklyGoal': 3}, merged['settings'])

    def goal(name, target):
        return {'name': name, 'target': target, 'unit': 'lbs', 'by': ''}

    base = start_from('goals', {'bench press': goal('Bench Press', 200)})
    patch({'goals': {'base': base, 'value': {**base, 'squat': goal('Squat', 300)}}})
    merged = patch({'goals': {'base': base, 'value': {}}})
    check('a goal added on one device and another removed on the other: both happen', merged['goals'] == {'squat': goal('Squat', 300)}, merged['goals'])

    base = start_from('bodyweight', {})
    patch({'bodyweight': {'base': base, 'value': {'2026-10-01': {'weight': 181.4, 'unit': 'lbs'}}}})
    merged = patch({'bodyweight': {'base': base, 'value': {'2026-10-02': {'weight': 82.3, 'unit': 'kg'}}}})
    check('weigh-ins on different days from two devices are both kept', sorted(merged['bodyweight']) == ['2026-10-01', '2026-10-02'], merged['bodyweight'])
    base = merged['bodyweight']
    patch({'bodyweight': {'base': base, 'value': {**base, '2026-10-03': {'weight': 180, 'unit': 'lbs'}}}})
    merged = patch({'bodyweight': {'base': base, 'value': {**base, '2026-10-03': {'weight': 81.5, 'unit': 'kg'}}}})
    check('one day weighed on both: the later weigh-in, its weight and unit kept together', merged['bodyweight']['2026-10-03'] == {'weight': 81.5, 'unit': 'kg'},
          merged['bodyweight'])

    def template(id, name):
        return {'id': id, 'name': name, 'exercises': [{'name': 'Row', 'reps': '10'}]}

    base = start_from('templates', [template('custom-1', 'Upper'), template('custom-2', 'Lower')])
    patch({'templates': {'base': base, 'value': [template('custom-1', 'Upper A'), template('custom-2', 'Lower'), template('custom-3', 'Push')]}})
    merged = patch({'templates': {'base': base, 'value': [template('custom-1', 'Upper'), template('custom-4', 'Pull')]}})
    check('templates: one renamed and one added on one device, one removed and one added on the other, all four happen',
          [x['name'] for x in merged['templates']] == ['Upper A', 'Push', 'Pull'], [x['name'] for x in merged['templates']])
    base = merged['templates']
    patch({'templates': {'base': base, 'value': [{**base[0], 'name': 'Upper B'}, *base[1:]]}})
    merged = patch({'templates': {'base': base, 'value': base[1:]}})
    check('one template changed on one device and removed on the other, later: it is removed', [x['name'] for x in merged['templates']] == ['Push', 'Pull'],
          [x['name'] for x in merged['templates']])
    base = start_from('templates', [{'name': 'From before ids', 'exercises': []}])
    patch({'templates': {'base': base, 'value': [*base, template('custom-5', 'Legs')]}})
    merged = patch({'templates': {'base': base, 'value': []}})
    check('templates from before they had ids cannot be told apart, so the later list wins whole', merged['templates'] == [], merged['templates'])

    done = {'at': 1, 'skipped': False, 'amrap': None, 'hit': None}
    skipped = {**done, 'skipped': True}
    base = start_from('program', {'definition': 'wendler-531', 'unit': 'lbs', 'startedAt': 1, 'cycle': 1, 'stalls': {}, 'options': {}, 'done': {}, 'lastRollover': None,
                                  'trainingMaxes': {'press': 100, 'deadlift': 300, 'bench': 200, 'squat': 250}})
    patch({'program': {'base': base, 'value': {**base, 'done': {'0-0': done}}}})
    merged = patch({'program': {'base': base, 'value': {**base, 'trainingMaxes': {**base['trainingMaxes'], 'bench': 205}}}})
    check('a program day done on one device and a training max edited on the other: both kept',
          merged['program']['done'] == {'0-0': done} and merged['program']['trainingMaxes'] == {**base['trainingMaxes'], 'bench': 205}, merged['program'])
    base = merged['program']
    patch({'program': {'base': base, 'value': {**base, 'done': {**base['done'], '0-1': done}}}})
    merged = patch({'program': {'base': base, 'value': {**base, 'done': {**base['done'], '0-2': skipped}}}})
    check('days done on two devices are all kept', sorted(merged['program']['done']) == ['0-0', '0-1', '0-2'], merged['program']['done'])
    base = merged['program']
    patch({'program': {'base': base, 'value': {**base, 'cycle': 2, 'done': {}, 'trainingMaxes': {lift: weight + 5 for lift, weight in base['trainingMaxes'].items()}}}})
    merged = patch({'program': {'base': base, 'value': {**base, 'done': {**base['done'], '1-0': skipped}}}})
    check('a day skipped on a device still in the last cycle is not carried into the next one, which another device started',
          merged['program']['cycle'] == 2 and merged['program']['done'] == {} and merged['program']['trainingMaxes']['bench'] == 210, merged['program'])
    base = merged['program']
    patch({'program': {'base': base, 'value': {**base, 'done': {'0-0': done}}}})
    in_kg = {lift: round(weight * 0.4536, 1) for lift, weight in base['trainingMaxes'].items()}
    merged = patch({'program': {'base': base, 'value': {**base, 'unit': 'kg', 'trainingMaxes': in_kg}}})
    check('a device converting the program to kilograms wins whole, its weights never mixed with pounds',
          merged['program']['unit'] == 'kg' and merged['program']['trainingMaxes'] == in_kg and merged['program']['done'] == {}, merged['program'])
    base = merged['program']
    patch({'program': {'base': base, 'value': {**base, 'done': {'0-0': done}}}})
    merged = patch({'program': {'base': base, 'value': None}})
    check('ending the program on one device ends it, whatever the other did meanwhile', merged['program'] is None, merged['program'])

    base = start_from('settings', {'soundEnabled': True, 'weeklyGoal': 3, 'unit': 'lbs'})
    patch({'settings': {'base': base, 'value': {**base, 'soundEnabled': False}}})
    api('PATCH', '/api/state', {'settings': {'base': base, 'value': {**base, 'unit': 'kg'}}}, me)
    merged = patch({'settings': {'base': base, 'sent': [{**base, 'soundEnabled': False}], 'value': base}})
    check('a change stored though its answer never came, then changed back: the change back counts, sent with the copy that went',
          merged['settings']['soundEnabled'] is True, merged['settings'])
    check("and another device's change meanwhile stays", merged['settings']['unit'] == 'kg', merged['settings'])
    merged = patch({'settings': {'base': base, 'value': {**base, 'soundEnabled': False}}})
    merged = patch({'settings': {'base': base, 'value': base}})
    check('without it, the change back would look like no change at all, and the lost one would stand', merged['settings']['soundEnabled'] is False, merged['settings'])
    base = start_from('settings', {'weeklyGoal': 3})
    merged = patch({'settings': {'base': base, 'sent': [{'weeklyGoal': 4}], 'value': {'weeklyGoal': 4}}})
    check('a copy sent before that never arrived at all still goes up with the next', merged['settings'] == {'weeklyGoal': 4}, merged['settings'])

    merged = patch({'goals': {'value': {'deadlift': goal('Deadlift', 405)}}})
    check('a part sent without the copy it came from replaces the stored one whole, as before', merged['goals'] == {'deadlift': goal('Deadlift', 405)}, merged['goals'])
    merged = api('PUT', '/api/state', {'goals': {}}, me)[0]
    check('and PUT still replaces, for pages from before', merged['goals'] == {}, merged['goals'])

    def many(prefix):
        return {f'{prefix}{n}': goal(f'{prefix}{n}', 100) for n in range(300)}

    start_from('goals', {})
    patch({'goals': {'base': {}, 'value': many('a')}})
    merged = patch({'goals': {'base': {}, 'value': many('b')}})
    check('a merge that would break a limit (600 goals of 500) keeps the later copy, which was within it',
          sorted(merged['goals']) == sorted(many('b')), len(merged['goals']))

    start_from('bodyweight', {})
    days = [(datetime.date(2026, 1, 1) + datetime.timedelta(days=n)).isoformat() for n in range(12)]

    def weigh(day):
        api('PATCH', '/api/state', {'bodyweight': {'base': {}, 'value': {day: {'weight': 180, 'unit': 'lbs'}}}}, me)

    threads = [threading.Thread(target=weigh, args=(day,)) for day in days]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check('twelve devices weighing in at the same moment, from the same copy: all twelve kept', sorted(stored()['bodyweight']) == days, sorted(stored()['bodyweight']))

    lifetime = {(datetime.date(1960, 1, 1) + datetime.timedelta(days=n)).isoformat(): {'weight': 180.5, 'unit': 'lbs'} for n in range(30000)}
    body = {'bodyweight': {'base': {}, 'value': lifetime}}
    size = len(json.dumps(body))
    check('a lifetime of daily weigh-ins goes up with its base, past the limit other requests have',
          size > 1024 * 1024 and status_of(body) == 200 and len(stored()['bodyweight']) == 30000, size)

    refused = [('a part that is not one', {'diary': {'value': {}}}), ('a part that is not an object', {'settings': 5}),
               ('a part without its value', {'settings': {'base': {}}}), ('a value that is not valid', {'settings': {'base': {}, 'value': []}}),
               ('copies sent that are not a list', {'settings': {'base': {}, 'sent': {}, 'value': {}}}),
               ('copies sent without the base they followed', {'settings': {'sent': [{}], 'value': {}}})]
    for label, body in refused:
        check(f'PATCH refuses {label}', status_of(body) == 400, status_of(body))
    check('and a change sent from another site', status_of({'settings': {'value': {}}}, {'Sec-Fetch-Site': 'cross-site'}) == 403)


def run_bursts(t, check):
    # ------------------------------------------------------------------ A22 many connections at once
    print('A22 a burst of connections is answered, not refused')
    # A page load asks for a dozen files at once while the service worker fetches its cache list. With the standard
    # library's queue of 5 waiting connections, five bursts of 80 lost 90 of 400 requests, and a page that loses a
    # script breaks (programTemplateCards is not defined).
    import socket

    outcomes = {'ok': 0, 'failed': 0}
    lock = threading.Lock()

    def burst(size):
        barrier = threading.Barrier(size)

        def fetch():
            barrier.wait()
            try:
                connection = socket.create_connection(('127.0.0.1', t.port), timeout=10)
                connection.sendall(b'GET /program.js HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
                answered = b' 200 ' in connection.recv(64)[:16]
                connection.close()
            except OSError:
                answered = False
            with lock:
                outcomes['ok' if answered else 'failed'] += 1

        threads = [threading.Thread(target=fetch) for _ in range(size)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    for _ in range(5):
        burst(80)
    check('five bursts of 80 simultaneous requests are all answered', outcomes == {'ok': 400, 'failed': 0}, outcomes)
    check('and the server goes on answering', t.raw('GET', '/login.html')[0] == 200)


def run_routes(t, check, request):
    """The route table (api_routes.py): what answers each request, who may ask, and what is said to a request nothing answers."""
    server = load_server()
    json_headers = {'Content-Type': 'application/json'}
    with_body = ('POST', 'PUT', 'PATCH')

    def ask(method, path, token=None, headers=None):
        send = method in with_body
        return request(method, path, b'{}' if send else None, {**json_headers, **(headers or {})} if send else headers, token=token)

    # ------------------------------------------------------------------ R the table
    print('R   the route table')
    routes, prefixed = server.ROUTES, server.PREFIXED
    handlers = [handler for handler, _ in routes.values()] + [handler for _, _, handler in prefixed]
    check('every route names a method the handler has', all(callable(getattr(server.AppHandler, handler, None)) for handler in handlers), [h for h in handlers if not hasattr(server.AppHandler, h)])
    check('and no two routes share one', len(handlers) == len(set(handlers)), sorted({h for h in handlers if handlers.count(h) > 1}))
    check('every path is under /api/, and a prefix ends in a slash', all(path.startswith('/api/') for _, path in routes) and all(prefix.startswith('/api/') and prefix.endswith('/') for _, prefix, _ in prefixed))
    open_to_anyone = sorted(key for key, (_, public) in routes.items() if public)
    check('exactly these are open to anyone: who is signed in, and the ways of signing in, up, out and back in', open_to_anyone == sorted([
        ('GET', '/api/auth/me'), ('POST', '/api/auth/register'), ('POST', '/api/auth/login'), ('POST', '/api/auth/forgot-password'), ('POST', '/api/auth/reset-password'),
        ('POST', '/api/auth/logout')]), open_to_anyone)
    check('and a route with an id is never one of them', all(not server.find_route(method, prefix + '12')[1] for method, prefix, _ in prefixed))
    check('find_route finds a route, a route with an id, and nothing', server.find_route('GET', '/api/workouts') == ('list_workouts', False)
          and server.find_route('PUT', '/api/workouts/12') == ('update_workout', False) and server.find_route('GET', '/api/workouts/12') == (None, False)
          and server.find_route('GET', '/api/nothing') == (None, False) and server.find_route('POST', '/api/state') == (None, False))

    # ------------------------------------------------------------------ A who may ask
    print('A   who may ask')
    token = api_token(t, 'router')
    closed = [(key, handler) for key, (handler, public) in sorted(routes.items()) if not public] + [((method, prefix + '12'), handler) for method, prefix, handler in prefixed]
    signed_out = {key: ask(*key)[0] for key, _ in closed}
    check('every route that is not open to anyone answers 401 to someone signed out, before it looks at what was sent', set(signed_out.values()) == {401}, {k: v for k, v in signed_out.items() if v != 401})
    # (What changes the account itself asks for its password, and a wrong one counts against it: those are checked in their own sections.)
    answered = {key: ask(*key, token=token)[0] for key, _ in closed if not key[1].startswith('/api/account/')}
    check('and to someone signed in, every one is answered: what is wrong with a request is a 4xx, never a path that is not there',
          all(status != 404 or key[1].startswith('/api/workouts/') for key, status in answered.items()), {k: v for k, v in answered.items() if v == 404})
    check('none of them is a server error', all(status < 500 for status in answered.values()), {k: v for k, v in answered.items() if v >= 500})

    # ------------------------------------------------------------------ U what nothing answers
    print('U   what nothing answers')
    nothing = [('GET', '/api/nothing'), ('POST', '/api/nothing'), ('PUT', '/api/nothing'), ('PATCH', '/api/nothing'), ('DELETE', '/api/nothing'), ('POST', '/api/state'),
               ('DELETE', '/api/workouts'), ('GET', '/api/workouts/12'), ('POST', '/api/workouts/12'), ('PATCH', '/api/workouts/12'), ('GET', '/api/auth/login'),
               ('DELETE', '/api/auth/me'), ('GET', '/api/push/test'), ('PUT', '/api/export'), ('GET', '/api/'), ('GET', '/api/workouts/')]
    signed_out = {key: ask(*key)[0] for key in nothing}
    check('a request nothing answers is 401 to someone signed out, which says nothing of what is and is not there', set(signed_out.values()) == {401}, {k: v for k, v in signed_out.items() if v != 401})
    signed_in = {key: ask(*key, token=token) for key in nothing}
    check('and 404, with a message, to someone signed in', all((status, reply) == (404, {'error': 'Endpoint not found.'}) for status, _, reply in signed_in.values()),
          {k: (v[0], v[2]) for k, v in signed_in.items() if v[0] != 404})
    status, _, reply = request('PUT', '/api/workouts/not-a-number', json.dumps({'name': 'x', 'exercises': [{'name': 'a', 'reps': 1}]}).encode(), json_headers, token=token)
    check('an id that is not a number is a workout that is not found, not an endpoint that is not', (status, reply) == (404, {'error': 'Workout not found.'}), (status, reply))
    status, _, reply = request('PUT', '/api/workouts/12', b'not json', json_headers, token=token)
    check('but what was sent is still checked first', status == 400, (status, reply))
    status, _, reply = request('DELETE', '/api/workouts/not-a-number', None, None, token=token)
    check('and a delete of one is the same', (status, reply) == (404, {'error': 'Workout not found.'}), (status, reply))
    check('a change from another page of the site is refused before the route is looked at, whether the route exists or not',
          ask('POST', '/api/nothing', token=token, headers={'Sec-Fetch-Site': 'same-site'})[0] == 403 and ask('POST', '/api/workouts', token=token, headers={'Sec-Fetch-Site': 'cross-site'})[0] == 403)


def api_token(t, name):
    """A new account's session, for a check that may do things that count against an account."""
    cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
    return cookie.split('session=')[1].split(';')[0]
