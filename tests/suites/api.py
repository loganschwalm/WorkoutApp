"""The HTTP API on its own, without a browser: bad input, racing uploads, redirects and database upgrades."""

import hashlib
import json
import sqlite3
import threading
import time

INTERCEPT = False
BROWSER = False

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
    _, cookie = api('POST', '/api/auth/register', {'username': 'racer', 'password': 'password123'})
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
    opener.api('POST', '/api/auth/register', {'username': 'owner', 'password': 'password123'})
    opener.stop()
    opener.process.wait(timeout=10)
    closed = t.start_server('closed.db', {'ALLOW_REGISTRATION': '0'})
    check('the server says registration is closed', closed.api('GET', '/api/auth/me')[0].get('registrationOpen') is False)
    status, _, reply = closed.request('POST', '/api/auth/register', json.dumps({'username': 'intruder', 'password': 'password123'}).encode(),
                                      {'Content-Type': 'application/json'})
    check('registering is refused with 403', status == 403 and 'turned off' in reply.get('error', ''), f'{status} {reply}')
    check('and no account was created', stored_hash('intruder', t.db_path('closed.db')) is None)
    status, headers, _ = login(closed, 'owner', 'password123')
    check('an existing account still signs in', status == 200 and 'session=' in headers.get('set-cookie', ''), status)

    # ------------------------------------------------------------------ A6 sign-in throttling
    print('A6  repeated failed sign-ins are slowed down')
    main.api('POST', '/api/auth/register', {'username': 'target', 'password': 'right-password'})
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
    # comfortably outlast five of them; the wait is then measured from the first failure.
    window = 8
    quick = t.start_server('quick.db', {'LOGIN_WINDOW': str(window)})
    quick.api('POST', '/api/auth/register', {'username': 'target', 'password': 'right-password'})
    first_failure = time.monotonic()
    for n in range(5):
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
    secure.api('POST', '/api/auth/register', {'username': 'someone', 'password': 'password123'})
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
        }
    finally:
        db.close()


def run_structure(t, check, request):
    main = t.server
    token = t.token
    json_headers = {'Content-Type': 'application/json'}
    tables = ['active_sessions', 'sessions', 'user_state', 'users', 'workouts']

    # ------------------------------------------------------------------ A12 schema at startup
    print('A12 the schema is created and versioned at startup, in WAL mode')
    t.start_server('fresh.db')  # the harness only asks /api/auth/me, which never opens the database
    schema = schema_of(t.db_path('fresh.db'))
    check('a new database has every table before any request touches it', schema['tables'] == tables, schema['tables'])
    check('it is at schema version 3', schema['version'] == 3, schema['version'])
    check('with the client_id column and its unique index',
          'client_id' in schema['columns'] and 'workouts_user_client' in schema['indexes'], schema)
    check('with a column for the training program', 'program_json' in schema['state_columns'], schema['state_columns'])
    check('in write-ahead-log mode', schema['journal'] == 'wal', schema['journal'])
    legacy = schema_of(t.db_path('legacy.db'))
    check('the database from before client_id (A3) is now at version 3 too', legacy['version'] == 3, legacy['version'])
    check('and has the training program column', 'program_json' in legacy['state_columns'], legacy['state_columns'])

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
          schema['version'] == 3 and schema['columns'].count('client_id') == 1 and kept == [('Kept', 'k1')], f'{schema} {kept}')

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
    _, cookie = t.api('POST', '/api/auth/register', {'username': 'neighbour', 'password': 'password123'})
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
