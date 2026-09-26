import argparse
import contextlib
import csv
import datetime
import email.utils
import getpass
import gzip
import io
import hashlib
import http.server
import json
import math
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import traceback
from email.message import EmailMessage
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlparse

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
ROOT = os.environ.get('APP_ROOT', os.path.join(PROJECT_ROOT, 'frontend'))
DB_PATH = os.environ.get('WORKOUT_DB', os.path.join(PROJECT_ROOT, 'data', 'workouts.db'))
SESSION_TTL = 60 * 60 * 24 * 30
# A session in use is renewed to a full SESSION_TTL once this much of it has gone by.
SESSION_RENEW = 60 * 60 * 24
# Years of workouts are a few hundred kilobytes, so anything bigger than this is not the app talking.
MAX_BODY = 1024 * 1024
# An import carries a whole account at once: room for tens of thousands of workouts.
MAX_IMPORT = 32 * 1024 * 1024
# What an export file says it is, so an import can tell one from any other JSON.
EXPORT_FORMAT = 'workout-tracker-export'


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
# Seconds a connection may sit without sending anything before it is closed. Every connection holds a thread, so
# without this, anyone who can reach the port could open silent connections until the server ran out of room.
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '30'))

# Password reset codes are emailed through this SMTP server. With SMTP_HOST unset there is no reset by email: the
# sign-in page says to ask whoever runs the server, who resets it with the reset-password command.
SMTP_HOST = os.environ.get('SMTP_HOST', '').strip()
SMTP_SECURITY = os.environ.get('SMTP_SECURITY', '').strip().lower() or 'starttls'
SMTP_PORT = int(os.environ.get('SMTP_PORT', '').strip() or {'ssl': 465, 'none': 25}.get(SMTP_SECURITY, 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM = os.environ.get('SMTP_FROM', '').strip() or SMTP_USERNAME
SMTP_TIMEOUT = 20
# A code works for this long and this many tries, and each address is sent at most RESET_EMAILS codes an hour.
RESET_CODE_TTL = 15 * 60
RESET_CODE_ATTEMPTS = 5
RESET_EMAILS = 5

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

# Files gzipped for browsers that take it: text, which shrinks to about a quarter. Anything smaller than MIN_COMPRESS
# bytes goes as it is, since gzip's own overhead would eat most of the saving.
COMPRESSIBLE = ('.html', '.js', '.css', '.json', '.webmanifest', '.svg')
MIN_COMPRESS = 1024
# Each file gzipped once, until it changes on disk: {path: ((mtime, size), gzipped bytes)}.
gzipped_files = {}
gzipped_files_lock = threading.Lock()


def gzipped_file(path, stat):
    version = (stat.st_mtime_ns, stat.st_size)
    with gzipped_files_lock:
        cached = gzipped_files.get(path)
    if cached and cached[0] == version:
        return cached[1]
    with open(path, 'rb') as file:
        body = gzip.compress(file.read(), mtime=0)
    with gzipped_files_lock:
        gzipped_files[path] = (version, body)
    return body


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


def migration_3_programs(database):
    # The training program an account is following (Wendler 5/3/1), kept beside its settings and templates.
    database.execute("ALTER TABLE user_state ADD COLUMN program_json TEXT NOT NULL DEFAULT 'null'")


def migration_4_emails(database):
    # Accounts gain an email, to sign in with and to receive password reset codes. Existing accounts have none until
    # they add one in Settings. Stored lowercased, so the unique index also refuses the same address in another case.
    database.execute('ALTER TABLE users ADD COLUMN email TEXT')
    database.execute('CREATE UNIQUE INDEX users_email ON users(email)')
    # One code per account at a time: asking again replaces it.
    database.execute('''
        CREATE TABLE password_resets (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )''')


MIGRATIONS = [migration_1_tables, migration_2_client_ids, migration_3_programs, migration_4_emails]


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
        # The rest timer's seconds after each set, when the exercise has its own; and whether it is held for seconds.
        if exercise.get('rest') is not None and not (is_number(exercise['rest']) and 0 < exercise['rest'] <= 3600):
            raise BadRequest(f'{where}.rest must be a number of seconds, up to an hour.')
        if exercise.get('timed') is not None and not isinstance(exercise['timed'], bool):
            raise BadRequest(f'{where}.timed must be true or false.')
        if exercise.get('sets') is not None:
            for number, logged in enumerate(listed(exercise['sets'], f'{where}.sets', 1000)):
                amount(logged.get('weight'), f'{where}.sets[{number}].weight')
                amount(logged.get('reps'), f'{where}.sets[{number}].reps')


def weight_unit(value, field='unit'):
    """A record's weight unit: 'lbs' or 'kg', or missing (meaning lbs, for everything saved before kilograms)."""
    if value is not None and value not in ('lbs', 'kg'):
        raise BadRequest(f'{field} must be lbs or kg.')


def validate_workout(data):
    """(name, notes, created_at) for storing, after checking the whole workout is a shape the pages can show."""
    name = text(data.get('name', 'Untitled workout'), 'name', 1000)
    notes = text(data.get('notes'), 'notes', 100_000)
    created_at = data.get('createdAt', int(time.time() * 1000))
    if not is_number(created_at) or not 0 <= created_at < 10 ** 14:
        raise BadRequest('createdAt must be a time in milliseconds.')
    validate_exercises(data.get('exercises'))
    weight_unit(data.get('unit'))
    # How long the workout took, in seconds, when it was timed from start to finish.
    if data.get('duration') is not None and not (is_number(data['duration']) and 0 <= data['duration'] < 10 ** 9):
        raise BadRequest('duration must be a number of seconds.')
    if data.get('clientId') is not None:
        text(data['clientId'], 'clientId', 200)
    # A workout from a training program says where in the program it was, for History to show.
    if data.get('program') is not None:
        if not isinstance(data['program'], dict):
            raise BadRequest('program must be an object.')
        text(data['program'].get('name'), 'program.name', 1000)
        text(data['program'].get('label'), 'program.label', 1000)
    return name, notes, int(created_at)


def validate_program(program):
    """The program being followed: null, or an object naming its definition with a number for every training max."""
    if program is None:
        return
    if not isinstance(program, dict):
        raise BadRequest('program must be an object or null.')
    if not text(program.get('definition'), 'program.definition', 100):
        raise BadRequest('program.definition must name the program.')
    weight_unit(program.get('unit'), 'program.unit')
    maxes = program.get('trainingMaxes')
    if not isinstance(maxes, dict) or len(maxes) > 100:
        raise BadRequest('program.trainingMaxes must be an object.')
    if not all(is_number(value) and value >= 0 for value in maxes.values()):
        raise BadRequest('Every training max must be a number of zero or more.')
    for field in ('options', 'done', 'stalls'):
        if program.get(field) is not None and not isinstance(program[field], dict):
            raise BadRequest(f'program.{field} must be an object.')


def validate_state(data):
    if 'settings' in data and not isinstance(data['settings'], dict):
        raise BadRequest('settings must be an object.')
    if 'templates' in data:
        for index, template in enumerate(listed(data['templates'], 'templates', 1000)):
            text(template.get('name'), f'templates[{index}].name', 1000)
            validate_exercises(template.get('exercises'), f'templates[{index}].exercises')
    if 'program' in data:
        validate_program(data['program'])


def email_address(value):
    """The address lowercased, if it looks like one. Only its shape is checked; nothing is sent to confirm it."""
    email = text(value, 'email', 254).strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or not email.isprintable():
        raise BadRequest('Enter a valid email address.')
    return email


def workout_id(path):
    """The id in /api/workouts/<id>, or None if it is not a plain number (answered as not found)."""
    tail = path[len('/api/workouts/'):]
    return int(tail) if tail.isdigit() and len(tail) < 19 else None


# ---- Export and import --------------------------------------------------------------------------------------
# An export is the whole account in one JSON file: every workout, plus the templates, program and settings. Importing
# one only ever adds. Workouts already here (by clientId, or else by name, time and exercises) and templates already
# here are skipped, and settings and a program are only taken by an account that has none of its own.

def store_state(database, user_id, settings, templates, program):
    database.execute('INSERT INTO user_state (user_id, settings_json, templates_json, program_json, updated_at) VALUES (?, ?, ?, ?, ?) '
                     'ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, templates_json=excluded.templates_json, '
                     'program_json=excluded.program_json, updated_at=excluded.updated_at',
                     (user_id, json.dumps(settings), json.dumps(templates), json.dumps(program), int(time.time() * 1000)))


def delete_account_rows(database, user_id):
    """Everything an account has, then the account. The tables would cascade, but only with foreign keys on and on
    databases made since those references existed, so each is emptied by name."""
    for table in ('sessions', 'workouts', 'active_sessions', 'user_state', 'password_resets'):
        database.execute(f'DELETE FROM {table} WHERE user_id = ?', (user_id,))
    database.execute('DELETE FROM users WHERE id = ?', (user_id,))


def exported_workouts(database, user_id):
    """Every workout, oldest first, as the pages know them but without this server's ids."""
    workouts = []
    for row in database.execute('SELECT name, notes, created_at, payload FROM workouts WHERE user_id = ? ORDER BY created_at, id', (user_id,)):
        item = json.loads(row['payload'])
        item.pop('id', None)
        item.update(name=row['name'], notes=row['notes'], createdAt=row['created_at'])
        workouts.append(item)
    return workouts


def export_zone(query):
    """The time zone an export's dates are written in: the browser's, which sends ?offset= in minutes east of UTC."""
    try:
        minutes = int(parse_qs(query).get('offset', ['0'])[0])
    except ValueError:
        minutes = 0
    return datetime.timezone(datetime.timedelta(minutes=max(-840, min(840, minutes))))


def local_date(milliseconds, zone):
    # Added on rather than fromtimestamp(), which some platforms refuse for dates far in the future.
    moment = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(milliseconds=milliseconds)
    return moment.astimezone(zone).strftime('%Y-%m-%d')


def spreadsheet_text(value):
    """Text a spreadsheet keeps as text. One starting like a formula (=, +, -, @) would otherwise be run as one."""
    value = str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def workouts_csv(workouts, zone):
    """One row per logged set, oldest first, for a spreadsheet. A skipped exercise has no rows, and one saved without
    sets (from the workout form) has one row of its weight and reps. A timed exercise's count goes under Seconds."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Date', 'Workout', 'Exercise', 'Set', 'Weight', 'Unit', 'Reps', 'Seconds'])
    for workout in workouts:
        date = local_date(workout['createdAt'], zone)
        unit = workout.get('unit') or 'lbs'
        for exercise in workout.get('exercises') or []:
            sets = exercise.get('sets')
            rows = [(index + 1, logged) for index, logged in enumerate(sets)] if sets is not None else [('', exercise)]
            timed = exercise.get('timed') is True
            for number, logged in rows:
                weight, count = logged.get('weight'), logged.get('reps')
                count = '' if count is None else count
                writer.writerow([date, spreadsheet_text(workout['name']), spreadsheet_text(exercise.get('name') or ''), number,
                                 '' if weight is None else weight, unit, '' if timed else count, count if timed else ''])
    # A byte-order mark, or Excel reads the file in its own code page and mangles anything beyond plain English.
    return '﻿' + out.getvalue()


def same_template(a, b):
    if a.get('id') and b.get('id'):
        return a['id'] == b['id']
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def workout_stored(database, user_id, name, created_at, workout):
    """Whether the account has a workout like this one, which has no clientId: the same name, time and exercises."""
    exercises = json.dumps(workout.get('exercises'), sort_keys=True)
    rows = database.execute('SELECT payload FROM workouts WHERE user_id = ? AND created_at = ? AND name = ?', (user_id, created_at, name))
    return any(json.dumps(json.loads(row['payload']).get('exercises'), sort_keys=True) == exercises for row in rows)


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


class Throttle:
    """Recent events per key (failed sign-ins, reset emails sent), forgotten `window` seconds after they happen."""

    def __init__(self, attempts, window):
        self.attempts = attempts
        self.window = window
        self.events = {}
        self.lock = threading.Lock()

    def retry_after(self, key):
        """Seconds until this key may try again; 0 if it may try now."""
        now = time.monotonic()
        with self.lock:
            recent = [moment for moment in self.events.get(key, []) if now - moment < self.window]
            if recent:
                self.events[key] = recent
            else:
                self.events.pop(key, None)
            if len(recent) < self.attempts:
                return 0
            return max(1, int(self.window - (now - recent[0])) + 1)

    def record(self, key):
        now = time.monotonic()
        with self.lock:
            if len(self.events) > 10000:  # someone cycling through usernames; drop what has expired
                self.events = {k: v for k, v in self.events.items() if now - v[-1] < self.window}
            self.events.setdefault(key, []).append(now)

    def clear(self, key):
        with self.lock:
            self.events.pop(key, None)


# Failed sign-ins per (client address, username).
login_throttle = Throttle(LOGIN_ATTEMPTS, LOGIN_WINDOW)
# Reset codes asked for per email address, whether or not an account uses it, so the limit never says which do.
reset_throttle = Throttle(RESET_EMAILS, 60 * 60)


def find_account(database, login):
    """The account signing in as `login`: an email in any case, or else a username exactly as registered."""
    columns = 'id, username, email, password_hash'
    if '@' in login:
        row = database.execute(f'SELECT {columns} FROM users WHERE email = ?', (login.lower(),)).fetchone()
        if row:
            return row
    # Usernames from before accounts had emails can contain @, so an address with no account behind it may be one.
    return database.execute(f'SELECT {columns} FROM users WHERE username = ?', (login,)).fetchone()


def public_user(row):
    """What the pages are told about an account."""
    return {'id': row['id'], 'username': row['username'], 'email': row['email']}


def reset_code_hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def check_mail_settings():
    if SMTP_SECURITY not in ('starttls', 'ssl', 'none'):
        raise SystemExit(f'SMTP_SECURITY must be starttls, ssl or none, not {SMTP_SECURITY!r}.')
    if SMTP_HOST and '@' not in SMTP_FROM:
        raise SystemExit('SMTP_HOST is set, so reset emails need a sender: set SMTP_FROM to the address they come from.')


def email_reset_code(email, username, code):
    """Send a password reset code. Runs on its own thread, so a slow mail server never holds up the reply."""
    message = EmailMessage()
    message['Subject'] = 'Your Workout Tracker password reset code'
    message['From'] = SMTP_FROM
    message['To'] = email
    message.set_content(
        f'Someone asked to reset the password of the Workout Tracker account "{username}".\n\n'
        f'Your code is {code}\n\n'
        f'Enter it on the sign-in page within {RESET_CODE_TTL // 60} minutes. It works once.\n\n'
        'If you did not ask for this, ignore this email. Your password has not changed.\n')
    try:
        if SMTP_SECURITY == 'ssl':
            client = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        with client:
            if SMTP_SECURITY == 'starttls':
                client.starttls(context=ssl.create_default_context())
            if SMTP_USERNAME:
                client.login(SMTP_USERNAME, SMTP_PASSWORD)
            client.send_message(message)
    except OSError as error:  # includes every smtplib error
        print(f'Could not email a password reset code to {email} through {SMTP_HOST}:{SMTP_PORT}: {error!r}', flush=True)
        return
    print(f'Emailed a password reset code to {email}.', flush=True)


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

    # Applied to every read and write on the connection (see REQUEST_TIMEOUT).
    timeout = REQUEST_TIMEOUT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_error(self, format, *args):
        # Browsers leave keep-alive connections idle, so closing one at the timeout is routine rather than an error.
        if not format.startswith('Request timed out'):
            super().log_error(format, *args)

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
        compressed = self.send_compressed_file()
        return super().send_head() if compressed is False else compressed

    def accepts_gzip(self):
        for part in self.headers.get('Accept-Encoding', '').split(','):
            name, _, params = part.partition(';')
            if name.strip().lower() in ('gzip', '*'):
                # gzip;q=0 is a browser saying it will not take gzip.
                return not re.fullmatch(r'\s*q\s*=\s*0(\.0*)?\s*', params)
        return False

    def encoded(self, body):
        """(body, headers) as sent: gzipped for a browser that takes that, when it is big enough to be worth it."""
        if len(body) < MIN_COMPRESS:
            return body, {}
        if not self.accepts_gzip():
            return body, {'Vary': 'Accept-Encoding'}
        return gzip.compress(body, mtime=0), {'Content-Encoding': 'gzip', 'Vary': 'Accept-Encoding'}

    def send_compressed_file(self):
        """Serve a page, script or stylesheet gzipped, for a browser that takes that. False leaves the file to the standard
        library, which serves it as it is: to a browser that does not, and for every other file, directory or error."""
        if not self.accepts_gzip():
            return False
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            if not urlparse(self.path).path.endswith('/'):
                return False  # the standard library redirects it to the path with a slash
            path = os.path.join(path, 'index.html')
        try:
            stat = os.stat(path)
        except OSError:
            return False
        if not path.endswith(COMPRESSIBLE) or not os.path.isfile(path) or stat.st_size < MIN_COMPRESS:
            return False
        # Unchanged since the browser's copy: the same 304 the standard library would answer.
        since = self.headers.get('If-Modified-Since')
        if since and not self.headers.get('If-None-Match'):
            try:
                when = email.utils.parsedate_to_datetime(since)
            except (TypeError, IndexError, OverflowError, ValueError):
                when = None
            if when is not None and when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            if when is not None and when.tzinfo is datetime.timezone.utc:
                modified = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).replace(microsecond=0)
                if modified <= when:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header('Vary', 'Accept-Encoding')
                    self.end_headers()
                    return None
        body = gzipped_file(path, stat)
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Last-Modified', self.date_time_string(stat.st_mtime))
        self.send_header('Content-Encoding', 'gzip')
        self.send_header('Vary', 'Accept-Encoding')
        self.end_headers()
        return io.BytesIO(body)

    def parse_request(self):
        # One handler answers every request on a keep-alive connection, so nothing is carried over from the last one.
        self.renewed_cookie = None
        return super().parse_request()

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
        # A session renewed while answering this request (see session_user) goes out on whatever the answer is.
        if getattr(self, 'renewed_cookie', None):
            self.send_header('Set-Cookie', self.renewed_cookie)
            self.renewed_cookie = None
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def secure_cookies(self):
        forwarded = self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
        return SECURE_COOKIES or forwarded == 'https'

    def session_cookie(self, token, max_age):
        return f"session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}" + ('; Secure' if self.secure_cookies() else '')

    def send_json(self, status, payload, cookies=None, headers=None):
        body, encoding = self.encoded(json.dumps(payload).encode())
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for name, value in {**encoding, **(headers or {})}.items():
            self.send_header(name, value)
        if cookies:
            for cookie in cookies:
                self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, limit=MAX_BODY):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            raise BadRequest('Invalid Content-Length header.')
        if length < 0:
            raise BadRequest('Invalid Content-Length header.')
        if length > limit:
            # The body is left unread, so this connection cannot carry another request.
            self.close_connection = True
            raise BadRequest('Request body is too large.', HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        # A page on another site can send a form or plain text without asking, but JSON only after a CORS check this
        # server never passes. Browsers that do not say where a request came from (see handle_api) are stopped here.
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self.close_connection = True
            raise BadRequest('Send the request body as JSON, with Content-Type: application/json.', HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:  # includes UnicodeDecodeError
            raise BadRequest('Request body must be valid JSON.')
        if not isinstance(data, dict):
            raise BadRequest('Request body must be a JSON object.')
        return data

    def handle_api(self, handler, path):
        try:
            # The session cookie is SameSite=Lax, which keeps it off requests from other sites, but not from other pages
            # on the same one: another port on this address, or another subdomain behind the same proxy. Browsers say
            # where a request came from, so a change asked for by any page but this site's own is refused.
            if self.command != 'GET' and self.headers.get('Sec-Fetch-Site', '').strip().lower() in ('same-site', 'cross-site'):
                raise BadRequest('Changes can only be made from this site.', HTTPStatus.FORBIDDEN)
            handler(path)
        except BadRequest as error:
            self.send_json(error.status, {'error': str(error)})
        except Exception:
            # Without this the client sees a dropped connection and no reason; log the cause and say so instead.
            traceback.print_exc()
            self.close_connection = True
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': 'Internal server error.'})

    def session_token(self):
        token = SimpleCookie(self.headers.get('Cookie', '')).get('session')
        return token.value if token else None

    def session_user(self):
        token = self.session_token()
        if not token:
            return None
        now = int(time.time())
        with connection() as database:
            row = database.execute('SELECT users.id, users.username, users.email, sessions.expires_at FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires_at > ?', (token, now)).fetchone()
            # A session lasts SESSION_TTL from when it was last used, not from signing in, so someone who trains every week
            # stays signed in. Renewed at most once a day, and the cookie with it, or the browser would drop it on time anyway.
            if row and row['expires_at'] < now + SESSION_TTL - SESSION_RENEW:
                database.execute('UPDATE sessions SET expires_at = ? WHERE token = ?', (now + SESSION_TTL, token))
                self.renewed_cookie = self.session_cookie(token, SESSION_TTL)
        return {key: row[key] for key in ('id', 'username', 'email')} if row else None

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
            self.send_json(HTTPStatus.OK, {'user': user, 'registrationOpen': ALLOW_REGISTRATION, 'passwordReset': bool(SMTP_HOST)})
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
                row = database.execute('SELECT settings_json, templates_json, program_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
                self.send_json(HTTPStatus.OK, {'settings': json.loads(row['settings_json']) if row else {}, 'templates': json.loads(row['templates_json']) if row else [],
                                               'program': json.loads(row['program_json']) if row else None})
            elif path in ('/api/export', '/api/export.csv'):
                self.export_account(database, user, as_csv=path.endswith('.csv'))
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def start_session(self, database, user_id):
        """Sign this account in: a new session, and the cookie that carries it."""
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        database.execute('DELETE FROM sessions WHERE expires_at <= ?', (now,))
        database.execute('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)', (token, user_id, now + SESSION_TTL))
        return self.session_cookie(token, SESSION_TTL)

    def send_wait(self, wait, message):
        self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {'error': f'{message} Try again in {(wait + 59) // 60} minute(s).'},
                       headers={'Retry-After': str(wait)})

    def register(self):
        if not ALLOW_REGISTRATION:
            self.send_json(HTTPStatus.FORBIDDEN, {'error': 'New accounts are turned off on this server.'})
            return
        data = self.read_json()
        email = email_address(data.get('email'))
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        if len(username) < 3:
            raise BadRequest('Username must be 3+ characters.')
        if '@' in username:
            # Signing in takes an email or a username in one field, and an @ is how the two are told apart.
            raise BadRequest('Username cannot contain @. Your email goes in its own field.')
        if len(password) < 8:
            raise BadRequest('Password must be 8+ characters.')
        stored_hash = password_hash(password)
        with connection() as database:
            if database.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone():
                raise BadRequest('That username is already registered.', HTTPStatus.CONFLICT)
            if database.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
                raise BadRequest('That email is already registered.', HTTPStatus.CONFLICT)
            user_id = database.execute('INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
                                       (username, email, stored_hash, int(time.time() * 1000))).lastrowid
            cookie = self.start_session(database, user_id)
        self.send_json(HTTPStatus.OK, {'user': {'id': user_id, 'username': username, 'email': email}}, [cookie])

    def sign_in(self):
        data = self.read_json()
        # An email or a username. Pages from before accounts had emails send it as `username`.
        login = str(data.get('login', data.get('username', ''))).strip()
        password = str(data.get('password', ''))
        if len(login) < 3 or len(password) < 8:
            raise BadRequest('Enter your email or username, and a password of 8+ characters.')
        with connection() as database:
            row = find_account(database, login)
            # Keyed by the account rather than what was typed, so its email and its username share one limit.
            throttle_key = (self.client_address[0], (row['username'] if row else login).lower())
            wait = login_throttle.retry_after(throttle_key)
            if wait:
                # Refused before the password is even checked, so guessing cannot continue during the wait.
                self.send_wait(wait, 'Too many failed sign-ins.')
                return
            matches = password_matches(password, row['password_hash'] if row else DUMMY_HASH)
            if not row or not matches:
                login_throttle.record(throttle_key)
                self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Wrong email, username or password.'})
                return
            login_throttle.clear(throttle_key)
            if needs_rehash(row['password_hash']):
                # The password is only known now, so this is the moment to move an older hash to the current strength.
                database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash(password), row['id']))
            cookie = self.start_session(database, row['id'])
        self.send_json(HTTPStatus.OK, {'user': public_user(row)}, [cookie])

    def send_reset_code(self):
        if not SMTP_HOST:
            raise BadRequest('Password reset by email is not set up on this server.', HTTPStatus.NOT_FOUND)
        email = email_address(self.read_json().get('email'))
        wait = reset_throttle.retry_after(email)
        if wait:
            self.send_wait(wait, 'Too many codes asked for.')
            return
        reset_throttle.record(email)
        code = f'{secrets.randbelow(10 ** 6):06d}'
        with connection() as database:
            user = database.execute('SELECT id, username FROM users WHERE email = ?', (email,)).fetchone()
            if user:
                now = int(time.time())
                database.execute('DELETE FROM password_resets WHERE expires_at <= ?', (now,))
                # Asking again replaces the code, and its tries start over.
                database.execute('INSERT INTO password_resets (user_id, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0) '
                                 'ON CONFLICT(user_id) DO UPDATE SET code_hash=excluded.code_hash, expires_at=excluded.expires_at, attempts=0',
                                 (user['id'], reset_code_hash(code), now + RESET_CODE_TTL))
        if user:
            # Sent off this thread, so the reply never waits on the mail server; a slow send would otherwise give away
            # that the address has an account, which the reply itself never says.
            threading.Thread(target=email_reset_code, args=(email, user['username'], code), daemon=True).start()
        self.send_json(HTTPStatus.OK, {'ok': True})

    def reset_password(self):
        data = self.read_json()
        email = email_address(data.get('email'))
        code = ''.join(text(data.get('code'), 'code', 100).split())
        password = str(data.get('password', ''))
        if not re.fullmatch('[0-9]{6}', code):
            raise BadRequest('Enter the 6-digit code from the email.')
        if len(password) < 8:
            raise BadRequest('Password must be 8+ characters.')
        stored_hash = password_hash(password)
        with connection() as database:
            user = database.execute('SELECT id, username, email FROM users WHERE email = ?', (email,)).fetchone()
            reset = None
            # The try is counted before the code is compared, and in the same write, so guesses sent at once cannot
            # share one. An address with no account, no code, or a used-up code all get the same answer.
            if user and database.execute('UPDATE password_resets SET attempts = attempts + 1 WHERE user_id = ? AND attempts < ? AND expires_at > ?',
                                         (user['id'], RESET_CODE_ATTEMPTS, int(time.time()))).rowcount:
                reset = database.execute('SELECT code_hash FROM password_resets WHERE user_id = ?', (user['id'],)).fetchone()
            accepted = reset is not None and secrets.compare_digest(reset_code_hash(code), reset['code_hash'])
            if accepted:
                database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user['id']))
                database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
                # Whoever knew the old password is signed out everywhere.
                database.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
                cookie = self.start_session(database, user['id'])
        # Raised only now, so the counted try is committed rather than rolled back with the refusal.
        if not accepted:
            raise BadRequest('That code is wrong or has expired. Check the newest email, or send a new code.')
        login_throttle.clear((self.client_address[0], user['username'].lower()))
        self.send_json(HTTPStatus.OK, {'user': public_user(user)}, [cookie])

    def change_email(self, user):
        data = self.read_json()
        email = email_address(data.get('email'))
        password = str(data.get('password', ''))
        # A signed-in page may not be its owner's, so the password is asked again, and wrong ones count as failed sign-ins.
        throttle_key = (self.client_address[0], user['username'].lower())
        wait = login_throttle.retry_after(throttle_key)
        if wait:
            self.send_wait(wait, 'Too many wrong passwords.')
            return
        with connection() as database:
            stored = database.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()['password_hash']
            if not password_matches(password, stored):
                login_throttle.record(throttle_key)
                # 403, not 401: the session is fine, and a 401 would tell the page it had expired.
                raise BadRequest('That password is not right.', HTTPStatus.FORBIDDEN)
            if database.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (email, user['id'])).fetchone():
                raise BadRequest('Another account already uses that email.', HTTPStatus.CONFLICT)
            database.execute('UPDATE users SET email = ? WHERE id = ?', (email, user['id']))
            # A code already sent went to the old address.
            database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'user': {**user, 'email': email}})

    def change_password(self, user):
        data = self.read_json()
        current = str(data.get('currentPassword', ''))
        new = str(data.get('newPassword', ''))
        if len(new) < 8:
            raise BadRequest('The new password must be 8+ characters.')
        # As with the email: the current password is asked again, and wrong ones count as failed sign-ins.
        throttle_key = (self.client_address[0], user['username'].lower())
        wait = login_throttle.retry_after(throttle_key)
        if wait:
            self.send_wait(wait, 'Too many wrong passwords.')
            return
        stored_hash = password_hash(new)
        with connection() as database:
            stored = database.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()['password_hash']
            if not password_matches(current, stored):
                login_throttle.record(throttle_key)
                # 403, not 401: the session is fine, and a 401 would tell the page it had expired.
                raise BadRequest('Your current password is not right.', HTTPStatus.FORBIDDEN)
            database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user['id']))
            # Whoever knew the old password is signed out everywhere but here, and a reset code sent for it stops working.
            signed_out = database.execute('DELETE FROM sessions WHERE user_id = ? AND token != ?', (user['id'], self.session_token())).rowcount
            database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'signedOut': signed_out})

    def delete_account(self, user):
        password = str(self.read_json().get('password', ''))
        # As with the email and password: asked again, and wrong ones count as failed sign-ins.
        throttle_key = (self.client_address[0], user['username'].lower())
        wait = login_throttle.retry_after(throttle_key)
        if wait:
            self.send_wait(wait, 'Too many wrong passwords.')
            return
        with connection() as database:
            stored = database.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()['password_hash']
            if not password_matches(password, stored):
                login_throttle.record(throttle_key)
                raise BadRequest('That password is not right.', HTTPStatus.FORBIDDEN)
            delete_account_rows(database, user['id'])
        print(f"Deleted the account {user['username']} at its owner's request.", flush=True)
        self.send_json(HTTPStatus.OK, {'ok': True}, [self.session_cookie('', 0)])

    def send_download(self, text, content_type, filename):
        """A file for the browser to save rather than show."""
        body, encoding = self.encoded(text.encode())
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        for name, value in encoding.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def export_account(self, database, user, as_csv):
        zone = export_zone(urlparse(self.path).query)
        today = datetime.datetime.now(zone).strftime('%Y-%m-%d')
        workouts = exported_workouts(database, user['id'])
        if as_csv:
            self.send_download(workouts_csv(workouts, zone), 'text/csv; charset=utf-8', f'workout-tracker-sets-{today}.csv')
            return
        row = database.execute('SELECT settings_json, templates_json, program_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
        export = {'format': EXPORT_FORMAT, 'version': 1, 'exportedAt': int(time.time() * 1000),
                  'account': {'username': user['username'], 'email': user['email']}, 'workouts': workouts,
                  'templates': json.loads(row['templates_json']) if row else [],
                  'program': json.loads(row['program_json']) if row else None,
                  'settings': json.loads(row['settings_json']) if row else {}}
        self.send_download(json.dumps(export, indent=1), 'application/json; charset=utf-8', f'workout-tracker-{today}.json')

    def import_account(self, user):
        data = self.read_json(MAX_IMPORT)
        if data.get('format', EXPORT_FORMAT) != EXPORT_FORMAT or not isinstance(data.get('workouts'), list):
            raise BadRequest('That file is not a Workout Tracker export.')
        # Everything is checked before anything is stored, so a file with one bad workout imports nothing.
        prepared = []
        for index, workout in enumerate(listed(data['workouts'], 'workouts', 100_000)):
            # An id belongs to the server the workout came from; this one gives it its own.
            workout = {key: value for key, value in workout.items() if key != 'id'}
            try:
                prepared.append((workout, *validate_workout(workout)))
            except BadRequest as error:
                raise BadRequest(f'Workout {index + 1} in the file cannot be imported: {error}')
        state = {part: data[part] for part in ('settings', 'templates', 'program') if part in data}
        validate_state(state)
        added = 0
        with connection() as database:
            for workout, name, notes, created_at in prepared:
                client_id = workout.get('clientId') or None
                if client_id is None and workout_stored(database, user['id'], name, created_at, workout):
                    continue
                added += database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (?, ?, ?, ?, ?, ?) '
                                          'ON CONFLICT(user_id, client_id) DO NOTHING',
                                          (user['id'], name, notes, created_at, json.dumps(workout), client_id)).rowcount
            row = database.execute('SELECT settings_json, templates_json, program_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
            settings = json.loads(row['settings_json']) if row else {}
            templates = json.loads(row['templates_json']) if row else []
            program = json.loads(row['program_json']) if row else None
            take_settings = not settings and bool(state.get('settings'))
            take_program = program is None and state.get('program') is not None
            new_templates = []
            for template in state.get('templates') or []:
                if not any(same_template(template, have) for have in templates + new_templates):
                    new_templates.append(template)
            if len(templates) + len(new_templates) > 1000:
                raise BadRequest('Importing these templates would take the account past 1000.')
            if take_settings or take_program or new_templates:
                store_state(database, user['id'], state['settings'] if take_settings else settings, templates + new_templates,
                            state['program'] if take_program else program)
        self.send_json(HTTPStatus.OK, {'workouts': added, 'alreadyHere': len(prepared) - added, 'templates': len(new_templates),
                                       'settings': take_settings, 'program': take_program})

    def api_post(self, path):
        if path == '/api/auth/register':
            self.register()
            return
        if path == '/api/auth/login':
            self.sign_in()
            return
        if path == '/api/auth/forgot-password':
            self.send_reset_code()
            return
        if path == '/api/auth/reset-password':
            self.reset_password()
            return
        if path == '/api/auth/logout':
            token = self.session_token()
            if token:
                with connection() as database:
                    database.execute('DELETE FROM sessions WHERE token = ?', (token,))
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
            if session is not None:
                weight_unit(session.get('unit'), 'session.unit')
            with connection() as database:
                database.execute('INSERT INTO active_sessions (user_id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at', (user['id'], json.dumps(session), int(time.time() * 1000)))
            self.send_json(HTTPStatus.OK, {'ok': True})
        elif path == '/api/account/email':
            self.change_email(user)
        elif path == '/api/account/password':
            self.change_password(user)
        elif path == '/api/account/delete':
            self.delete_account(user)
        elif path == '/api/import':
            self.import_account(user)
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
                existing = database.execute('SELECT settings_json, templates_json, program_json FROM user_state WHERE user_id = ?', (user['id'],)).fetchone()
                settings = data.get('settings', json.loads(existing['settings_json']) if existing else {})
                templates = data.get('templates', json.loads(existing['templates_json']) if existing else [])
                # null is a real value here (the program was ended), so only a missing key keeps the stored one.
                program = data['program'] if 'program' in data else (json.loads(existing['program_json']) if existing else None)
                store_state(database, user['id'], settings, templates, program)
            self.send_json(HTTPStatus.OK, {'settings': settings, 'templates': templates, 'program': program})
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


class AppServer(http.server.ThreadingHTTPServer):
    # Connections waiting to be accepted. The standard library allows 5, but one page load asks for a dozen files at
    # once while the service worker fetches its whole cache list, and past the limit a connection is refused or reset:
    # the page then runs without one of its scripts. Five bursts of 80 requests lost 90 of 400 at the default.
    request_queue_size = 128


def serve():
    check_mail_settings()
    init_database()
    port = int(os.environ.get('PORT', '6769'))
    server = AppServer(('0.0.0.0', port), AppHandler)
    print(f'Workout Tracker listening on http://0.0.0.0:{port}')
    print(f'Password reset codes are emailed through {SMTP_HOST}:{SMTP_PORT} ({SMTP_SECURITY}).' if SMTP_HOST else
          'Password reset by email is off: set SMTP_HOST to turn it on, or reset passwords with the reset-password command.')
    server.serve_forever()


# ---- Account administration ---------------------------------------------------------------------------------
# `server.py users`, `server.py reset-password <account>` and `server.py set-email <account> <email>` manage accounts
# from the server's own command line, so a forgotten password can be reset without a mail server.

class AdminError(Exception):
    """A command that cannot be carried out; its message is printed and the command exits with status 1."""


def act_as_database_owner():
    """Run as root, switch to the user who owns the database (the service's user), so that the journal files SQLite
    creates beside it stay writable by the server. Anyone else stays who they are."""
    if not hasattr(os, 'getuid') or os.getuid() != 0:
        return
    owner = os.stat(DB_PATH)
    if owner.st_uid != 0:
        os.setgroups([])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)


def admin_account(database, login):
    row = find_account(database, login)
    if not row:
        raise AdminError(f'No account has the username or email {login!r}. `users` lists them.')
    return row


def read_new_password():
    """Asked twice, unseen, at a terminal; read from the first line of input otherwise, so it can be piped in."""
    if sys.stdin.isatty():
        password = getpass.getpass('New password: ')
        if getpass.getpass('Same again: ') != password:
            raise AdminError('The passwords did not match. Nothing was changed.')
    else:
        password = sys.stdin.readline().rstrip('\r\n')
    if len(password) < 8:
        raise AdminError('Password must be 8+ characters. Nothing was changed.')
    return password


def admin_users(args):
    with connection() as database:
        rows = database.execute('SELECT username, email FROM users ORDER BY username COLLATE NOCASE').fetchall()
    if not rows:
        print('No accounts yet.')
    width = max((len(row['username']) for row in rows), default=0)
    for row in rows:
        print(f"{row['username']:<{width}}  {row['email'] or '(no email)'}")


def admin_reset_password(args):
    with connection() as database:
        username = admin_account(database, args.account)['username']
    stored_hash = password_hash(read_new_password())
    with connection() as database:
        user_id = admin_account(database, username)['id']
        database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user_id))
        database.execute('DELETE FROM password_resets WHERE user_id = ?', (user_id,))
        database.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    print(f'Set a new password for {username}, and signed the account out everywhere.')
    # The sign-in limit lives in the running server's memory, which this command cannot reach.
    print(f'If failed sign-ins had made it wait, that wait still runs out on its own (up to {LOGIN_WINDOW // 60} minutes), '
          'or restart the server to end it now.')


def admin_set_email(args):
    try:
        email = email_address(args.email)
    except BadRequest as error:
        raise AdminError(f'{error} Nothing was changed.')
    with connection() as database:
        row = admin_account(database, args.account)
        if database.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (email, row['id'])).fetchone():
            raise AdminError(f'Another account already uses {email}. Nothing was changed.')
        database.execute('UPDATE users SET email = ? WHERE id = ?', (email, row['id']))
        # A code already sent went to the old address.
        database.execute('DELETE FROM password_resets WHERE user_id = ?', (row['id'],))
    print(f"Set the email of {row['username']} to {email}.")


def admin_delete_user(args):
    with connection() as database:
        row = admin_account(database, args.account)
        count = database.execute('SELECT COUNT(*) FROM workouts WHERE user_id = ?', (row['id'],)).fetchone()[0]
    username, workouts = row['username'], f"{count} workout{'' if count == 1 else 's'}"
    if not args.yes:
        # Nothing to undo it with, so it is asked for by name; without a terminal to ask at, --yes says it instead.
        if not sys.stdin.isatty():
            raise AdminError(f'Deleting {username} and their {workouts} cannot be undone. Add --yes to go ahead. Nothing was changed.')
        if input(f'This deletes {username} and their {workouts}, and cannot be undone. Type the username to go ahead: ').strip() != username:
            raise AdminError('That is not the username. Nothing was changed.')
    with connection() as database:
        delete_account_rows(database, admin_account(database, username)['id'])
    print(f'Deleted {username} and their {workouts}.')


def main(argv):
    parser = argparse.ArgumentParser(
        prog='server.py', description='Runs the Workout Tracker server. The commands manage its accounts instead, '
                                      'in the database WORKOUT_DB names, while the server keeps running.')
    commands = parser.add_subparsers(dest='command', metavar='command')
    commands.add_parser('users', help='list every account and its email')
    reset = commands.add_parser('reset-password', help='set a new password for an account, and sign it out everywhere')
    reset.add_argument('account', help='its username or email')
    email = commands.add_parser('set-email', help="add or change an account's email")
    email.add_argument('account', help='its username or current email')
    email.add_argument('email', help='the new email')
    delete = commands.add_parser('delete-user', help='delete an account and everything in it')
    delete.add_argument('account', help='its username or email')
    delete.add_argument('--yes', action='store_true', help='without asking to confirm, as a script needs')
    args = parser.parse_args(argv)
    if args.command is None:
        serve()
        return 0
    if not os.path.exists(DB_PATH):
        print(f'There is no database at {DB_PATH}. Set WORKOUT_DB to the one the server uses.', file=sys.stderr)
        return 1
    act_as_database_owner()
    init_database()
    try:
        {'users': admin_users, 'reset-password': admin_reset_password, 'set-email': admin_set_email,
         'delete-user': admin_delete_user}[args.command](args)
    except AdminError as error:
        print(error, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nStopped. Nothing was changed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
