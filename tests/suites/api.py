"""The HTTP API on its own, without a browser: bad input, racing uploads, redirects, database upgrades and accounts."""

import csv
import datetime
import gzip
import hashlib
import io
import json
import os
import socket
import sqlite3
import threading
import time

from ..harness import REPO_ROOT

INTERCEPT = False
BROWSER = False
MAIL = True

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
    _, cookie = api('POST', '/api/auth/register', {'username': 'racer', 'email': 'racer@example.test', 'password': 'password123'})
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

    run_security(t, check, request)
    run_structure(t, check, request)
    run_accounts(t, check, request)
    run_admin(t, check, request)
    run_export(t, check, request)
    run_account_security(t, check, request)
    run_compression(t, check, request)
    run_deletion(t, check, request)
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
    opener.api('POST', '/api/auth/register', {'username': 'owner', 'email': 'owner@example.test', 'password': 'password123'})
    opener.stop()
    opener.process.wait(timeout=10)
    closed = t.start_server('closed.db', {'ALLOW_REGISTRATION': '0'})
    check('the server says registration is closed', closed.api('GET', '/api/auth/me')[0].get('registrationOpen') is False)
    status, _, reply = closed.request('POST', '/api/auth/register', json.dumps({'username': 'intruder', 'email': 'intruder@example.test', 'password': 'password123'}).encode(),
                                      {'Content-Type': 'application/json'})
    check('registering is refused with 403', status == 403 and 'turned off' in reply.get('error', ''), f'{status} {reply}')
    check('and no account was created', stored_hash('intruder', t.db_path('closed.db')) is None)
    status, headers, _ = login(closed, 'owner', 'password123')
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
    check('another username from the same address is unaffected', login(main, 'tester', 'password123')[0] == 200)
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

    known = sorted(timed('veteran') for _ in range(3))[1]
    unknown = sorted(timed(f'nobody-{n}') for n in range(3))[1]
    check('an unknown username takes about as long as a wrong password', unknown > known * 0.5,
          f'unknown {unknown:.3f}s, known {known:.3f}s')

    # ------------------------------------------------------------------ A8 cookies
    print('A8  the session cookie is marked Secure behind HTTPS')
    _, headers, _ = login(main, 'tester', 'password123')
    cookie = headers['set-cookie']
    check('plain HTTP: HttpOnly and SameSite, no Secure',
          'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Secure' not in cookie, cookie)
    _, headers, _ = login(main, 'tester', 'password123', {'X-Forwarded-Proto': 'https'})
    check('a proxy reporting HTTPS gets a Secure cookie', headers['set-cookie'].endswith('; Secure'), headers['set-cookie'])
    secure = t.start_server('secure.db', {'SECURE_COOKIES': '1'})
    secure.api('POST', '/api/auth/register', {'username': 'someone', 'email': 'someone@example.test', 'password': 'password123'})
    _, headers, _ = login(secure, 'someone', 'password123')
    check('SECURE_COOKIES=1 marks it Secure without a proxy', headers['set-cookie'].endswith('; Secure'), headers['set-cookie'])

    # ------------------------------------------------------------------ A9 expired sessions
    print('A9  expired sessions are deleted')
    tester_id = main.api('GET', '/api/auth/me', token=t.token)[0]['user']['id']
    db = sqlite3.connect(db_path)
    db.executemany('INSERT INTO sessions VALUES (?, ?, ?)', [(f'stale-{n}', tester_id, 1000 + n) for n in range(5)])
    db.commit()
    db.close()
    login(main, 'tester', 'password123')
    db = sqlite3.connect(db_path)
    stale = db.execute("SELECT COUNT(*) FROM sessions WHERE token LIKE 'stale-%'").fetchone()[0]
    live = db.execute('SELECT COUNT(*) FROM sessions WHERE token = ?', (t.token,)).fetchone()[0]
    db.close()
    check('signing in clears sessions that have expired', stale == 0, stale)
    check('and keeps the ones that have not', live == 1 and main.api('GET', '/api/auth/me', token=t.token)[0]['user'] is not None)

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
            'user_indexes': sorted(r[1] for r in db.execute("PRAGMA index_list('users')")),
        }
    finally:
        db.close()


