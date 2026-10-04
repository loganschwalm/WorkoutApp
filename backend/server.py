import argparse
import base64
import collections
import concurrent.futures
import contextlib
import csv
import datetime
import email.utils
import getpass
import gzip
import io
import hashlib
import hmac
import http.server
import json
import math
import os
import re
import secrets
import signal
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from email.message import EmailMessage
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
ROOT = os.environ.get('APP_ROOT', os.path.join(PROJECT_ROOT, 'frontend'))
DB_PATH = os.environ.get('WORKOUT_DB', os.path.join(PROJECT_ROOT, 'data', 'workouts.db'))
SESSION_TTL = 60 * 60 * 24 * 30
# A session in use is renewed to a full SESSION_TTL once this much of it has gone by.
SESSION_RENEW = 60 * 60 * 24
# Signing in without "Remember me" gives a cookie the browser drops when it closes, and a session the server drops after
# half a day without use, so a copy of the cookie does not outlast the visit for long either. Renewed the same way.
SHORT_SESSION_TTL = 60 * 60 * 12
SHORT_SESSION_RENEW = 60 * 60
# Years of workouts are a few hundred kilobytes, so anything bigger than this is not the app talking.
MAX_BODY = 1024 * 1024
# An import carries a whole account at once: room for tens of thousands of workouts.
MAX_IMPORT = 32 * 1024 * 1024
# A change to the account state carries each changed part twice (as changed, and the copy it was changed from), and a
# lifetime of daily weigh-ins is a part on its own.
MAX_STATE_CHANGE = 4 * MAX_BODY
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
# Failed sign-ins from one address across every username before it waits the same way, so trying one common password
# against many usernames gets no further than many passwords against one. Not cleared by signing in, which an account of
# one's own could otherwise do between guesses. Behind a reverse proxy every request shares the proxy's address, and one
# person's guessing would make everyone wait: 0 turns it off.
LOGIN_ADDRESS_ATTEMPTS = int(os.environ.get('LOGIN_ADDRESS_ATTEMPTS', '20'))
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
# Wrong codes per address, counted across every code sent to it: after RESET_GUESSES in a day, no code for that address
# is even compared until the oldest wrong one is a day old. Without this, asking for a new code started the tries over,
# which allowed 25 guesses an hour. With it, a six-digit code holds out against guessing for centuries.
RESET_GUESSES = int(os.environ.get('RESET_GUESSES', '10'))

