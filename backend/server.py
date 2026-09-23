import contextlib
import hashlib
import http.server
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import quote, unquote, urlparse

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
ROOT = os.environ.get('APP_ROOT', os.path.join(PROJECT_ROOT, 'frontend'))
DB_PATH = os.environ.get('WORKOUT_DB', os.path.join(PROJECT_ROOT, 'data', 'workouts.db'))
SESSION_TTL = 60 * 60 * 24 * 30
# Years of workouts are a few hundred kilobytes, so anything bigger than this is not the app talking.
MAX_BODY = 1024 * 1024


def env_flag(name, default):
    value = os.environ.get(name, '').strip().lower()
    return default if not value else value not in ('0', 'false', 'no', 'off')


# Set ALLOW_REGISTRATION=0 once your accounts exist, so nobody else who can reach the port can make one.
ALLOW_REGISTRATION = env_flag('ALLOW_REGISTRATION', True)
# The cookie is also marked Secure whenever a reverse proxy says the request arrived over HTTPS.
SECURE_COOKIES = env_flag('SECURE_COOKIES', False)
# After this many failed sign-ins for one username from one address, that pair waits until the oldest failure
# is LOGIN_WINDOW seconds old. Behind a reverse proxy every request shares the proxy's address.
LOGIN_ATTEMPTS = int(os.environ.get('LOGIN_ATTEMPTS', '5'))
LOGIN_WINDOW = int(os.environ.get('LOGIN_WINDOW', str(15 * 60)))

# OWASP's recommendation for PBKDF2-HMAC-SHA256. Hashes record their own count, so raising it later only
# needs this number changed: each account is rehashed the next time it signs in.
PBKDF2_ITERATIONS = 600_000
# Hashes written before the count was recorded ("salt$digest") used this many.
LEGACY_ITERATIONS = 120_000

SECURITY_HEADERS = {
    # Every script and stylesheet is a file served from here; nothing inline, nothing from elsewhere.
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                               "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
}

# How long a request waits for another request's write to finish before giving up, in seconds.
BUSY_TIMEOUT = 10


class BadRequest(Exception):
    """A request the client got wrong; answered with its status and message instead of a dropped connection."""

    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


# ---- Schema -------------------------------------------------------------------------------------------------
# Each migration moves the database up one version, and PRAGMA user_version records how many have run. Add new
# ones to the end and never change one that has shipped: databases in the wild have already run it.

def migration_1_tables(database):
    # IF NOT EXISTS: databases from before versioning already have these tables, at user_version 0.
    # One statement at a time: executescript would commit, ending the migration's transaction early.
    for statement in ('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )''', '''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        )''', '''
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            payload TEXT NOT NULL
        )''', '''
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            payload TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )''', '''
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            settings_json TEXT NOT NULL DEFAULT '{}',
            templates_json TEXT NOT NULL DEFAULT '[]',
            updated_at INTEGER NOT NULL
        )'''):
        database.execute(statement)


def migration_2_client_ids(database):
    # Retried uploads are recognised by the clientId the app puts on each finished workout. Keeping it in its own
    # column under a unique index lets the database refuse a second copy, even when two uploads race each other.
    # The column may already exist: the version before migrations were numbered added it the same way.
    columns = {row[1] for row in database.execute('PRAGMA table_info(workouts)')}
    if 'client_id' not in columns:
        database.execute('ALTER TABLE workouts ADD COLUMN client_id TEXT')
        # A race before this column existed may already have stored a workout twice. Only the first copy
        # keeps its clientId, so the unique index can be built; the other copy is left untouched.
        database.execute('''
            UPDATE workouts SET client_id = json_extract(payload, '$.clientId')
            WHERE json_type(payload, '$.clientId') = 'text' AND json_extract(payload, '$.clientId') != ''
              AND id = (SELECT MIN(other.id) FROM workouts AS other
                        WHERE other.user_id = workouts.user_id
                          AND json_type(other.payload, '$.clientId') = 'text'
                          AND json_extract(other.payload, '$.clientId') = json_extract(workouts.payload, '$.clientId'))
        ''')
    database.execute('CREATE UNIQUE INDEX IF NOT EXISTS workouts_user_client ON workouts(user_id, client_id)')


MIGRATIONS = [migration_1_tables, migration_2_client_ids]