def run_structure(t, check, request):
    main = t.server
    token = t.token
    json_headers = {'Content-Type': 'application/json'}
    tables = ['active_sessions', 'password_resets', 'sessions', 'user_state', 'users', 'workouts']

    # ------------------------------------------------------------------ A12 schema at startup
    print('A12 the schema is created and versioned at startup, in WAL mode')
    t.start_server('fresh.db')  # the harness only asks /api/auth/me, which never opens the database
    schema = schema_of(t.db_path('fresh.db'))
    check('a new database has every table before any request touches it', schema['tables'] == tables, schema['tables'])
    check('it is at schema version 4', schema['version'] == 4, schema['version'])
    check('with the client_id column and its unique index',
          'client_id' in schema['columns'] and 'workouts_user_client' in schema['indexes'], schema)
    check('with a column for the training program', 'program_json' in schema['state_columns'], schema['state_columns'])
    check('with an email for each account, and its unique index',
          'email' in schema['user_columns'] and 'users_email' in schema['user_indexes'], schema)
    check('in write-ahead-log mode', schema['journal'] == 'wal', schema['journal'])
    legacy = schema_of(t.db_path('legacy.db'))
    check('the database from before client_id (A3) is now at version 4 too', legacy['version'] == 4, legacy['version'])
    check('and has the training program column', 'program_json' in legacy['state_columns'], legacy['state_columns'])
    check('and the email column, and the table of reset codes',
          'email' in legacy['user_columns'] and 'password_resets' in legacy['tables'], legacy)

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
          schema['version'] == 4 and schema['columns'].count('client_id') == 1 and kept == [('Kept', 'k1')], f'{schema} {kept}')

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
    ]
    for label, body in accepted:
        status, _, reply = request('POST', '/api/workouts', json.dumps(body).encode(), json_headers, token=token)
        check(f'accepted: {label}', status == 201, f'{status} {reply}')

    # ------------------------------------------------------------------ A15 editing and deleting
    print('A15 editing a workout that is missing, or not yours, is a 404')
    mine = t.W1
    _, cookie = t.api('POST', '/api/auth/register', {'username': 'neighbour', 'email': 'neighbour@example.test', 'password': 'password123'})
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
    status, _, _ = request('PUT', '/api/state', json.dumps({'program': None}).encode(), json_headers, token=token)
    state = t.api('GET', '/api/state', token=token)[0]
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
        ('no email', {'username': 'nomail', 'password': 'password123'}),
        ('an email with no @', {'username': 'bad1', 'email': 'bad.example.test', 'password': 'password123'}),
        ('an email with two @', {'username': 'bad2', 'email': 'a@b@example.test', 'password': 'password123'}),
        ('an email with a space in it', {'username': 'bad3', 'email': 'a b@example.test', 'password': 'password123'}),
        ('an email with no dot after the @', {'username': 'bad4', 'email': 'a@localhost', 'password': 'password123'}),
        ('an email that is a number', {'username': 'bad5', 'email': 5, 'password': 'password123'}),
        ('a username with an @ in it', {'username': 'me@home', 'email': 'me@example.test', 'password': 'password123'}),
    ]:
        status, _, reply = post('/api/auth/register', body)
        check(f'registering with {label} -> 400', status == 400 and isinstance(reply, dict) and reply.get('error'), f'{status} {reply}')
    status, headers, reply = post('/api/auth/register', {'username': 'mailer', 'email': ' Mailer@Example.TEST ', 'password': 'password123'})
    check('an account is created with its email, trimmed and in lowercase',
          status == 200 and reply['user']['email'] == 'mailer@example.test', f'{status} {reply}')
    mailer = session_of(headers)
    check('/api/auth/me includes the email', me(mailer)['user'] == reply['user'], me(mailer))
    status, _, reply = post('/api/auth/register', {'username': 'copycat', 'email': 'MAILER@example.test', 'password': 'password123'})
    check('the same email in another case is refused -> 409', status == 409 and 'email' in reply.get('error', ''), f'{status} {reply}')
    for label, typed in [('the email', 'mailer@example.test'), ('the email in capitals', 'MAILER@EXAMPLE.TEST'), ('the username', 'mailer')]:
        status, _, reply = post('/api/auth/login', {'login': typed, 'password': 'password123'})
        check(f'signs in with {label}', status == 200 and reply['user']['username'] == 'mailer', f'{status} {reply}')
    status, _, _ = login(main, 'mailer@example.test', 'password123')
    check('a page from before emails, sending it as username, signs in too', status == 200, status)
    check('the email with a wrong password -> 401', sign_in('mailer@example.test', 'wrong-password') == 401)
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
    check('the old password no longer signs in', sign_in('mailer', 'password123') == 401)
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

    _, headers, _ = sign_in('tester', 'password123')
    other_session = session_of(headers)
    post('/api/auth/forgot-password', {'email': 'tester@example.test'})
    code = mail.code(mail.wait('tester@example.test', 1))
    status, out, err = main.admin('reset-password', 'tester', stdin='admin-chosen-1\n')
    check('reset-password sets the password typed in', status == 0 and 'tester' in out, f'{status} {out!r} {err!r}')
    check('the old password no longer signs in', sign_in('tester', 'password123')[0] == 401)
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


