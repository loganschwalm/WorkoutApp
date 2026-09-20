import hashlib
import http.server
import json
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
ROOT = os.environ.get('APP_ROOT', os.path.join(PROJECT_ROOT, 'frontend'))
DB_PATH = os.environ.get('WORKOUT_DB', os.path.join(PROJECT_ROOT, 'data', 'workouts.db'))
SESSION_TTL = 60 * 60 * 24 * 30


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
            payload TEXT NOT NULL
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
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length) or b'{}')

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

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.api_get(parsed.path)
            return
        public_path = parsed.path[9:] if parsed.path.startswith('/frontend/') else parsed.path
        if public_path in ('/', '/index.html', '/progress.html', '/history.html') and not self.session_user():
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Location', '/login.html')
            self.end_headers()
            return
        if parsed.path.startswith('/frontend/'):
            self.path = parsed._replace(path=public_path).geturl()
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.api_post(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.api_put(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.api_delete(parsed.path)
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
            database = connection()
            cursor = database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload) VALUES (?, ?, ?, ?, ?)', (user['id'], data.get('name', 'Untitled workout'), data.get('notes', ''), data.get('createdAt', now), json.dumps(payload)))
            database.commit()
            database.close()
            self.send_json(HTTPStatus.CREATED, {'id': cursor.lastrowid})
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