def init_database():
    """Create or upgrade the database once, before the server accepts a request."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    database = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT, isolation_level=None)
    try:
        version = database.execute('PRAGMA user_version').fetchone()[0]
        if version > len(MIGRATIONS):
            raise SystemExit(f'{DB_PATH} is at schema version {version}, but this server only knows {len(MIGRATIONS)}. '
                             'It was written by a newer version of the app; update the app instead of downgrading.')
        # Write-ahead logging lets requests keep reading while another one writes. It is a property of the
        # file, so setting it once here covers every later connection.
        database.execute('PRAGMA journal_mode = WAL')
        for number in range(version + 1, len(MIGRATIONS) + 1):
            database.execute('BEGIN IMMEDIATE')
            try:
                MIGRATIONS[number - 1](database)
                database.execute(f'PRAGMA user_version = {number}')
                database.execute('COMMIT')
            except BaseException:
                database.execute('ROLLBACK')
                raise
            print(f'Database upgraded to schema version {number}.')
    finally:
        database.close()


@contextlib.contextmanager
def connection():
    """One request's database connection: committed if the block finishes, rolled back if it raises, always closed."""
    database = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT)
    database.row_factory = sqlite3.Row
    database.execute('PRAGMA foreign_keys = ON')
    try:
        yield database
        database.commit()
    except BaseException:
        database.rollback()
        raise
    finally:
        database.close()


# ---- Validation ---------------------------------------------------------------------------------------------
# Generous limits: nothing the app sends comes near them, but a stored value is always the shape the pages expect.

def text(value, field, limit, default=''):
    if value is None:
        return default
    if not isinstance(value, str):
        raise BadRequest(f'{field} must be text.')
    if len(value) > limit:
        raise BadRequest(f'{field} is longer than {limit} characters.')
    return value


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amount(value, field):
    """A weight or rep count: a number, or the text a number field produces ('' when left empty)."""
    if value is None or value == '' or (is_number(value) and value >= 0):
        return
    if isinstance(value, str) and len(value) <= 32:
        try:
            number = float(value)
        except ValueError:
            number = None
        if number is not None and math.isfinite(number) and number >= 0:
            return
    raise BadRequest(f'{field} must be a number of zero or more.')


def listed(value, field, limit):
    if not isinstance(value, list):
        raise BadRequest(f'{field} must be a list.')
    if len(value) > limit:
        raise BadRequest(f'{field} has more than {limit} entries.')
    for item in value:
        if not isinstance(item, dict):
            raise BadRequest(f'Every entry in {field} must be an object.')
    return value


def validate_exercises(exercises, field='exercises'):
    for index, exercise in enumerate(listed(exercises, field, 1000)):
        where = f'{field}[{index}]'
        text(exercise.get('name'), f'{where}.name', 1000)
        amount(exercise.get('weight'), f'{where}.weight')
        amount(exercise.get('reps'), f'{where}.reps')
        if exercise.get('sets') is not None:
            for number, logged in enumerate(listed(exercise['sets'], f'{where}.sets', 1000)):
                amount(logged.get('weight'), f'{where}.sets[{number}].weight')
                amount(logged.get('reps'), f'{where}.sets[{number}].reps')


def validate_workout(data):
    """(name, notes, created_at) for storing, after checking the whole workout is a shape the pages can show."""
    name = text(data.get('name', 'Untitled workout'), 'name', 1000)
    notes = text(data.get('notes'), 'notes', 100_000)
    created_at = data.get('createdAt', int(time.time() * 1000))
    if not is_number(created_at) or not 0 <= created_at < 10 ** 14:
        raise BadRequest('createdAt must be a time in milliseconds.')
    validate_exercises(data.get('exercises'))
    if data.get('clientId') is not None:
        text(data['clientId'], 'clientId', 200)
    return name, notes, int(created_at)


def validate_state(data):
    if 'settings' in data and not isinstance(data['settings'], dict):
        raise BadRequest('settings must be an object.')
    if 'templates' in data:
        for index, template in enumerate(listed(data['templates'], 'templates', 1000)):
            text(template.get('name'), f'templates[{index}].name', 1000)
            validate_exercises(template.get('exercises'), f'templates[{index}].exercises')


def workout_id(path):
    """The id in /api/workouts/<id>, or None if it is not a plain number (answered as not found)."""
    tail = path[len('/api/workouts/'):]
    return int(tail) if tail.isdigit() and len(tail) < 19 else None


def derive(password, salt, iterations):
    # surrogatepass: JSON can carry a lone surrogate, which strict UTF-8 refuses; valid text encodes as before.
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8', 'surrogatepass'), salt.encode(), iterations).hex()