def run_export(t, check, request):
    json_headers = {'Content-Type': 'application/json'}

    def register(name):
        _, cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'password123'})
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
             'program': {'definition': 'wendler531', 'unit': 'kg', 'trainingMaxes': {'squat': 100}}}
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
    check('with the templates, program and settings',
          export.get('templates') == state['templates'] and export.get('program') == state['program'] and export.get('settings') == state['settings'])
    check('and whose account it was', export.get('account') == {'username': 'exporter', 'email': 'exporter@example.test'}, export.get('account'))

    # Five hours behind UTC, 02:00 UTC on the 10th is still the 9th.
    status, headers, body = request('GET', '/api/export.csv?offset=-300', token=source)
    check('the CSV export is a file to save', status == 200 and headers.get('content-type', '').startswith('text/csv')
          and 'workout-tracker-sets-' in headers.get('content-disposition', ''), f"{status} {headers.get('content-type')}")
    text = body.decode('utf-8') if isinstance(body, bytes) else ''
    check('it starts with a byte-order mark, so Excel reads it as UTF-8', text.startswith('﻿'))
    rows = list(csv.reader(io.StringIO(text.lstrip('﻿'))))
    check('with a header row', rows[:1] == [['Date', 'Workout', 'Exercise', 'Set', 'Weight', 'Unit', 'Reps', 'Seconds']], rows[:1])
    check('one row per logged set, in the time zone asked for', ["2026-03-09", "'=SUM(A1) Push", 'Bench Press', '1', '80', 'kg', '5', ''] in rows
          and ["2026-03-09", "'=SUM(A1) Push", 'Bench Press', '2', '82.5', 'kg', '5', ''] in rows, rows)
    check('a timed set under Seconds', ["2026-03-09", "'=SUM(A1) Push", 'Plank', '1', '', 'kg', '', '45'] in rows, rows)
    check('no rows for a skipped exercise', not any(row[2] == 'Dips' for row in rows[1:]), rows)
    check('an exercise saved without sets as one row', ['2026-03-12', 'Form Workout', 'Squat', '', '100', 'lbs', '5', ''] in rows, rows)
    check("a name that looks like a formula stays text", all(row[1] != '=SUM(A1) Push' for row in rows), rows)
    status, _, _ = request('GET', '/api/export')
    check('signed out, there is nothing to export', status == 401, status)

    print('A24 importing adds what is missing and never duplicates or overwrites')
    target = register('importer')
    t.api('POST', '/api/workouts', {'name': 'Already Mine', 'notes': '', 'exercises': [{'name': 'Curl', 'weight': 20, 'reps': 10}]}, target)
    status, _, result = import_file(export, target)
    check('an export imports into another account', status == 200 and result == {'workouts': 2, 'alreadyHere': 0, 'templates': 1, 'settings': True,
                                                                                  'program': True}, f'{status} {result}')
    mine = {w['name']: w for w in workouts_of(target)}
    check('its workouts arrive as they were, beside what was there',
          set(mine) == {'Already Mine', 'Form Workout', '=SUM(A1) Push'} and mine['=SUM(A1) Push']['exercises'] == finished['exercises']
          and mine['=SUM(A1) Push']['createdAt'] == finished['createdAt'], sorted(mine))
    imported_state = t.api('GET', '/api/state', token=target)[0]
    check('with the templates, program and settings', imported_state == {k: state[k] for k in ('settings', 'templates', 'program')}, imported_state)
    status, _, result = import_file(export, target)
    check('importing the same file again adds nothing', status == 200 and result == {'workouts': 0, 'alreadyHere': 2, 'templates': 0,
                                                                                     'settings': False, 'program': False}, f'{status} {result}')
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
        row = db.execute('SELECT expires_at FROM sessions WHERE token = ?', (token,)).fetchone()
        db.close()
        return row[0] if row else None

    def set_expires_at(token, when):
        db = sqlite3.connect(db_path)
        db.execute('UPDATE sessions SET expires_at = ? WHERE token = ?', (when, token))
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
        cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'password123'})[1]
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