# OWASP's recommendation for PBKDF2-HMAC-SHA256. Hashes record their own count, so raising it later only
# needs this number changed: each account is rehashed the next time it signs in.
PBKDF2_ITERATIONS = 600_000
# Hashes written before the count was recorded ("salt$digest") used this many.
LEGACY_ITERATIONS = 120_000
# Hashing a password is the one thing a request can make costly without signing in: a good part of a second of a core
# each time. At most PASSWORD_HASHERS run at once, so a flood of sign-ins, sign-ups or resets can take those cores and no
# more, and signed-in pages stay quick. A request that gets no turn within PASSWORD_HASH_WAIT seconds is told to try again.
PASSWORD_HASHERS = max(1, int(os.environ.get('PASSWORD_HASHERS', '2')))
PASSWORD_HASH_WAIT = float(os.environ.get('PASSWORD_HASH_WAIT', '5'))

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
# Video, which Safari only plays from a server that answers a Range request with just those bytes (206).
RANGED = ('.mp4',)
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

    def __init__(self, message, status=HTTPStatus.BAD_REQUEST, headers=None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


# ---- Schema -------------------------------------------------------------------------------------------------
# Each migration moves the database up one version, and PRAGMA user_version records how many have run. Add new
# ones to the end and never change one that has shipped: databases in the wild have already run it.

def session_hash(token):
    """What the sessions table keeps of a session's token. A token is 32 random bytes, so a plain SHA-256 is enough: there
    is nothing to guess, only a copy of the database to make useless."""
    return hashlib.sha256(token.encode()).hexdigest()


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


def migration_5_exercise_notes(database):
    # Notes that stay with an exercise from one workout to the next ("seat on 4"), keyed by the exercise's name as
    # exerciseKey writes it, kept beside the settings, templates and program.
    database.execute("ALTER TABLE user_state ADD COLUMN notes_json TEXT NOT NULL DEFAULT '{}'")


def migration_6_hashed_sessions(database):
    # Sessions are kept as a SHA-256 of their token rather than the token itself, so a copy of the database (a backup,
    # say) cannot be used to sign in. The column keeps its name. Each session is rehashed where it stands, so nobody is
    # signed out by the upgrade.
    for (token,) in database.execute('SELECT token FROM sessions').fetchall():
        database.execute('UPDATE sessions SET token = ? WHERE token = ?', (session_hash(token), token))


def migration_7_goals(database):
    # A weight to reach in an exercise, by exerciseKey, kept beside the settings, templates, program and notes.
    database.execute("ALTER TABLE user_state ADD COLUMN goals_json TEXT NOT NULL DEFAULT '{}'")


def migration_8_bodyweight(database):
    # Bodyweight logged by day ({'2026-09-29': {'weight': 181.4, 'unit': 'lbs'}}), kept beside the goals.
    database.execute("ALTER TABLE user_state ADD COLUMN bodyweight_json TEXT NOT NULL DEFAULT '{}'")


def migration_9_remembered_sessions(database):
    # Whether a session was started with "Remember me", which decides how long it lasts (SESSION_TTL or SHORT_SESSION_TTL)
    # and whether its cookie outlives the browser. Every session from before had a cookie that did, so it counts as remembered.
    database.execute('ALTER TABLE sessions ADD COLUMN remember INTEGER NOT NULL DEFAULT 1')


def migration_10_exercise_library(database):
    # What each exercise works and is done with ({'bench press': {'name': 'Bench Press', 'muscle': 'chest', 'equipment':
    # 'barbell'}}), by exerciseKey: exercises of the account's own, and its choices for ones the app would otherwise guess.
    database.execute("ALTER TABLE user_state ADD COLUMN library_json TEXT NOT NULL DEFAULT '{}'")


def migration_11_push(database):
    # Phones that have allowed reminders: the address of the browser's push service to post to, the keys to encrypt for
    # it, the phone's own clock (its time zone, and its offset from UTC for a server that does not know that zone) and the
    # day it was last reminded, by that clock.
    database.execute('''
        CREATE TABLE push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            tz TEXT NOT NULL DEFAULT '',
            offset_minutes INTEGER NOT NULL DEFAULT 0,
            last_sent TEXT,
            created_at INTEGER NOT NULL
        )''')
    database.execute('CREATE INDEX push_subscriptions_user ON push_subscriptions(user_id)')
    # Keys the server makes for itself: the one that signs its push messages (see vapid_key).
    database.execute('CREATE TABLE server_keys (name TEXT PRIMARY KEY, value TEXT NOT NULL)')


def migration_12_workout_cache(database):
    # Two things for reading an account's workouts, which every page does on every load. An index in the order they are read.
    # And a tag per account that changes whenever one of its workouts is added, changed or deleted, which is the ETag of
    # GET /api/workouts, so a page that already has the history is told it is current instead of being sent it again
    # (workout_tag). The triggers keep it, so no way of writing a workout can forget to: an upload, an edit, a delete,
    # an import. The tag is random each time rather than a count, so a database restored from a backup cannot give a tag
    # that a browser has seen before for different workouts.
    database.execute('CREATE INDEX workouts_user_created ON workouts(user_id, created_at)')
    database.execute('CREATE TABLE workout_versions (user_id INTEGER PRIMARY KEY, tag TEXT NOT NULL)')
    for name, event, row in (('inserted', 'INSERT', 'NEW'), ('updated', 'UPDATE', 'NEW'), ('deleted', 'DELETE', 'OLD')):
        database.execute(f'''
            CREATE TRIGGER workouts_{name} AFTER {event} ON workouts
            BEGIN
                INSERT INTO workout_versions (user_id, tag) VALUES ({row}.user_id, lower(hex(randomblob(8))))
                ON CONFLICT(user_id) DO UPDATE SET tag = excluded.tag;
            END''')


MIGRATIONS = [migration_1_tables, migration_2_client_ids, migration_3_programs, migration_4_emails, migration_5_exercise_notes,
              migration_6_hashed_sessions, migration_7_goals, migration_8_bodyweight, migration_9_remembered_sessions,
              migration_10_exercise_library, migration_11_push, migration_12_workout_cache]


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
        # Exercises next to each other with the same group are a superset.
        text(exercise.get('group'), f'{where}.group', 100)
        # A template exercise can plan its sets, 1 to 20, and a rep range up to repsMax; a workout started from it keeps them.
        if exercise.get('setCount') is not None and not (is_number(exercise['setCount']) and 1 <= exercise['setCount'] <= 20):
            raise BadRequest(f'{where}.setCount must be a number of sets from 1 to 20.')
        amount(exercise.get('repsMax'), f'{where}.repsMax')
        if exercise.get('sets') is not None:
            for number, logged in enumerate(listed(exercise['sets'], f'{where}.sets', 1000)):
                amount(logged.get('weight'), f'{where}.sets[{number}].weight')
                amount(logged.get('reps'), f'{where}.sets[{number}].reps')
                # How many more reps the set had in it, when that was recorded: 0 (none) to 10.
                if logged.get('rir') is not None and not (is_number(logged['rir']) and 0 <= logged['rir'] <= 10):
                    raise BadRequest(f'{where}.sets[{number}].rir must be a number from 0 to 10.')


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
    validate_cardio(data)
    return name, notes, int(created_at)


# The most a cardio session's numbers can be; nothing the app sends comes near them.
CARDIO_LIMITS = {'distance': 1_000_000, 'calories': 100_000, 'heartRate': 400, 'floors': 100_000}
# What a machine (or a treadmill) was set to, each optional, as cardioSettings in cardio-activities.js has them: (least,
# most). A treadmill's incline can go below zero.
CARDIO_SETTINGS = {'incline': (-10, 40), 'resistance': (0, 100), 'ramp': (0, 100), 'cadence': (0, 300), 'damper': (1, 10),
                   'strokeRate': (0, 100), 'level': (0, 100)}


def validate_cardio(data):
    """A cardio session (the Cardio page) is a workout with kind 'cardio', no exercises, its time as duration, and what it
    did as cardio: {activity, distance, distanceUnit, calories, heartRate, floors}, all but the activity optional."""
    kind = data.get('kind')
    if kind is None:
        return
    if kind != 'cardio':
        raise BadRequest('kind must be cardio, or left out for a strength workout.')
    cardio = data.get('cardio')
    if not isinstance(cardio, dict):
        raise BadRequest('cardio must be an object.')
    if not text(cardio.get('activity'), 'cardio.activity', 50).strip():
        raise BadRequest('cardio.activity must name the activity.')
    if not (is_number(data.get('duration')) and 0 < data['duration'] < 10 ** 6):
        raise BadRequest('A cardio session needs its time, as duration in seconds.')
    for field, most in CARDIO_LIMITS.items():
        value = cardio.get(field)
        if value is not None and not (is_number(value) and 0 <= value <= most):
            raise BadRequest(f'cardio.{field} must be a number from 0 to {most}.')
    if cardio.get('distanceUnit') not in (None, 'mi', 'km', 'm'):
        raise BadRequest('cardio.distanceUnit must be mi, km or m.')
    for field, (least, most) in CARDIO_SETTINGS.items():
        value = cardio.get(field)
        if value is not None and not (is_number(value) and least <= value <= most):
            raise BadRequest(f'cardio.{field} must be a number from {least} to {most}.')


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
    # A program the lifter built has a name and up to 7 days, each named and done from a template, by its id.
    text(program.get('name'), 'program.name', 200)
    if program.get('days') is not None:
        for index, day in enumerate(listed(program['days'], 'program.days', 7)):
            text(day.get('name'), f'program.days[{index}].name', 200)
            if not text(day.get('template'), f'program.days[{index}].template', 200):
                raise BadRequest(f'program.days[{index}].template must name the template the day does.')


# The muscle an exercise mostly works, and what it is done with, as exercise-library.js offers them.
MUSCLES = ('chest', 'back', 'shoulders', 'biceps', 'triceps', 'forearms', 'quads', 'hamstrings', 'glutes', 'calves', 'core', 'other')
EQUIPMENT = ('barbell', 'dumbbell', 'machine', 'cable', 'bodyweight', 'kettlebell', 'band', 'other')


# The time of day to remind at until one is chosen: the same as the page's default (settings-fields.js; tests/lint.py checks).
DEFAULT_REMINDER_TIME = '17:00'


def validate_schedule(schedule):
    """The days of the week the lifter trains, as the browser numbers them (Sunday is 0), and the time of day to remind them."""
    if not isinstance(schedule, dict):
        raise BadRequest('settings.schedule must be an object.')
    days = schedule.get('days', [])
    if (not isinstance(days, list) or not all(isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6 for day in days)
            or len(set(days)) != len(days)):
        raise BadRequest('settings.schedule.days must be a list of different days of the week, 0 (Sunday) to 6 (Saturday).')
    at = schedule.get('time', DEFAULT_REMINDER_TIME)
    if not (isinstance(at, str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', at)):
        raise BadRequest('settings.schedule.time must be a time of day as HH:MM.')


# How many of each an account may keep, for the validators below and for what an import may add.
MAX_TEMPLATES = 1000
MAX_NOTES = 5000
MAX_GOALS = 500
MAX_WEIGH_INS = 40_000
MAX_LIBRARY = 5000


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise BadRequest('settings must be an object.')
    if 'schedule' in settings:
        validate_schedule(settings['schedule'])


def validate_templates(templates):
    for index, template in enumerate(listed(templates, 'templates', MAX_TEMPLATES)):
        text(template.get('name'), f'templates[{index}].name', 1000)
        validate_exercises(template.get('exercises'), f'templates[{index}].exercises')


def keyed_collection(name, limit, things, check_entry, check_key=None):
    """The validator of a part that is an object of up to `limit` entries by key: the keys are checked by `check_key` (by
    default, as text) and each entry by `check_entry(key, entry)`, which raise BadRequest."""
    def validate(entries):
        if not isinstance(entries, dict) or len(entries) > limit:
            raise BadRequest(f'{name} must be an object of up to {limit} {things}.')
        for key, entry in entries.items():
            (check_key or (lambda key: text(key, f'{name} key', 1000)))(key)
            check_entry(key, entry)
    return validate


def check_note(key, note):
    text(note, f'exerciseNotes[{key!r}]', 2000)


def check_goal(key, goal):
    if not isinstance(goal, dict):
        raise BadRequest(f'goals[{key!r}] must be an object.')
    if not text(goal.get('name'), f'goals[{key!r}].name', 1000).strip():
        raise BadRequest(f'goals[{key!r}].name must name the exercise.')
    if not is_number(goal.get('target')) or not 0 < goal['target'] <= 100_000:
        raise BadRequest(f'goals[{key!r}].target must be a weight above zero.')
    weight_unit(goal.get('unit'), f'goals[{key!r}].unit')
    by = goal.get('by')
    if by not in (None, '') and not (isinstance(by, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', by)):
        raise BadRequest(f'goals[{key!r}].by must be a date as YYYY-MM-DD, or empty.')


def check_weigh_in_day(day):
    try:
        datetime.date.fromisoformat(day if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) else '')
    except ValueError:
        raise BadRequest(f'bodyweight key {day!r} must be a date as YYYY-MM-DD.')


def check_weigh_in(day, entry):
    if not isinstance(entry, dict) or not is_number(entry.get('weight')) or not 0 < entry['weight'] <= 2000:
        raise BadRequest(f'bodyweight[{day!r}].weight must be a weight above zero.')
    weight_unit(entry.get('unit'), f'bodyweight[{day!r}].unit')


def check_library_entry(key, entry):
    if not isinstance(entry, dict):
        raise BadRequest(f'exerciseLibrary[{key!r}] must be an object.')
    if not text(entry.get('name'), f'exerciseLibrary[{key!r}].name', 1000).strip():
        raise BadRequest(f'exerciseLibrary[{key!r}].name must name the exercise.')
    # Empty, or missing, leaves it to the app's guess from the name.
    if entry.get('muscle') not in (None, '', *MUSCLES):
        raise BadRequest(f'exerciseLibrary[{key!r}].muscle must be one of {", ".join(MUSCLES)}, or empty.')
    if entry.get('equipment') not in (None, '', *EQUIPMENT):
        raise BadRequest(f'exerciseLibrary[{key!r}].equipment must be one of {", ".join(EQUIPMENT)}, or empty.')


def validate_state(data):
    """Checks each part of the state that `data` has (see STATE_PARTS), in their order; a part it does not name is not looked at."""
    for name, part in STATE_PARTS.items():
        if name in data:
            part.validate(data[name])


# ---- Account details ----------------------------------------------------------------------------------------
# What a new username, email and password must be. account-rules.js checks the same in the browser first, so a
# mistake shows at once; these are the rules that count. Existing accounts keep what they have: an older, longer
# username still signs in, and so does a password set before these rules.

USERNAME_MAX = 32
PASSWORD_MAX = 128
# An address as mail servers take one: a local part of letters, digits and the usual symbols, in dot-separated runs,
# and a domain of dot-separated labels (letters, digits and inner hyphens) ending in a top-level domain of 2+ letters,
# or an internationalised one as it is sent (xn--). The local part is at most 64 characters, and the whole at most 254.
EMAIL_SHAPE = re.compile(r"([a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*)"
                         r'@((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59}))')
# The most used passwords long enough to pass the other rules, from published lists of leaked ones, in lowercase (the
# check is too). Whoever guesses passwords tries these first. Runs of keys (12345678, abcdefgh) are caught by rule.
COMMON_PASSWORDS = frozenset('''
    password password1 password12 password123 password1234 password12345 password! password1! passw0rd p@ssw0rd p@ssword
    passwort motdepasse contraseña 123456789 1234567890 12341234 12344321 11223344 1122334455 123123123 123321123
    987654321 123654789 147258369 741852963 159753456 147852369 12qwaszx 1q2w3e4r 1q2w3e4r5t 1q2w3e4r5t6y 1qaz2wsx
    1qazxsw2 zaq12wsx zaq1xsw2 q1w2e3r4 q1w2e3r4t5 qwerty123 qwerty12 qwerty1234 qwertyui qwertyuiop qwerty123456
    123456qwerty 123qweasd qweasdzxc qweasd123 1234qwer qwer1234 asdfghjkl asdf1234 1234asdf zxcvbnm1 zxcvbnm123
    abc12345 abcd1234 abcde12345 1234abcd aa123456 a1234567 a12345678 iloveyou iloveyou1 iloveyou2 iloveu123
    sunshine sunshine1 princess princess1 football football1 baseball baseball1 basketball soccer123 hockey123
    superman superman1 batman123 starwars starwars1 whatever whatever1 trustno1 letmein1 letmein123 welcome1
    welcome123 welcome2 admin123 admin1234 administrator changeme changeme1 changeme123 computer computer1 internet
    michael1 jennifer jessica1 michelle charlie1 jordan23 jordan123 liverpool chelsea1 arsenal1 manchester pokemon1
    pokemon123 naruto123 minecraft fortnite1 monkey123 dragon123 master123 shadow123 freedom1 lovely123 daniel123
    andrew123 matthew1 hunter123 harley123 ranger123 thomas123 robert123 secret123 summer123 summer2024 summer2025
    winter123 spring123 autumn123 samsung1 samsung123 google123 facebook1 linkedin mustang1 corvette ferrari1
    blink182 metallica gladiator elephant chocolate butterfly cookie123 cheese123 banana123 pepper123 ginger123
    buster123 tigger123 flower123 angel123 friends1 family123 blessed1 jesus123 hello123 hello1234 helloworld
    workout1 workout123 workouts fitness1 fitness123 gym12345 bodybuilding strength1 powerlifting deadlift squat123
    '''.split())


def new_username(value):
    """A username to register, checked: 3 to USERNAME_MAX characters, no @, and nothing invisible."""
    username = str(value or '').strip()
    if len(username) < 3:
        raise BadRequest('Username must be 3+ characters.')
    if len(username) > USERNAME_MAX:
        raise BadRequest(f'Username must be {USERNAME_MAX} characters or fewer.')
    if '@' in username:
        # Signing in takes an email or a username in one field, and an @ is how the two are told apart.
        raise BadRequest('Username cannot contain @. Your email goes in its own field.')
    if not username.isprintable():
        raise BadRequest('Username cannot contain invisible or control characters.')
    return username


def email_address(value, strict=True):
    """The address lowercased, if it is one. Only its form is checked; nothing is sent to confirm it. `strict=False`
    takes any address shaped like one, for finding an account whose email predates the rules (a reset code)."""
    email = text(value, 'email', 1000).strip().lower()
    if strict:
        shape = EMAIL_SHAPE.fullmatch(email) if len(email) <= 254 else None
        valid = bool(shape) and len(shape.group(1)) <= 64
    else:
        valid = len(email) <= 254 and bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)) and email.isprintable()
    if not valid:
        raise BadRequest('Enter a valid email address, like name@example.com.')
    return email


def password_problem(password, username='', email=''):
    """Why a new password will not do, or None. Long enough, not too long, and not easy to guess: varied, not a run of
    keys or a common password, and not the account's own name. No rules about capitals or symbols, which lead to
    Password1! more often than to strong passwords."""
    if len(password) < 8:
        return 'Password must be 8+ characters.'
    if len(password) > PASSWORD_MAX:
        return f'Password must be {PASSWORD_MAX} characters or fewer.'
    lowered = password.lower()
    if len(set(lowered)) < 5:
        return 'Use at least 5 different characters in your password.'
    steps = {ord(after) - ord(before) for before, after in zip(lowered, lowered[1:])}
    if lowered in COMMON_PASSWORDS or steps in ({1}, {-1}):
        return 'That password is too common and easy to guess. Choose another.'
    for name in (username.lower(), email.lower().split('@')[0]):
        if len(name) >= 3 and name in lowered:
            return 'Your password cannot contain your username or email.'
    return None


def new_password(password, username='', email=''):
    """The password, if it passes password_problem; a 400 saying why otherwise."""
    problem = password_problem(password, username, email)
    if problem:
        raise BadRequest(problem)
    return password


def workout_id(path):
    """The id in /api/workouts/<id>, or None if it is not a plain number (answered as not found)."""
    tail = path[len('/api/workouts/'):]
    return int(tail) if tail.isdigit() and len(tail) < 19 else None


# ---- Export and import --------------------------------------------------------------------------------------
# An export is the whole account in one JSON file: every workout, plus every part of its state (STATE_PARTS). Importing one only
# ever adds. Workouts already here (by clientId, or else by name, time and exercises) are skipped, and what a part adds is its
# `take`: templates not already here, an entry for a key that has none, and settings and a program only for an account that has
# none of its own.

# The account's state: what the pages keep and sync with the server, which is everything an account has but its workouts. One entry
# in STATE_PARTS says all the server needs to know about a part, so a new one is an entry here, a column (below), and its name
# in accountStateParts in frontend/offline.js, and not a change in each place that has to know the parts. (tests/lint.py checks
# that the server's list and the page's agree, and the api suite that every part has its column.) Each part has:
#   column    the column of user_state that keeps it, as JSON
#   empty     what the column holds for an account that has not set it, as JSON: also the column's DEFAULT
#   merge     how changes to it from several devices are merged (see merge_values)
#   validate  checks a value, raising BadRequest if it will not do
#   take      what an import does with it: from what the account has and what the file has, what the account has after (an
#             import only ever adds) and what that added, a count or whether the file's was taken
#   report    the name an import's answer gives that: templates, settings, program, notes, goals, bodyweights, exercises
StatePart = collections.namedtuple('StatePart', 'column empty merge validate take report')


def take_whole(have, incoming):
    """Import rule for a part that is one thing: the file's is taken only by an account that has none of its own."""
    return (incoming, True) if incoming and not have else (have, False)


def add_missing(noun, limit, unit='', wanted=lambda entry: True):
    """Import rule for a part that is entries by key: the file's for a key the account has none for; one already here is the
    account's own and stays."""
    def take(have, incoming):
        new = {key: entry for key, entry in (incoming or {}).items() if key not in have and wanted(entry)}
        if len(have) + len(new) > limit:
            raise BadRequest(f'Importing these {noun} would take the account past {limit}{unit}.')
        return {**have, **new}, len(new)
    return take


def add_new_templates(have, incoming):
    """Import rule for the templates: those the account has not already got (see same_template)."""
    new = []
    for template in incoming or []:
        if not any(same_template(template, kept) for kept in have + new):
            new.append(template)
    if len(have) + len(new) > MAX_TEMPLATES:
        raise BadRequest(f'Importing these templates would take the account past {MAX_TEMPLATES}.')
    return have + new, len(new)


STATE_PARTS = {
    'settings': StatePart('settings_json', '{}', {'depth': 1}, validate_settings, take_whole, 'settings'),
    'templates': StatePart('templates_json', '[]', {'depth': 1, 'by_id': True}, validate_templates, add_new_templates, 'templates'),
    'program': StatePart('program_json', 'null', {'depth': 2, 'identity': ('definition', 'startedAt', 'cycle', 'unit')}, validate_program, take_whole, 'program'),
    'exerciseNotes': StatePart('notes_json', '{}', {'depth': 1}, keyed_collection('exerciseNotes', MAX_NOTES, 'notes', check_note),
                               add_missing('notes', MAX_NOTES, wanted=bool), 'notes'),
    'goals': StatePart('goals_json', '{}', {'depth': 1}, keyed_collection('goals', MAX_GOALS, 'goals', check_goal), add_missing('goals', MAX_GOALS), 'goals'),
    # One weight a day, by the day it was weighed; a lifetime of daily weigh-ins fits.
    'bodyweight': StatePart('bodyweight_json', '{}', {'depth': 1}, keyed_collection('bodyweight', MAX_WEIGH_INS, 'days', check_weigh_in, check_weigh_in_day),
                            add_missing('bodyweights', MAX_WEIGH_INS, ' days'), 'bodyweights'),
    'exerciseLibrary': StatePart('library_json', '{}', {'depth': 1}, keyed_collection('exerciseLibrary', MAX_LIBRARY, 'exercises', check_library_entry),
                                 add_missing('exercises', MAX_LIBRARY), 'exercises'),
}


def load_state(database, user_id):
    columns = ', '.join(part.column for part in STATE_PARTS.values())
    row = database.execute(f'SELECT {columns} FROM user_state WHERE user_id = ?', (user_id,)).fetchone()
    return {name: json.loads(row[part.column] if row else part.empty) for name, part in STATE_PARTS.items()}


def store_state(database, user_id, state):
    columns = [part.column for part in STATE_PARTS.values()]
    database.execute(f"INSERT INTO user_state (user_id, {', '.join(columns)}, updated_at) VALUES (?, {', '.join('?' for _ in columns)}, ?) "
                     f"ON CONFLICT(user_id) DO UPDATE SET {', '.join(f'{column}=excluded.{column}' for column in columns)}, updated_at=excluded.updated_at",
                     (user_id, *(json.dumps(state[name]) for name in STATE_PARTS), int(time.time() * 1000)))


# ---- Merging changes from several devices ---------------------------------------------------------------------
# A device that changed part of the state sends the part as it changed it, and the copy it started from (PATCH
# /api/state). Another device may have changed the part on the server since; merging keeps both devices' changes, and
# where both changed the same thing, the change arriving now wins. How finely each part is merged is its `merge` in STATE_PARTS:
#   depth     how many levels of objects below the part are merged key by key; a value deeper than that is one value,
#             so a bodyweight's weight and unit, or a goal's target and unit, always travel together
#   by_id     a list of objects told apart by their id, merged as if keyed by it (templates)
#   identity  keys that say which run of a program the rest belongs to: its days are a cycle's, its weights a unit's,
#             so changes to two different runs are never mixed (see merge_values)
# A key one side has and the other does not.
MISSING = object()


def merge_values(bases, mine, theirs, depth, identity=()):
    """`mine` (this device's copy) merged with `theirs` (the server's). `bases` are the copies this device's change may
    have started from: the one the server last confirmed having, and any sent since whose answer never came back (the
    page closed, the connection dropped), which the server may have stored. What only one side changed is kept; where
    both changed the same thing, `mine` wins, as the later. A value is this device's change if it differs from any base,
    so a value changed and then changed back, before an answer that never came, still counts; and the server's is
    unchanged if it matches any. Objects are merged key by key `depth` levels down. Copies whose `identity` keys differ
    are different runs of a program, which are not mixed: the side that moved to another run wins whole."""
    if all(mine == base for base in bases):
        return theirs
    if mine == theirs or any(theirs == base for base in bases):
        return mine
    if depth <= 0 or not isinstance(mine, dict) or not isinstance(theirs, dict):
        return mine
    bases = [base if isinstance(base, dict) else {} for base in bases]
    if any(mine.get(key, MISSING) != theirs.get(key, MISSING) for key in identity):
        moved = any(mine.get(key, MISSING) != base.get(key, MISSING) for base in bases for key in identity)
        return mine if moved else theirs
    merged = {}
    # The server's order, then what this device added.
    for key in [*theirs, *(key for key in mine if key not in theirs)]:
        value = merge_values([base.get(key, MISSING) for base in bases], mine.get(key, MISSING), theirs.get(key, MISSING), depth - 1)
        if value is not MISSING:
            merged[key] = value
    return merged


def keyed_by_id(items):
    """A list of objects with distinct text ids as {id: object}, or None when it is not one."""
    if not isinstance(items, list):
        return None
    keyed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in keyed:
            return None
        keyed[item['id']] = item
    return keyed


def merge_part(part, bases, mine, theirs):
    spec = STATE_PARTS[part].merge
    if spec.get('by_id'):
        keyed = [keyed_by_id(value) for value in (*bases, mine, theirs)]
        # A list with an item that has no id (from before templates had them) cannot be told apart item by item.
        if None in keyed:
            return merge_values(bases, mine, theirs, 0)
        return list(merge_values(keyed[:-2], keyed[-2], keyed[-1], spec['depth']).values())
    return merge_values(bases, mine, theirs, spec['depth'], spec.get('identity', ()))


def delete_account_rows(database, user_id):
    """Everything an account has, then the account. The tables would cascade, but only with foreign keys on and on
    databases made since those references existed, so each is emptied by name."""
    for table in ('sessions', 'workouts', 'workout_versions', 'active_sessions', 'user_state', 'password_resets', 'push_subscriptions'):
        database.execute(f'DELETE FROM {table} WHERE user_id = ?', (user_id,))
    database.execute('DELETE FROM users WHERE id = ?', (user_id,))


def workout_tag(database, user_id):
    """The tag that changes with the account's workouts (see migration_12_workout_cache). An account with workouts from before
    the tags has none until now, and is given one."""
    row = database.execute('SELECT tag FROM workout_versions WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        database.execute('INSERT OR IGNORE INTO workout_versions (user_id, tag) VALUES (?, ?)', (user_id, secrets.token_hex(8)))
        row = database.execute('SELECT tag FROM workout_versions WHERE user_id = ?', (user_id,)).fetchone()
    return row['tag']


def etag_matches(header, etag):
    """Whether an If-None-Match header names this ETag (or anything: *). Compared weakly, as it is for a GET, so W/"x" is "x"."""
    if not header:
        return False
    plain = lambda tag: tag.strip().removeprefix('W/')
    return header.strip() == '*' or plain(etag) in {plain(tag) for tag in header.split(',')}


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
    sets (from the workout form) has one row of its weight and reps. A timed exercise's count goes under Seconds. A cardio
    session is one row: its time under Seconds, then its distance (in the unit it was entered in), calories, average heart
    rate and floors, then what the machine was set to, where it has them."""
    out = io.StringIO()
    writer = csv.writer(out)
    settings = {'incline': 'Incline (%)', 'resistance': 'Resistance level', 'ramp': 'Incline level', 'cadence': 'Cadence (rpm)', 'damper': 'Damper',
                'strokeRate': 'Stroke rate (spm)', 'level': 'Level'}
    writer.writerow(['Date', 'Workout', 'Exercise', 'Set', 'Weight', 'Unit', 'Reps', 'Seconds', 'Distance', 'Distance unit', 'Calories',
                     'Average heart rate', 'Floors', *settings.values()])
    for workout in workouts:
        date = local_date(workout['createdAt'], zone)
        unit = workout.get('unit') or 'lbs'
        if workout.get('kind') == 'cardio':
            cardio = workout.get('cardio') or {}
            given = lambda field: '' if cardio.get(field) is None else cardio[field]
            name = spreadsheet_text(workout['name'])
            writer.writerow([date, name, name, '', '', '', '', workout.get('duration', ''), given('distance'),
                             cardio.get('distanceUnit', '') if cardio.get('distance') is not None else '', given('calories'), given('heartRate'),
                             given('floors'), *(given(field) for field in settings)])
            continue
        for exercise in workout.get('exercises') or []:
            sets = exercise.get('sets')
            rows = [(index + 1, logged) for index, logged in enumerate(sets)] if sets is not None else [('', exercise)]
            timed = exercise.get('timed') is True
            for number, logged in rows:
                weight, count = logged.get('weight'), logged.get('reps')
                count = '' if count is None else count
                writer.writerow([date, spreadsheet_text(workout['name']), spreadsheet_text(exercise.get('name') or ''), number,
                                 '' if weight is None else weight, unit, '' if timed else count, count if timed else '', '', '', '', '', '',
                                 *('' for _ in settings)])
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


hashing_turns = threading.BoundedSemaphore(PASSWORD_HASHERS)


def derive(password, salt, iterations):
    if not hashing_turns.acquire(timeout=PASSWORD_HASH_WAIT):
        raise BadRequest('The server is busy. Try again in a moment.', HTTPStatus.SERVICE_UNAVAILABLE,
                         {'Retry-After': str(max(1, math.ceil(PASSWORD_HASH_WAIT)))})
    try:
        # surrogatepass: JSON can carry a lone surrogate, which strict UTF-8 refuses; valid text encodes as before.
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8', 'surrogatepass'), salt.encode(), iterations).hex()
    finally:
        hashing_turns.release()


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
# Failed sign-ins per client address, whatever the username (LOGIN_ADDRESS_ATTEMPTS; off at 0).
address_throttle = Throttle(LOGIN_ADDRESS_ATTEMPTS, LOGIN_WINDOW) if LOGIN_ADDRESS_ATTEMPTS > 0 else None
# Reset codes asked for per email address, whether or not an account uses it, so the limit never says which do.
reset_throttle = Throttle(RESET_EMAILS, 60 * 60)
# Wrong reset codes per email address, whether or not an account uses it, so this limit never says which do either.
reset_guess_throttle = Throttle(RESET_GUESSES, 24 * 60 * 60)


def wait_words(seconds):
    """How long a wait is, as a person would say it: "3 minutes", "5 hours"."""
    minutes = (seconds + 59) // 60
    if minutes < 120:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours = (minutes + 59) // 60
    return f'{hours} hours'


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


# ---- Web push: reminders on training days ------------------------------------------------------------------
# A phone that has allowed notifications is given a push subscription by its browser: an address on the browser maker's
# push service, and two keys. The server posts a message to that address, encrypted for that browser alone (RFC 8291,
# aes128gcm per RFC 8188) and signed as this server (VAPID, RFC 8292), and the browser wakes its service worker to show it.
#
# The standard library has no elliptic curves or AES, so the little of them that this needs is here: P-256 (ECDH and ECDSA),
# AES-128 in GCM, and HKDF. They are checked against known answers in tests/suites/push.py. Pure Python is not constant-time,
# which would matter if someone could make the server use a long-lived key over and over and time the answers. Here the
# only long-lived key signs tokens that go to the push service, never back to whoever caused them, and every message's
# encryption key is made fresh.

PUSH_TIMEOUT = 10
# What the push service is told to do with a message it cannot deliver yet (a phone that is off), in seconds.
PUSH_TTL = 3 * 60 * 60
# Who the server says it is to the push services, which may refuse a message with no way to reach its sender (RFC 8292).
VAPID_SUBJECT = os.environ.get('VAPID_SUBJECT', '').strip() or (f'mailto:{SMTP_FROM}' if '@' in SMTP_FROM else 'mailto:admin@example.com')
# How often the server looks for training days to remind about, and how long after the time chosen a reminder is still
# worth sending (the server was down at that moment, or the phone off).
REMINDER_TICK = max(0.2, float(os.environ.get('REMINDER_TICK_SECONDS', '60')))
REMINDER_GRACE_MINUTES = 3 * 60
# Push services a subscription may name, as hosts or the end of one. A subscription is an address this server then posts to,
# so it is not taken from just anyone: PUSH_ALLOWED_HOSTS adds hosts (and lets them be plain http, for a push service of one's
# own), which is how the tests give the server a push service to talk to.
PUSH_SERVICES = ('fcm.googleapis.com', 'push.services.mozilla.com', 'push.apple.com', 'notify.windows.com')
PUSH_ALLOWED_HOSTS = tuple(host.strip().lower() for host in os.environ.get('PUSH_ALLOWED_HOSTS', '').split(',') if host.strip())
MAX_SUBSCRIPTIONS = 10
# How many messages go at once (see send_all). Threads only wait on the network, so a few is plenty for one household's phones,
# and not so many that one push service that has stopped answering could take them all.
PUSH_WORKERS = 8
push_pool = concurrent.futures.ThreadPoolExecutor(max_workers=PUSH_WORKERS, thread_name_prefix='push')
# The least time between one test notification and the next, per account, in seconds.
TEST_PUSH_WAIT = float(os.environ.get('PUSH_TEST_WAIT', '3'))
push_test_times = {}
push_test_lock = threading.Lock()


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64url_decode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]*', value):
        raise ValueError('not base64url')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


# -- P-256 --
# Points are kept as Jacobian (x, y, z) triples while they are worked on, which needs no division until the end; z == 0 is
# the point at infinity.
P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
P256_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
P256_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
P256_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
          0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)
EC_INFINITY = (1, 1, 0)


def ec_double(point):
    x, y, z = point
    if z == 0 or y == 0:
        return EC_INFINITY
    p = P256_P
    delta = z * z % p
    gamma = y * y % p
    beta = x * gamma % p
    alpha = 3 * (x - delta) * (x + delta) % p
    x3 = (alpha * alpha - 8 * beta) % p
    return x3, (alpha * (4 * beta - x3) - 8 * gamma * gamma) % p, ((y + z) ** 2 - gamma - delta) % p


def ec_add(first, second):
    if first[2] == 0:
        return second
    if second[2] == 0:
        return first
    p = P256_P
    x1, y1, z1 = first
    x2, y2, z2 = second
    z1z1, z2z2 = z1 * z1 % p, z2 * z2 % p
    u1, u2 = x1 * z2z2 % p, x2 * z1z1 % p
    s1, s2 = y1 * z2 * z2z2 % p, y2 * z1 * z1z1 % p
    if u1 == u2:
        return ec_double(first) if s1 == s2 else EC_INFINITY
    h, r = (u2 - u1) % p, (s2 - s1) % p
    h2 = h * h % p
    h3 = h * h2 % p
    v = u1 * h2 % p
    x3 = (r * r - h3 - 2 * v) % p
    return x3, (r * (v - x3) - s1 * h3) % p, h * z1 * z2 % p


def ec_multiply(scalar, point=P256_G):
    """scalar × point as an (x, y) pair, or None for the point at infinity. A Montgomery ladder: every bit does the same two
    operations, whichever it is."""
    base = (point[0], point[1], 1)
    low, high = EC_INFINITY, base
    for bit in bin(scalar % P256_N)[2:]:
        if bit == '1':
            low, high = ec_add(low, high), ec_double(high)
        else:
            high, low = ec_add(low, high), ec_double(low)
    if low[2] == 0:
        return None
    inverse = pow(low[2], -1, P256_P)
    return low[0] * inverse * inverse % P256_P, low[1] * inverse ** 3 % P256_P


def ec_on_curve(x, y):
    return 0 <= x < P256_P and 0 <= y < P256_P and (y * y - (x * x * x - 3 * x + P256_B)) % P256_P == 0


def encode_point(x, y):
    return b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')


def decode_point(raw):
    """The (x, y) of an uncompressed P-256 public key, which must be a point on the curve."""
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError('not an uncompressed P-256 point')
    x, y = int.from_bytes(raw[1:33], 'big'), int.from_bytes(raw[33:], 'big')
    if not ec_on_curve(x, y):
        raise ValueError('not on the curve')
    return x, y


def ecdsa_sign(private, message):
    """An ES256 signature (r then s, 32 bytes each) of the message."""
    z = int.from_bytes(hashlib.sha256(message).digest(), 'big')
    while True:
        k = secrets.randbelow(P256_N - 1) + 1
        r = ec_multiply(k)[0] % P256_N
        s = pow(k, -1, P256_N) * (z + r * private) % P256_N
        if r and s:
            return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


def hkdf(salt, key_material, info, length):
    """HKDF-SHA256 (RFC 5869): extract, then expand."""
    pseudo_random_key = hmac.new(salt, key_material, hashlib.sha256).digest()
    output = block = b''
    while len(output) < length:
        block = hmac.new(pseudo_random_key, block + info + bytes([len(output) // 32 + 1]), hashlib.sha256).digest()
        output += block
    return output[:length]


# -- AES-128 in GCM --
def aes_tables():
    """The S-box and the table that doubles a byte in GF(2^8), worked out rather than typed in."""
    sbox = [0] * 256
    rotated = lambda value, by: ((value << by) | (value >> (8 - by))) & 0xff
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xff) ^ (0x1b if p & 0x80 else 0)       # p times 3
        q ^= (q << 1) & 0xff                                         # q divided by 3
        q ^= (q << 2) & 0xff
        q ^= (q << 4) & 0xff
        if q & 0x80:
            q ^= 0x09
        sbox[p] = q ^ rotated(q, 1) ^ rotated(q, 2) ^ rotated(q, 3) ^ rotated(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox, [((value << 1) ^ (0x1b if value & 0x80 else 0)) & 0xff for value in range(256)]


AES_SBOX, AES_DOUBLE = aes_tables()


def aes_round_keys(key):
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for index in range(4, 44):
        word = words[index - 1][:]
        if index % 4 == 0:
            word = [AES_SBOX[byte] for byte in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = AES_DOUBLE[rcon]
        words.append([a ^ b for a, b in zip(words[index - 4], word)])
    return [sum(words[4 * round_number:4 * round_number + 4], []) for round_number in range(11)]


def aes_encrypt_block(round_keys, block):
    state = [a ^ b for a, b in zip(block, round_keys[0])]
    for round_number in range(1, 11):
        state = [AES_SBOX[byte] for byte in state]
        state = [state[(i + 4 * (i % 4)) % 16] for i in range(16)]       # shift rows
        if round_number < 10:
            mixed = []
            for column in range(0, 16, 4):
                a0, a1, a2, a3 = state[column:column + 4]
                mixed += [AES_DOUBLE[a0] ^ AES_DOUBLE[a1] ^ a1 ^ a2 ^ a3, a0 ^ AES_DOUBLE[a1] ^ AES_DOUBLE[a2] ^ a2 ^ a3,
                          a0 ^ a1 ^ AES_DOUBLE[a2] ^ AES_DOUBLE[a3] ^ a3, AES_DOUBLE[a0] ^ a0 ^ a1 ^ a2 ^ AES_DOUBLE[a3]]
            state = mixed
        state = [a ^ b for a, b in zip(state, round_keys[round_number])]
    return bytes(state)


def gcm_multiply(x, y):
    """Multiplication in GCM's field, on 128-bit integers."""
    z, v = 0, y
    for bit in range(127, -1, -1):
        if (x >> bit) & 1:
            z ^= v
        v = (v >> 1) ^ (0xe1 << 120) if v & 1 else v >> 1
    return z


def gcm_ghash(hash_key, data):
    value = 0
    for start in range(0, len(data), 16):
        value = gcm_multiply(value ^ int.from_bytes(data[start:start + 16].ljust(16, b'\0'), 'big'), hash_key)
    return value


def gcm_keystream_xor(round_keys, iv, data):
    """The data with the counter-mode keystream from block 2 of this IV (block 1 is for the tag) mixed in: encrypts or decrypts."""
    output = bytearray()
    for index in range(0, len(data), 16):
        counter = iv + (index // 16 + 2).to_bytes(4, 'big')
        output += bytes(a ^ b for a, b in zip(data[index:index + 16], aes_encrypt_block(round_keys, counter)))
    return bytes(output)


def gcm_tag(round_keys, iv, ciphertext):
    hash_key = int.from_bytes(aes_encrypt_block(round_keys, bytes(16)), 'big')
    lengths = (0).to_bytes(8, 'big') + (len(ciphertext) * 8).to_bytes(8, 'big')
    padded = ciphertext + bytes(-len(ciphertext) % 16)
    digest = gcm_ghash(hash_key, padded + lengths).to_bytes(16, 'big')
    return bytes(a ^ b for a, b in zip(digest, aes_encrypt_block(round_keys, iv + (1).to_bytes(4, 'big'))))


def aes_gcm_seal(key, iv, plaintext):
    """The ciphertext followed by its 16-byte tag, for a 16-byte key and a 12-byte IV, with nothing else authenticated."""
    round_keys = aes_round_keys(key)
    ciphertext = gcm_keystream_xor(round_keys, iv, plaintext)
    return ciphertext + gcm_tag(round_keys, iv, ciphertext)


# -- The message --
def encrypt_push_payload(payload, receiver_public, auth_secret, sender_private=None, salt=None):
    """`payload` encrypted for one browser (RFC 8291), as the body of the request to its push service: a header naming the
    salt and this message's own public key, then one record of aes128gcm (RFC 8188). The last two arguments are for tests,
    which need the same message twice; every real one has a key and salt of its own."""
    sender_private = sender_private or secrets.randbelow(P256_N - 1) + 1
    sender_public = encode_point(*ec_multiply(sender_private))
    shared = ec_multiply(sender_private, decode_point(receiver_public))
    if shared is None:
        raise ValueError('no shared secret')
    key_material = hkdf(auth_secret, shared[0].to_bytes(32, 'big'), b'WebPush: info\0' + receiver_public + sender_public, 32)
    salt = salt or secrets.token_bytes(16)
    key = hkdf(salt, key_material, b'Content-Encoding: aes128gcm\0', 16)
    nonce = hkdf(salt, key_material, b'Content-Encoding: nonce\0', 12)
    record = payload + b'\x02'
    if len(record) > 4096 - 16:
        raise ValueError('a push message is limited to about 4 KB')
    return salt + (4096).to_bytes(4, 'big') + bytes([len(sender_public)]) + sender_public + aes_gcm_seal(key, nonce, record)


# -- This server's key --
vapid_key_cache = {}
vapid_key_lock = threading.Lock()


def vapid_key():
    """(private key, public key as base64url): made the first time one is needed and kept in the database, so a subscription
    made against it keeps working across restarts, and across an update."""
    with vapid_key_lock:
        if not vapid_key_cache:
            with connection() as database:
                row = database.execute("SELECT value FROM server_keys WHERE name = 'vapid'").fetchone()
                if not row:
                    database.execute("INSERT OR IGNORE INTO server_keys (name, value) VALUES ('vapid', ?)", (f'{secrets.randbelow(P256_N - 1) + 1:064x}',))
                    row = database.execute("SELECT value FROM server_keys WHERE name = 'vapid'").fetchone()
            private = int(row['value'], 16)
            vapid_key_cache.update(private=private, public=b64url(encode_point(*ec_multiply(private))))
    return vapid_key_cache['private'], vapid_key_cache['public']


def vapid_authorization(endpoint):
    """The Authorization header that says the message comes from this server (RFC 8292): a signed token for the push
    service's own address, and the key that signed it."""
    parts = urlparse(endpoint)
    def part(value):
        return b64url(json.dumps(value, separators=(',', ':')).encode())
    signing = f"{part({'typ': 'JWT', 'alg': 'ES256'})}.{part({'aud': f'{parts.scheme}://{parts.netloc}', 'exp': int(time.time()) + 12 * 3600, 'sub': VAPID_SUBJECT})}"
    private, public = vapid_key()
    return f'vapid t={signing}.{b64url(ecdsa_sign(private, signing.encode()))}, k={public}'


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """A push service that answers with a redirect is not followed: the address was checked, where it points is not."""

    def redirect_request(self, *args, **kwargs):
        return None


def push_endpoint_allowed(endpoint):
    """Whether this address may be posted to: a known push service over https, or one the administrator named."""
    try:
        parts = urlparse(endpoint)
        host = (parts.hostname or '').lower()
        port = parts.port
    except ValueError:
        return False
    if parts.username or parts.password or not host:
        return False
    matches = lambda hosts: any(host == allowed or host.endswith('.' + allowed) for allowed in hosts)
    if matches(PUSH_ALLOWED_HOSTS):
        return parts.scheme in ('http', 'https')
    return parts.scheme == 'https' and port in (None, 443) and matches(PUSH_SERVICES)


def send_push(subscription, message):
    """Posts a message (a dict) to a subscription. Returns the push service's status, or None if it could not be reached."""
    try:
        body = encrypt_push_payload(json.dumps(message, separators=(',', ':')).encode(), b64url_decode(subscription['p256dh']), b64url_decode(subscription['auth']))
    except ValueError:
        return 400
    request = urllib.request.Request(subscription['endpoint'], data=body, method='POST', headers={
        'Authorization': vapid_authorization(subscription['endpoint']), 'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream',
        'TTL': str(PUSH_TTL), 'Urgency': 'normal'})
    try:
        with urllib.request.build_opener(NoRedirects).open(request, timeout=PUSH_TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return None


def send_safely(subscription, message):
    """send_push, with anything it did not expect kept from stopping the rest: a message that goes astray is no worse than one lost."""
    try:
        return send_push(subscription, message)
    except Exception:
        traceback.print_exc()
        return None


def send_all(subscriptions, message):
    """The message sent to every subscription at once, up to PUSH_WORKERS at a time, so a push service that is slow, or
    does not answer, holds up only its own. The statuses, in the order of the subscriptions."""
    return list(push_pool.map(lambda subscription: send_safely(subscription, message), subscriptions))


def settle_pushes(database, subscriptions, statuses):
    """What the statuses of the sends mean: forgets the subscriptions the push service says are gone (404 and 410, a phone
    that cleared its site data or turned notifications off). Returns how many were sent, how many were forgotten, and the
    subscriptions that failed some other way."""
    sent, forgotten, failed = 0, 0, []
    for subscription, status in zip(subscriptions, statuses):
        if status is not None and 200 <= status < 300:
            sent += 1
        elif status in (404, 410):
            database.execute('DELETE FROM push_subscriptions WHERE id = ?', (subscription['id'],))
            forgotten += 1
        else:
            print(f"Could not push to {urlparse(subscription['endpoint']).netloc}: {'no answer' if status is None else status}.", flush=True)
            failed.append(subscription)
    return sent, forgotten, failed


# -- Training days --
def reminder_schedule(settings_json):
    """(days as the browser numbers them, Sunday 0, and the time as minutes after midnight), or None for no reminders."""
    try:
        schedule = json.loads(settings_json or '{}').get('schedule')
        days = {day for day in schedule['days'] if isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6}
        hours, minutes = schedule.get('time', DEFAULT_REMINDER_TIME).split(':')
        return (days, int(hours) * 60 + int(minutes)) if days else None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def device_clock(subscription, now):
    """The time on the phone the subscription belongs to: its time zone, or when this server does not know that one, the
    offset it had when it last said so."""
    try:
        return now.astimezone(ZoneInfo(subscription['tz']))
    except (ZoneInfoNotFoundError, ValueError, OSError, KeyError, TypeError):
        return now.astimezone(datetime.timezone(datetime.timedelta(minutes=subscription['offset_minutes'] or 0)))


def due_reminders(database, now):
    """The subscriptions to remind at this moment, each marked as reminded for its day. A phone is reminded once on a
    training day, from the time chosen until REMINDER_GRACE_MINUTES minutes after, and not when a workout has been saved that day."""
    due = []
    rows = database.execute('SELECT s.id, s.user_id, s.endpoint, s.p256dh, s.auth, s.tz, s.offset_minutes, s.last_sent, u.settings_json '
                            'FROM push_subscriptions s JOIN user_state u ON u.user_id = s.user_id').fetchall()
    for row in rows:
        schedule = reminder_schedule(row['settings_json'])
        if not schedule:
            continue
        days, at = schedule
        clock = device_clock(row, now)
        minute = clock.hour * 60 + clock.minute
        today = clock.date().isoformat()
        if (clock.weekday() + 1) % 7 not in days or not at <= minute < at + REMINDER_GRACE_MINUTES or row['last_sent'] == today:
            continue
        midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
        trained = database.execute('SELECT 1 FROM workouts WHERE user_id = ? AND created_at >= ? AND created_at < ?',
                                   (row['user_id'], int(midnight.timestamp() * 1000), int((midnight + datetime.timedelta(days=1)).timestamp() * 1000))).fetchone()
        claimed = database.execute('UPDATE push_subscriptions SET last_sent = ? WHERE id = ? AND (last_sent IS NULL OR last_sent != ?)', (today, row['id'], today)).rowcount
        if claimed and not trained:
            due.append(dict(row))
    return due


REMINDER_MESSAGE = {'title': 'Time to train', 'body': 'Today is a training day. Tap to open Workout Tracker.', 'url': '/index.html', 'tag': 'training-day'}


def send_due_reminders():
    now = datetime.datetime.now(datetime.timezone.utc)
    with connection() as database:
        due = due_reminders(database, now)
    # Each is sent by the pool, and settled as its answer comes, so this returns at once: the next look at the time is not kept
    # waiting for a push service that has stopped answering. No connection is held while a message goes either.
    for subscription in due:
        push_pool.submit(send_safely, subscription, REMINDER_MESSAGE).add_done_callback(lambda future, subscription=subscription: reminder_answered(subscription, future))


def reminder_answered(subscription, future):
    """What came of one reminder: a phone the push service says is gone is forgotten, and one that could not be reached is tried
    again on the next look, while it is still worth it (its day is not counted as reminded)."""
    try:
        with connection() as database:
            if settle_pushes(database, [subscription], [future.result()])[2]:
                database.execute('UPDATE push_subscriptions SET last_sent = ? WHERE id = ?', (subscription['last_sent'], subscription['id']))
    except Exception:
        traceback.print_exc()


def reminder_loop():
    while True:
        time.sleep(REMINDER_TICK)
        try:
            send_due_reminders()
        except Exception:
            traceback.print_exc()


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
        '.woff2': 'font/woff2',
    }

    # Applied to every read and write on the connection (see REQUEST_TIMEOUT).
    timeout = REQUEST_TIMEOUT

    # Answers say HTTP/1.1, because a browser takes an ETag, and so the workouts' 304, only from a server that does: the standard
    # library's HTTP/1.0 makes it ask for everything again. Every connection is still closed after its answer, as it always
    # was (keep-alive would hold a thread for each idle one, and a stop would wait for them), which Connection: close says.
    protocol_version = 'HTTP/1.1'

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
        if urlparse(self.path).path.endswith(RANGED):
            return self.send_ranged_file()
        compressed = self.send_compressed_file()
        return super().send_head() if compressed is False else compressed

    def send_ranged_file(self):
        """A video, whole or the one byte range asked for. Several ranges in one request are answered with the whole file,
        which HTTP allows; no browser asks a video for more than one."""
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        with open(path, 'rb') as handle:
            body = handle.read()
        size = len(body)
        start, end, status = 0, size - 1, HTTPStatus.OK
        asked = re.fullmatch(r'\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*', self.headers.get('Range', ''))
        if asked and (asked.group(1) or asked.group(2)):
            if asked.group(1):
                start = int(asked.group(1))
                end = min(int(asked.group(2)), size - 1) if asked.group(2) else size - 1
            else:  # bytes=-N: the last N
                start = max(0, size - int(asked.group(2)))
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Accept-Ranges', 'bytes')
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Last-Modified', self.date_time_string(os.stat(path).st_mtime))
        self.end_headers()
        return io.BytesIO(body[start:end + 1])

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
        understood = super().parse_request()
        self.close_connection = True
        return understood

    def send_response(self, *args, **kwargs):
        self.cache_control_sent = False
        self.connection_sent = False
        super().send_response(*args, **kwargs)

    def send_header(self, keyword, value):
        if keyword.lower() == 'cache-control':
            self.cache_control_sent = True
        elif keyword.lower() == 'connection':
            self.connection_sent = True
        super().send_header(keyword, value)

    def end_headers(self):
        # Static files otherwise go out with only Last-Modified, and a browser is then
        # free to guess how long they stay fresh. It guesses badly: a signed-out visit
        # can be answered from the cache with the signed-in page instead of the login
        # redirect, and an upgraded server keeps serving old JavaScript to a browser
        # that never asks again. Revalidating every time costs a 304 and avoids both.
        if not getattr(self, 'cache_control_sent', False):
            self.send_header('Cache-Control', 'no-cache')
        if not getattr(self, 'connection_sent', False):
            self.send_header('Connection', 'close')
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
        """The cookie carrying a session. With no max_age it lasts until the browser is closed."""
        lifetime = '' if max_age is None else f'; Max-Age={max_age}'
        return f"session={token}; Path=/; HttpOnly; SameSite=Lax{lifetime}" + ('; Secure' if self.secure_cookies() else '')

    def send_json(self, status, payload, cookies=None, headers=None):
        body, encoding = self.encoded(json.dumps(payload).encode())
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        for name, value in {'Cache-Control': 'no-store', **encoding, **(headers or {})}.items():
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
            self.send_json(error.status, {'error': str(error)}, headers=error.headers)
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
            row = database.execute('SELECT users.id, users.username, users.email, sessions.expires_at, sessions.remember FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires_at > ?', (session_hash(token), now)).fetchone()
            # A session lasts SESSION_TTL from when it was last used, not from signing in, so someone who trains every week
            # stays signed in. Renewed at most once a day, and the cookie with it, or the browser would drop it on time anyway.
            # One started without "Remember me" is renewed the same way on its shorter clock, and its cookie stays one
            # that goes when the browser does.
            if row:
                remembered = bool(row['remember'])
                lifetime, renew = (SESSION_TTL, SESSION_RENEW) if remembered else (SHORT_SESSION_TTL, SHORT_SESSION_RENEW)
                if row['expires_at'] < now + lifetime - renew:
                    database.execute('UPDATE sessions SET expires_at = ? WHERE token = ?', (now + lifetime, session_hash(token)))
                    self.renewed_cookie = self.session_cookie(token, lifetime if remembered else None)
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
        if parsed.path in ('/', '/index.html', '/cardio.html', '/progress.html', '/history.html') and not self.session_user():
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

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.handle_api(self.api_patch, parsed.path)
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
                # A page already holding the history is told so, rather than sent it again: every page asks on every load,
                # and the history only grows. Cached by the browser, which checks with the server each time (no-cache), under a
                # tag that changes whenever a workout does. The tag is read first, so workouts changing meanwhile can only
                # leave the browser with newer ones than the tag says, which it then asks for again.
                etag = f'W/"{workout_tag(database, user["id"])}"'
                caching = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
                if etag_matches(self.headers.get('If-None-Match'), etag):
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    for name, value in caching.items():
                        self.send_header(name, value)
                    self.end_headers()
                    return
                rows = database.execute('SELECT id, name, notes, created_at, payload FROM workouts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)).fetchall()
                workouts = []
                for row in rows:
                    item = json.loads(row['payload'])
                    item.update(id=row['id'], name=row['name'], notes=row['notes'], createdAt=row['created_at'])
                    workouts.append(item)
                self.send_json(HTTPStatus.OK, {'workouts': workouts}, headers=caching)
            elif path == '/api/active-session':
                row = database.execute('SELECT payload FROM active_sessions WHERE user_id = ?', (user['id'],)).fetchone()
                self.send_json(HTTPStatus.OK, {'session': json.loads(row['payload']) if row else None})
            elif path == '/api/state':
                self.send_json(HTTPStatus.OK, load_state(database, user['id']))
            elif path == '/api/push/key':
                self.send_json(HTTPStatus.OK, {'publicKey': vapid_key()[1]})
            elif path in ('/api/export', '/api/export.csv'):
                self.export_account(database, user, as_csv=path.endswith('.csv'))
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def start_session(self, database, user_id, remember=True):
        """Sign this account in: a new session, and the cookie that carries it. One that is not remembered ends when the
        browser closes, or after SHORT_SESSION_TTL without use."""
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        lifetime = SESSION_TTL if remember else SHORT_SESSION_TTL
        database.execute('DELETE FROM sessions WHERE expires_at <= ?', (now,))
        database.execute('INSERT INTO sessions (token, user_id, expires_at, remember) VALUES (?, ?, ?, ?)', (session_hash(token), user_id, now + lifetime, int(remember)))
        return self.session_cookie(token, lifetime if remember else None)

    def wants_remembering(self, data):
        """Whether the sign-in asked to be remembered. Pages from before "Remember me" say nothing, and were."""
        remember = data.get('remember', True)
        if not isinstance(remember, bool):
            raise BadRequest('remember must be true or false.')
        return remember

    def send_wait(self, wait, message):
        self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {'error': f'{message} Try again in {wait_words(wait)}.'}, headers={'Retry-After': str(wait)})

    def register(self):
        if not ALLOW_REGISTRATION:
            self.send_json(HTTPStatus.FORBIDDEN, {'error': 'New accounts are turned off on this server.'})
            return
        data = self.read_json()
        email = email_address(data.get('email'))
        username = new_username(data.get('username'))
        password = new_password(str(data.get('password', '')), username, email)
        remember = self.wants_remembering(data)
        with connection() as database:
            if database.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone():
                raise BadRequest('That username is already registered.', HTTPStatus.CONFLICT)
            if database.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
                raise BadRequest('That email is already registered.', HTTPStatus.CONFLICT)
            # Only now, so a name or email already taken costs no hash. Reading takes no lock, so none is held meanwhile.
            stored_hash = password_hash(password)
            user_id = database.execute('INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
                                       (username, email, stored_hash, int(time.time() * 1000))).lastrowid
            cookie = self.start_session(database, user_id, remember)
        self.send_json(HTTPStatus.OK, {'user': {'id': user_id, 'username': username, 'email': email}}, [cookie])

    def sign_in(self):
        data = self.read_json()
        # An email or a username. Pages from before accounts had emails send it as `username`.
        login = str(data.get('login', data.get('username', ''))).strip()
        password = str(data.get('password', ''))
        if len(login) < 3 or len(password) < 8:
            raise BadRequest('Enter your email or username, and a password of 8+ characters.')
        remember = self.wants_remembering(data)
        with connection() as database:
            row = find_account(database, login)
            # Keyed by the account rather than what was typed, so its email and its username share one limit.
            address = self.client_address[0]
            throttle_key = (address, (row['username'] if row else login).lower())
            # Refused before the password is even checked, so guessing cannot continue during the wait.
            wait = address_throttle.retry_after(address) if address_throttle else 0
            if wait:
                self.send_wait(wait, 'Too many failed sign-ins from this address.')
                return
            wait = login_throttle.retry_after(throttle_key)
            if wait:
                self.send_wait(wait, 'Too many failed sign-ins.')
                return
            matches = password_matches(password, row['password_hash'] if row else DUMMY_HASH)
            if not row or not matches:
                login_throttle.record(throttle_key)
                if address_throttle:
                    address_throttle.record(address)
                self.send_json(HTTPStatus.UNAUTHORIZED, {'error': 'Wrong email, username or password.'})
                return
            login_throttle.clear(throttle_key)
            if needs_rehash(row['password_hash']):
                # The password is only known now, so this is the moment to move an older hash to the current strength.
                database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash(password), row['id']))
            cookie = self.start_session(database, row['id'], remember)
        self.send_json(HTTPStatus.OK, {'user': public_user(row)}, [cookie])

    def send_reset_code(self):
        if not SMTP_HOST:
            raise BadRequest('Password reset by email is not set up on this server.', HTTPStatus.NOT_FOUND)
        # Loosely: an account's email from before the rules were strict must still get its code.
        email = email_address(self.read_json().get('email'), strict=False)
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
        email = email_address(data.get('email'), strict=False)
        code = ''.join(text(data.get('code'), 'code', 100).split())
        password = str(data.get('password', ''))
        if not re.fullmatch('[0-9]{6}', code):
            raise BadRequest('Enter the 6-digit code from the email.')
        # Checked before the code is, so a password that will not do costs none of its tries. The username is only
        # known once the code is right, and is checked then.
        new_password(password, email=email)
        wait = reset_guess_throttle.retry_after(email)
        if wait:
            self.send_wait(wait, 'Too many wrong codes for this address.')
            return
        with connection() as database:
            user = database.execute('SELECT id, username, email FROM users WHERE email = ?', (email,)).fetchone()
            reset = None
            # The try is counted before the code is compared, and in the same write, so guesses sent at once cannot
            # share one. An address with no account, no code, or a used-up code all get the same answer.
            if user and database.execute('UPDATE password_resets SET attempts = attempts + 1 WHERE user_id = ? AND attempts < ? AND expires_at > ?',
                                         (user['id'], RESET_CODE_ATTEMPTS, int(time.time()))).rowcount:
                reset = database.execute('SELECT code_hash FROM password_resets WHERE user_id = ?', (user['id'],)).fetchone()
            accepted = reset is not None and secrets.compare_digest(reset_code_hash(code), reset['code_hash'])
        # Raised only now, so the counted try is committed rather than rolled back with the refusal.
        wrong = 'That code is wrong or has expired. Check the newest email, or send a new code.'
        if not accepted:
            reset_guess_throttle.record(email)
            raise BadRequest(wrong)
        new_password(password, user['username'], email)
        # Hashed only once the code is right, so a wrong guess costs no hash; and between the two writes, so nothing else
        # waits on the database meanwhile. Too busy to hash it, and the code still works for another go.
        stored_hash = password_hash(password)
        with connection() as database:
            # The code works once: of two requests that both had it right, the first to get here takes it.
            if not database.execute('DELETE FROM password_resets WHERE user_id = ? AND code_hash = ?', (user['id'], reset['code_hash'])).rowcount:
                raise BadRequest(wrong)
            database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user['id']))
            # Whoever knew the old password is signed out everywhere.
            database.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
            cookie = self.start_session(database, user['id'])
        reset_guess_throttle.clear(email)
        login_throttle.clear((self.client_address[0], user['username'].lower()))
        self.send_json(HTTPStatus.OK, {'user': public_user(user)}, [cookie])

    def confirm_password(self, database, user, password, wrong='That password is not right.'):
        """Check the signed-in account's password, asked again before a change only its owner should make: a signed-in
        page may not be its owner's. Wrong ones count as failed sign-ins, and the same wait applies."""
        throttle_key = (self.client_address[0], user['username'].lower())
        wait = login_throttle.retry_after(throttle_key)
        if wait:
            raise BadRequest(f'Too many wrong passwords. Try again in {wait_words(wait)}.', HTTPStatus.TOO_MANY_REQUESTS, {'Retry-After': str(wait)})
        stored = database.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()['password_hash']
        if not password_matches(str(password or ''), stored):
            login_throttle.record(throttle_key)
            # 403, not 401: the session is fine, and a 401 would tell the page it had expired.
            raise BadRequest(wrong, HTTPStatus.FORBIDDEN)

    def change_email(self, user):
        data = self.read_json()
        email = email_address(data.get('email'))
        with connection() as database:
            self.confirm_password(database, user, data.get('password'))
            if database.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (email, user['id'])).fetchone():
                raise BadRequest('Another account already uses that email.', HTTPStatus.CONFLICT)
            database.execute('UPDATE users SET email = ? WHERE id = ?', (email, user['id']))
            # A code already sent went to the old address.
            database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'user': {**user, 'email': email}})

    def change_password(self, user):
        data = self.read_json()
        current = str(data.get('currentPassword', ''))
        new = new_password(str(data.get('newPassword', '')), user['username'], user['email'] or '')
        stored_hash = password_hash(new)
        with connection() as database:
            self.confirm_password(database, user, current, 'Your current password is not right.')
            database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user['id']))
            # Whoever knew the old password is signed out everywhere but here, and a reset code sent for it stops working.
            signed_out = database.execute('DELETE FROM sessions WHERE user_id = ? AND token != ?', (user['id'], session_hash(self.session_token()))).rowcount
            database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'signedOut': signed_out})

    def delete_account(self, user):
        password = self.read_json().get('password')
        with connection() as database:
            self.confirm_password(database, user, password)
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
        export = {'format': EXPORT_FORMAT, 'version': 1, 'exportedAt': int(time.time() * 1000),
                  'account': {'username': user['username'], 'email': user['email']}, 'workouts': workouts,
                  **load_state(database, user['id'])}
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
        state = {name: data[name] for name in STATE_PARTS if name in data}
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
            have = load_state(database, user['id'])
            # Each part takes what it will of the file's (and refuses the file, with nothing stored, if that would take it past its limit).
            taken = {name: part.take(have[name], state.get(name)) for name, part in STATE_PARTS.items()}
            if any(count for _, count in taken.values()):
                store_state(database, user['id'], {name: value for name, (value, _) in taken.items()})
        self.send_json(HTTPStatus.OK, {'workouts': added, 'alreadyHere': len(prepared) - added,
                                       **{part.report: taken[name][1] for name, part in STATE_PARTS.items()}})

    def push_subscribe(self, user):
        """Remember this phone, to remind it on training days: what its browser's push service gave it (`endpoint` and `keys`)
        and its clock. Asking again with the same endpoint updates it, which is how a change of time zone reaches the server."""
        data = self.read_json()
        endpoint, keys = data.get('endpoint'), data.get('keys')
        if not isinstance(endpoint, str) or not 0 < len(endpoint) <= 1000 or not push_endpoint_allowed(endpoint):
            raise BadRequest('endpoint must be the address of a push service this server sends to.')
        try:
            if not isinstance(keys, dict):
                raise ValueError('keys')
            decode_point(b64url_decode(keys.get('p256dh')))
            if len(b64url_decode(keys.get('auth'))) != 16:
                raise ValueError('auth')
        except ValueError:
            raise BadRequest("keys must hold the subscription's public key (p256dh) and auth secret (auth).")
        zone = text(data.get('timeZone'), 'timeZone', 64)
        offset = data.get('utcOffset', 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or not -840 <= offset <= 840:
            raise BadRequest('utcOffset must be minutes from UTC, from -840 to 840.')
        with connection() as database:
            database.execute('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, tz, offset_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) '
                             'ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth, '
                             'tz=excluded.tz, offset_minutes=excluded.offset_minutes',
                             (user['id'], endpoint, keys['p256dh'], keys['auth'], zone, offset, int(time.time() * 1000)))
            database.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND id NOT IN '
                             '(SELECT id FROM push_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT ?)', (user['id'], user['id'], MAX_SUBSCRIPTIONS))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def push_unsubscribe(self, user):
        endpoint = self.read_json().get('endpoint')
        if not isinstance(endpoint, str):
            raise BadRequest('endpoint must be the address to stop sending to.')
        with connection() as database:
            database.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?', (user['id'], endpoint))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def push_test(self, user):
        """A notification to every phone of this account now, so the lifter can see that reminders will arrive."""
        now = time.monotonic()
        with push_test_lock:
            if now - push_test_times.get(user['id'], -TEST_PUSH_WAIT) < TEST_PUSH_WAIT:
                raise BadRequest('Wait a few seconds before sending another test.', HTTPStatus.TOO_MANY_REQUESTS)
            push_test_times[user['id']] = now
        with connection() as database:
            subscriptions = [dict(row) for row in database.execute('SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?', (user['id'],))]
        statuses = send_all(subscriptions, {'title': 'Workout Tracker', 'body': 'Reminders work on this device.', 'url': '/index.html', 'tag': 'test'})
        with connection() as database:
            sent, forgotten, failed = settle_pushes(database, subscriptions, statuses)
        self.send_json(HTTPStatus.OK, {'devices': len(subscriptions), 'sent': sent, 'forgotten': forgotten, 'failed': len(failed)})

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
                    database.execute('DELETE FROM sessions WHERE token = ?', (session_hash(token),))
            # The workouts are kept by the browser between visits (see GET /api/workouts), so signing out clears them, on a
            # browser that understands this (Safari does not) and over HTTPS or localhost, the only places it is honoured.
            self.send_json(HTTPStatus.OK, {'ok': True}, [self.session_cookie('', 0)], headers={'Clear-Site-Data': '"cache"'})
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
        elif path == '/api/push/subscribe':
            self.push_subscribe(user)
        elif path == '/api/push/unsubscribe':
            self.push_unsubscribe(user)
        elif path == '/api/push/test':
            self.push_test(user)
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
            # Each part sent replaces the stored one whole. Pages from before PATCH (below) send this, so it stays.
            data = self.read_json()
            validate_state(data)
            with connection() as database:
                # Read and written in one locked go, so another request's change cannot land in between and be lost.
                database.execute('BEGIN IMMEDIATE')
                # Only the parts sent change. A missing key keeps the stored part; null is a real value for the program (ended).
                state = {**load_state(database, user['id']), **{name: data[name] for name in STATE_PARTS if name in data}}
                store_state(database, user['id'], state)
            self.send_json(HTTPStatus.OK, state)
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})

    def api_patch(self, path):
        user = self.require_user()
        if not user:
            return
        if path != '/api/state':
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})
            return
        # {part: {value, base, sent}}: each part as this device changed it, the copy it started from, and any copies sent
        # since without an answer, so the change can be merged with any made on another device (see merge_values). A part
        # sent without its base (a change made before this device had loaded the server's copy) replaces the stored one,
        # as PUT does.
        data = self.read_json(MAX_STATE_CHANGE)
        changes = {}
        for part, change in data.items():
            if part not in STATE_PARTS:
                raise BadRequest(f'{part} is not part of the account state.')
            if not isinstance(change, dict) or 'value' not in change:
                raise BadRequest(f'{part} must be an object with its value, and the base it was changed from.')
            if not isinstance(change.get('sent', []), list) or ('sent' in change and 'base' not in change):
                raise BadRequest(f'{part}.sent must be a list of copies sent since its base.')
            changes[part] = change
        validate_state({part: change['value'] for part, change in changes.items()})
        with connection() as database:
            # Read, merged and written in one locked go, so two devices sending at once both have their changes kept.
            database.execute('BEGIN IMMEDIATE')
            state = load_state(database, user['id'])
            for part, change in changes.items():
                mine = change['value']
                merged = merge_part(part, [change['base'], *change.get('sent', [])], mine, state[part]) if 'base' in change else mine
                if merged is not mine:
                    # A merge of two valid copies can still break a limit (more goals than are allowed, say); this
                    # device's own copy, already checked, is kept then, as it would have been without merging.
                    try:
                        validate_state({part: merged})
                    except BadRequest:
                        merged = mine
                state[part] = merged
            store_state(database, user['id'], state)
        self.send_json(HTTPStatus.OK, state)

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
    # `docker stop` and `systemctl stop` ask with SIGTERM. In a container the server is process 1, which the kernel
    # spares from any signal it has no handler for, so without this Docker waits 10 seconds and then kills it.
    # shutdown() waits for serve_forever to return, so it is called from another thread, not from inside the handler.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    threading.Thread(target=reminder_loop, daemon=True).start()
    server.serve_forever()
    server.server_close()
    print('Workout Tracker stopped.', flush=True)


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


def read_new_password(username, email):
    """Asked twice, unseen, at a terminal; read from the first line of input otherwise, so it can be piped in. It has to
    pass the same rules as one set on the sign-in page."""
    if sys.stdin.isatty():
        password = getpass.getpass('New password: ')
        if getpass.getpass('Same again: ') != password:
            raise AdminError('The passwords did not match. Nothing was changed.')
    else:
        password = sys.stdin.readline().rstrip('\r\n')
    problem = password_problem(password, username, email or '')
    if problem:
        raise AdminError(f'{problem} Nothing was changed.')
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
        account = admin_account(database, args.account)
    username = account['username']
    stored_hash = password_hash(read_new_password(username, account['email']))
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