def password_hash(password, salt=None, iterations=PBKDF2_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    return f'pbkdf2_sha256${iterations}${salt}${derive(password, salt, iterations)}'


def parse_hash(stored):
    """(iterations, salt, digest) from either hash format; ValueError if it is neither."""
    parts = stored.split('$')
    if len(parts) == 4 and parts[0] == 'pbkdf2_sha256':
        return int(parts[1]), parts[2], parts[3]
    if len(parts) == 2:
        return LEGACY_ITERATIONS, parts[0], parts[1]
    raise ValueError('unrecognised password hash')


def password_matches(password, stored):
    try:
        iterations, salt, expected = parse_hash(stored)
    except ValueError:
        return False
    return secrets.compare_digest(derive(password, salt, iterations), expected)


def needs_rehash(stored):
    try:
        return parse_hash(stored)[0] < PBKDF2_ITERATIONS
    except ValueError:
        return True


# Checked against when the username does not exist, so a wrong username takes as long as a wrong password.
DUMMY_HASH = password_hash(secrets.token_hex(16))


class LoginThrottle:
    """Failed sign-ins per (client address, username), forgotten LOGIN_WINDOW seconds after they happen."""

    def __init__(self, attempts, window):
        self.attempts = attempts
        self.window = window
        self.failures = {}
        self.lock = threading.Lock()

    def retry_after(self, key):
        """Seconds until this key may try again; 0 if it may try now."""
        now = time.monotonic()
        with self.lock:
            recent = [moment for moment in self.failures.get(key, []) if now - moment < self.window]
            if recent:
                self.failures[key] = recent
            else:
                self.failures.pop(key, None)
            if len(recent) < self.attempts:
                return 0
            return max(1, int(self.window - (now - recent[0])) + 1)

    def failed(self, key):
        now = time.monotonic()
        with self.lock:
            if len(self.failures) > 10000:  # someone cycling through usernames; drop what has expired
                self.failures = {k: v for k, v in self.failures.items() if now - v[-1] < self.window}
            self.failures.setdefault(key, []).append(now)

    def succeeded(self, key):
        with self.lock:
            self.failures.pop(key, None)


login_throttle = LoginThrottle(LOGIN_ATTEMPTS, LOGIN_WINDOW)


class AppHandler(http.server.SimpleHTTPRequestHandler):
    # With nosniff the browser trusts these types exactly, so they must not depend on the host's mime database
    # (Windows can map .js to text/plain from the registry, and a minimal container may have no database at all).
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.html': 'text/html; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.json': 'application/json',
        '.webmanifest': 'application/manifest+json',
        '.png': 'image/png',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def list_directory(self, path):
        # Directories are not browsable; only the files the pages reference are served.
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def send_head(self):
        # A path beginning // or containing a backslash can come back in the Location of the standard library's
        # directory redirect, which browsers read as a link to another site. The app never uses either.
        if self.path.startswith('//') or '\\' in unquote(urlparse(self.path).path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return super().send_head()

    def send_response(self, *args, **kwargs):
        self.cache_control_sent = False
        super().send_response(*args, **kwargs)

    def send_header(self, keyword, value):
        if keyword.lower() == 'cache-control':
            self.cache_control_sent = True
        super().send_header(keyword, value)

    def end_headers(self):
        # Static files otherwise go out with only Last-Modified, and a browser is then
        # free to guess how long they stay fresh. It guesses badly: a signed-out visit
        # can be answered from the cache with the signed-in page instead of the login
        # redirect, and an upgraded server keeps serving old JavaScript to a browser
        # that never asks again. Revalidating every time costs a 304 and avoids both.
        if not getattr(self, 'cache_control_sent', False):
            self.send_header('Cache-Control', 'no-cache')
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def secure_cookies(self):
        forwarded = self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
        return SECURE_COOKIES or forwarded == 'https'

    def session_cookie(self, token, max_age):
        return f"session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}" + ('; Secure' if self.secure_cookies() else '')

    def send_json(self, status, payload, cookies=None, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if cookies:
            for cookie in cookies:
                self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            raise BadRequest('Invalid Content-Length header.')
        if length < 0:
            raise BadRequest('Invalid Content-Length header.')
        if length > MAX_BODY:
            # The body is left unread, so this connection cannot carry another request.
            self.close_connection = True
            raise BadRequest('Request body is too large.', HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:  # includes UnicodeDecodeError
            raise BadRequest('Request body must be valid JSON.')
        if not isinstance(data, dict):
            raise BadRequest('Request body must be a JSON object.')
        return data

    def handle_api(self, handler, path):
        try:
            handler(path)
        except BadRequest as error:
            self.send_json(error.status, {'error': str(error)})
        except Exception:
            # Without this the client sees a dropped connection and no reason; log the cause and say so instead.
            traceback.print_exc()
            self.close_connection = True
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': 'Internal server error.'})

    def session_user(self):
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        token = cookie.get('session')
        if not token:
            return None
        with connection() as database:
            row = database.execute('SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires_at > ?', (token.value, int(time.time()))).fetchone()
        return dict(row) if row else None

    def require_user(self):
        user = self.session_user()
        if not user:
            self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Authentication required.'})
        return user

    def redirect(self, status, location):
        self.send_response(status)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.handle_api(self.api_get, parsed.path)
            return
        if parsed.path == '/frontend' or parsed.path.startswith('/frontend/'):
            # Old links and installs used /frontend/…; sending them to the one real path keeps a single copy of
            # each page and script in the browser and service-worker caches. Leading slashes and backslashes are
            # collapsed so /frontend//evil.example cannot become a redirect to another site.
            target = '/' + parsed.path[len('/frontend'):].lstrip('/\\')
            self.redirect(HTTPStatus.MOVED_PERMANENTLY, target + (f'?{parsed.query}' if parsed.query else ''))
            return
        if parsed.path in ('/', '/index.html', '/progress.html', '/history.html') and not self.session_user():
            self.redirect(HTTPStatus.SEE_OTHER, '/login.html?next=' + quote(self.path, safe=''))
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.handle_api(self.api_post, parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.handle_api(self.api_put, parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.handle_api(self.api_delete, parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def api_get(self, path):
        if path == '/api/auth/me':
            user = self.session_user()
            self.send_json(HTTPStatus.OK, {'user': user, 'registrationOpen': ALLOW_REGISTRATION})
            return
        user = self.require_user()
        if not user:
            return
        with connection() as database:
            if path == '/api/workouts':
                rows = database.execute('SELECT id, name, notes, created_at, payload FROM workouts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)).fetchall()
                workouts = []
                for row in rows:
                    item = json.loads(row['payload'])
                    item.update(id=row['id'], name=row['name'], notes=row['notes'], createdAt=row['created_at'])
                    workouts.append(item)
                self.send_json(HTTPStatus.OK, {'workouts': workouts})
            elif path == '/api/active-session':
                row = database.execute('SELECT payload FROM active_sessions WHERE user_id = ?', (user['id'],)).fetchone()
                self.send_json(HTTPStatus.OK, {'session': json.loads(row['payload']) if row else None})
            elif path == '/api/state':
                row = database.execute('SELECT settings_json, templates_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
                self.send_json(HTTPStatus.OK, {'settings': json.loads(row['settings_json']) if row else {}, 'templates': json.loads(row['templates_json']) if row else []})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def authenticate(self, create=False):
        if create and not ALLOW_REGISTRATION:
            self.send_json(HTTPStatus.FORBIDDEN, {'error': 'New accounts are turned off on this server.'})
            return
        data = self.read_json()
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        if len(username) < 3 or len(password) < 8:
            self.send_json(HTTPStatus.BAD_REQUEST, {'error': 'Username must be 3+ characters and password must be 8+ characters.'})
            return
        throttle_key = (self.client_address[0], username.lower())
        if not create:
            wait = login_throttle.retry_after(throttle_key)
            if wait:
                # Refused before the password is even checked, so guessing cannot continue during the wait.
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {'error': f'Too many failed sign-ins. Try again in {(wait + 59) // 60} minute(s).'},
                               headers={'Retry-After': str(wait)})
                return
        with connection() as database:
            row = database.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,)).fetchone()
            if create:
                if row:
                    self.send_json(HTTPStatus.CONFLICT, {'error': 'That username is already registered.'})
                    return
                database.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)', (username, password_hash(password), int(time.time() * 1000)))
                row = database.execute('SELECT id, username FROM users WHERE username = ?', (username,)).fetchone()
            else:
                matches = password_matches(password, row['password_hash'] if row else DUMMY_HASH)
                if not row or not matches:
                    login_throttle.failed(throttle_key)
                    self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid username or password.'})
                    return
                login_throttle.succeeded(throttle_key)
                if needs_rehash(row['password_hash']):
                    # The password is only known now, so this is the moment to move an older hash to the current strength.
                    database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash(password), row['id']))
            now = int(time.time())
            token = secrets.token_urlsafe(32)
            database.execute('DELETE FROM sessions WHERE expires_at <= ?', (now,))
            database.execute('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)', (token, row['id'], now + SESSION_TTL))
        self.send_json(HTTPStatus.OK, {'user': {'id': row['id'], 'username': row['username']}}, [self.session_cookie(token, SESSION_TTL)])

    def api_post(self, path):
        if path == '/api/auth/register':
            self.authenticate(create=True)
            return
        if path == '/api/auth/login':
            self.authenticate()
            return
        if path == '/api/auth/logout':
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie.get('session')
            if token:
                with connection() as database:
                    database.execute('DELETE FROM sessions WHERE token = ?', (token.value,))
            self.send_json(HTTPStatus.OK, {'ok': True}, [self.session_cookie('', 0)])
            return
        user = self.require_user()
        if not user:
            return
        if path == '/api/workouts':
            data = self.read_json()
            name, notes, created_at = validate_workout(data)
            client_id = data.get('clientId') or None
            with connection() as database:
                # Clients retry uploads after network failures, so a repeated clientId must not create a second workout.
                # The unique index decides, so two retries arriving at the same moment cannot both get in.
                cursor = database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, client_id) DO NOTHING', (user['id'], name, notes, created_at, json.dumps(data), client_id))
                if cursor.rowcount:
                    status, stored_id = HTTPStatus.CREATED, cursor.lastrowid
                else:
                    status, stored_id = HTTPStatus.OK, database.execute('SELECT id FROM workouts WHERE user_id = ? AND client_id = ?', (user['id'], client_id)).fetchone()['id']
            self.send_json(status, {'id': stored_id})
        elif path == '/api/active-session':
            data = self.read_json()
            session = data.get('session')
            if session is not None and not isinstance(session, dict):
                raise BadRequest('session must be an object or null.')
            with connection() as database:
                database.execute('INSERT INTO active_sessions (user_id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at', (user['id'], json.dumps(session), int(time.time() * 1000)))
            self.send_json(HTTPStatus.OK, {'ok': True})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def api_put(self, path):
        user = self.require_user()
        if not user:
            return
        if path.startswith('/api/workouts/'):
            target = workout_id(path)
            data = self.read_json()
            name, notes, created_at = validate_workout(data)
            updated = 0
            if target is not None:
                with connection() as database:
                    updated = database.execute('UPDATE workouts SET name=?, notes=?, created_at=?, payload=? WHERE id=? AND user_id=?', (name, notes, created_at, json.dumps(data), target, user['id'])).rowcount
            if not updated:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Workout not found.'})
                return
            self.send_json(HTTPStatus.OK, {'ok': True})
        elif path == '/api/state':
            data = self.read_json()
            validate_state(data)
            with connection() as database:
                existing = database.execute('SELECT settings_json, templates_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
                settings = data.get('settings', json.loads(existing['settings_json']) if existing else {})
                templates = data.get('templates', json.loads(existing['templates_json']) if existing else [])
                database.execute('INSERT INTO user_state (user_id, settings_json, templates_json, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, templates_json=excluded.templates_json, updated_at=excluded.updated_at', (user['id'], json.dumps(settings), json.dumps(templates), int(time.time() * 1000)))
            self.send_json(HTTPStatus.OK, {'settings': settings, 'templates': templates})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def api_delete(self, path):
        user = self.require_user()
        if not user:
            return
        if path.startswith('/api/workouts/'):
            target = workout_id(path)
            if target is None:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Workout not found.'})
                return
            # Deleting a workout that is already gone (from another tab, say) still leaves what was asked for.
            with connection() as database:
                database.execute('DELETE FROM workouts WHERE id=? AND user_id=?', (target, user['id']))
        elif path == '/api/active-session':
            with connection() as database:
                database.execute('DELETE FROM active_sessions WHERE user_id=?', (user['id'],))
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})
            return
        self.send_json(HTTPStatus.OK, {'ok': True})


if __name__ == '__main__':
    init_database()
    port = int(os.environ.get('PORT', '6769'))
    server = http.server.ThreadingHTTPServer(('0.0.0.0', port), AppHandler)
    print(f'Workout Tracker listening on http://0.0.0.0:{port}')
    server.serve_forever()
