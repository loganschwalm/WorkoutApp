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