def run_deletion(t, check, request):
    main = t.server
    json_headers = {'Content-Type': 'application/json'}

    def post(path, body, token=None):
        return request('POST', path, json.dumps(body).encode(), json_headers, token=token)

    def session_of(headers):
        cookie = headers.get('set-cookie', '')
        return cookie.split('session=')[1].split(';')[0] if 'session=' in cookie else None

    def register(name):
        return session_of(post('/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'password123'})[1])

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
    other_device = session_of(post('/api/auth/login', {'login': 'leaver', 'password': 'password123'})[1])
    main.api('POST', '/api/workouts', {'name': 'Mine', 'exercises': [t.ex('Squat', 100, 5, [(5, 100)])]}, leaver)
    main.api('PUT', '/api/state', {'settings': {'restDuration': 120}, 'templates': [], 'program': None}, leaver)
    main.api('POST', '/api/active-session', {'session': {'name': 'Going', 'exercises': [], 'currentIndex': 0}}, leaver)
    status, _, reply = post('/api/account/delete', {'password': 'wrong-password'}, leaver)
    check('a wrong password -> 403, and nothing is deleted', status == 403 and reply.get('error') and me(leaver) is not None
          and rows_of(leaver_id)['workouts'] == 1, f'{status} {reply}')
    check('signed out -> 401', post('/api/account/delete', {'password': 'password123'})[0] == 401)
    status, headers, reply = post('/api/account/delete', {'password': 'password123'}, leaver)
    check('the right password deletes it', status == 200, f'{status} {reply}')
    check('and clears the cookie', 'session=;' in headers.get('set-cookie', '') and 'Max-Age=0' in headers.get('set-cookie', ''), headers.get('set-cookie'))
    check('with every workout, setting, session and workout in progress', rows_of(leaver_id) == {'sessions': 0, 'workouts': 0, 'active_sessions': 0,
                                                                                                  'user_state': 0, 'users': 0}, rows_of(leaver_id))
    check('so no device is signed in to it any more', me(leaver) is None and me(other_device) is None)
    check('and it no longer signs in', post('/api/auth/login', {'login': 'leaver', 'password': 'password123'})[0] == 401)
    check('its username and email are free again', register('leaver') is not None)
    guesser = register('careful')
    guesses = [post('/api/account/delete', {'password': f'guess-{n}'}, guesser)[0] for n in range(5)]
    status = post('/api/account/delete', {'password': 'password123'}, guesser)[0]
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
