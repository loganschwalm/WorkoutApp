import hashlib
import http.server
import json
import os
import secrets
import sqlite3
import threading
import time
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, urlparse

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
ROOT = os.environ.get('APP_ROOT', os.path.join(PROJECT_ROOT, 'frontend'))
DB_PATH = os.environ.get('WORKOUT_DB', os.path.join(PROJECT_ROOT, 'data', 'workouts.db'))
SESSION_TTL = 60 * 60 * 24 * 30
# Years of workouts are a few hundred kilobytes, so anything bigger than this is not the app talking.
MAX_BODY = 1024 * 1024

_client_id_ready = False
_client_id_lock = threading.Lock()


class BadRequest(Exception):
    """A request the client got wrong; answered with its status and message instead of a dropped connection."""

    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def migrate_client_ids(database):
    # Retried uploads are recognised by the clientId the app puts on each finished workout. Keeping it in its own
    # column under a unique index lets the database refuse a second copy, even when two uploads race each other.
    global _client_id_ready
    if _client_id_ready:
        return
    with _client_id_lock:
        if _client_id_ready:
            return
        columns = {row['name'] for row in database.execute('PRAGMA table_info(workouts)')}
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
        database.commit()
        _client_id_ready = True


def connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    database = sqlite3.connect(DB_PATH)
    database.row_factory = sqlite3.Row
    database.execute('PRAGMA foreign_keys = ON')
    database.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            payload TEXT NOT NULL,
            client_id TEXT
        );
        CREATE TABLE IF NOT EXISTS active_sessions (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            payload TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            settings_json TEXT NOT NULL DEFAULT '{}',
            templates_json TEXT NOT NULL DEFAULT '[]',
            updated_at INTEGER NOT NULL
        );
    ''')
    migrate_client_ids(database)
    return database


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
    return f'{salt}${digest}'


def password_matches(password, stored):
    try:
        salt, expected = stored.split('$', 1)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
        return secrets.compare_digest(actual, expected)
    except ValueError:
        return False


class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

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
        super().end_headers()

    def send_json(self, status, payload, cookies=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
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
        database = connection()
        row = database.execute('SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires_at > ?', (token.value, int(time.time()))).fetchone()
        database.close()
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
            self.send_json(HTTPStatus.OK, {'user': user})
            return
        user = self.require_user()
        if not user:
            return
        database = connection()
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
        database.close()

    def authenticate(self, create=False):
        data = self.read_json()
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        if len(username) < 3 or len(password) < 8:
            self.send_json(HTTPStatus.BAD_REQUEST, {'error': 'Username must be 3+ characters and password must be 8+ characters.'})
            return
        database = connection()
        row = database.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,)).fetchone()
        if create:
            if row:
                database.close()
                self.send_json(HTTPStatus.CONFLICT, {'error': 'That username is already registered.'})
                return
            database.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)', (username, password_hash(password), int(time.time() * 1000)))
            database.commit()
            row = database.execute('SELECT id, username FROM users WHERE username = ?', (username,)).fetchone()
        elif not row or not password_matches(password, row['password_hash']):
            database.close()
            self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid username or password.'})
            return
        token = secrets.token_urlsafe(32)
        database.execute('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)', (token, row['id'], int(time.time()) + SESSION_TTL))
        database.commit()
        database.close()
        cookie = f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}'
        self.send_json(HTTPStatus.OK, {'user': {'id': row['id'], 'username': row['username']}}, [cookie])

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
                database = connection()
                database.execute('DELETE FROM sessions WHERE token = ?', (token.value,))
                database.commit()
                database.close()
            self.send_json(HTTPStatus.OK, {'ok': True}, ['session=; Path=/; HttpOnly; Max-Age=0'])
            return
        user = self.require_user()
        if not user:
            return
        if path == '/api/workouts':
            data = self.read_json()
            now = int(time.time() * 1000)
            payload = dict(data)
            client_id = data.get('clientId') if isinstance(data.get('clientId'), str) and data.get('clientId') else None
            database = connection()
            # Clients retry uploads after network failures, so a repeated clientId must not create a second workout.
            # The unique index decides, so two retries arriving at the same moment cannot both get in.
            cursor = database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, client_id) DO NOTHING', (user['id'], data.get('name', 'Untitled workout'), data.get('notes', ''), data.get('createdAt', now), json.dumps(payload), client_id))
            database.commit()
            if cursor.rowcount:
                database.close()
                self.send_json(HTTPStatus.CREATED, {'id': cursor.lastrowid})
                return
            existing = database.execute('SELECT id FROM workouts WHERE user_id = ? AND client_id = ?', (user['id'], client_id)).fetchone()
            database.close()
            self.send_json(HTTPStatus.OK, {'id': existing['id']})
        elif path == '/api/active-session':
            data = self.read_json()
            database = connection()
            database.execute('INSERT INTO active_sessions (user_id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at', (user['id'], json.dumps(data.get('session')), int(time.time() * 1000)))
            database.commit()
            database.close()
            self.send_json(HTTPStatus.OK, {'ok': True})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def api_put(self, path):
        user = self.require_user()
        if not user:
            return
        if path.startswith('/api/workouts/'):
            workout_id = path.rsplit('/', 1)[-1]
            data = self.read_json()
            database = connection()
            database.execute('UPDATE workouts SET name=?, notes=?, created_at=?, payload=? WHERE id=? AND user_id=?', (data.get('name', 'Untitled workout'), data.get('notes', ''), data.get('createdAt', int(time.time() * 1000)), json.dumps(data), workout_id, user['id']))
            database.commit()
            database.close()
            self.send_json(HTTPStatus.OK, {'ok': True})
        elif path == '/api/state':
            data = self.read_json()
            database = connection()
            existing = database.execute('SELECT settings_json, templates_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
            settings = data.get('settings', json.loads(existing['settings_json']) if existing else {})
            templates = data.get('templates', json.loads(existing['templates_json']) if existing else [])
            database.execute('INSERT INTO user_state (user_id, settings_json, templates_json, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, templates_json=excluded.templates_json, updated_at=excluded.updated_at', (user['id'], json.dumps(settings), json.dumps(templates), int(time.time() * 1000)))
            database.commit()
            database.close()
            self.send_json(HTTPStatus.OK, {'settings': settings, 'templates': templates})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def api_delete(self, path):
        user = self.require_user()
        if not user:
            return
        database = connection()
        if path.startswith('/api/workouts/'):
            database.execute('DELETE FROM workouts WHERE id=? AND user_id=?', (path.rsplit('/', 1)[-1], user['id']))
        elif path == '/api/active-session':
            database.execute('DELETE FROM active_sessions WHERE user_id=?', (user['id'],))
        else:
            database.close()
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})
            return
        database.commit()
        database.close()
        self.send_json(HTTPStatus.OK, {'ok': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = http.server.ThreadingHTTPServer(('0.0.0.0', port), AppHandler)
    print(f'Workout Tracker listening on http://0.0.0.0:{port}')
    server.serve_forever()
