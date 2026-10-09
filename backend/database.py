"""The SQLite database: its schema, moved up one numbered migration at a time, and the connection a request uses.
Add a migration to the end of MIGRATIONS and never change one that has shipped."""

import contextlib
import hashlib
import os
import secrets
import sqlite3
import unicodedata

from config import BUSY_TIMEOUT, DB_PATH


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


def migration_13_session_details(database):
    # What the list of signed-in devices shows of a session (when it began, when it was last used, the browser and system it
    # is, and the address it came from), and which session a phone's reminders were set up under, so signing that session out
    # (here, from another device, or by a password change) also stops them. Sessions and subscriptions from before have none
    # of it: they show as "Signed in earlier", and a subscription is given its session the next time its phone tells the server
    # about itself, which it does once a day.
    for column in ('created_at INTEGER NOT NULL DEFAULT 0', 'last_used INTEGER NOT NULL DEFAULT 0',
                   "label TEXT NOT NULL DEFAULT ''", "address TEXT NOT NULL DEFAULT ''"):
        database.execute(f'ALTER TABLE sessions ADD COLUMN {column}')
    database.execute('CREATE INDEX sessions_user ON sessions(user_id)')
    database.execute("ALTER TABLE push_subscriptions ADD COLUMN session_hash TEXT NOT NULL DEFAULT ''")


def migration_14_workout_bytes(database):
    # How much each account's workouts take as stored (their names, notes and the rest, in bytes), for MAX_WORKOUTS_MB. Kept by
    # triggers, as the tags of migration 12 are, so no way of writing a workout can forget to, and a new one is checked without
    # adding up every one before it. Accounts with workouts already are given their total here.
    size = lambda row: f'length(CAST({row}.name AS BLOB)) + length(CAST({row}.notes AS BLOB)) + length(CAST({row}.payload AS BLOB))'
    database.execute('CREATE TABLE workout_bytes (user_id INTEGER PRIMARY KEY, bytes INTEGER NOT NULL)')
    database.execute(f"INSERT INTO workout_bytes (user_id, bytes) SELECT user_id, SUM({size('workouts')}) FROM workouts GROUP BY user_id")
    for name, event, row, change in (('inserted', 'INSERT', 'NEW', size('NEW')), ('updated', 'UPDATE', 'NEW', f"{size('NEW')} - ({size('OLD')})"),
                                     ('deleted', 'DELETE', 'OLD', f"-({size('OLD')})")):
        database.execute(f'''
            CREATE TRIGGER workouts_bytes_{name} AFTER {event} ON workouts
            BEGIN
                INSERT INTO workout_bytes (user_id, bytes) VALUES ({row}.user_id, {change})
                ON CONFLICT(user_id) DO UPDATE SET bytes = bytes + excluded.bytes;
            END''')


def username_key(username):
    """What tells one username from another: the name composed (NFKC, so "José" typed with an accent or with a combining one is
    one name) and in one case, so "Henry" and "henry" are one name too. migration_15_username_keys gives every account its key, so
    changing this needs a new migration that gives them all again."""
    return unicodedata.normalize('NFKC', unicodedata.normalize('NFKC', username).casefold())


def migration_15_username_keys(database):
    # Usernames were unique only as typed, so "henry" and "Henry" could be two accounts, which look the same to a person and which
    # the sign-in limits, kept per name in any case, could not tell apart: whoever had one could reset the other's count of
    # failures by signing in. Each account is given its username_key, unique from now on. Two accounts from before that share one
    # (rare) keep signing in by their exact names; only the older of them holds the key, which a name in other capitals finds.
    database.execute('ALTER TABLE users ADD COLUMN username_key TEXT')
    held = set()
    for user_id, username in database.execute('SELECT id, username FROM users ORDER BY id').fetchall():
        key = username_key(username)
        if key not in held:
            held.add(key)
            database.execute('UPDATE users SET username_key = ? WHERE id = ?', (key, user_id))
    database.execute('CREATE UNIQUE INDEX users_username_key ON users(username_key)')


MIGRATIONS = [migration_1_tables, migration_2_client_ids, migration_3_programs, migration_4_emails, migration_5_exercise_notes,
              migration_6_hashed_sessions, migration_7_goals, migration_8_bodyweight, migration_9_remembered_sessions,
              migration_10_exercise_library, migration_11_push, migration_12_workout_cache, migration_13_session_details,
              migration_14_workout_bytes, migration_15_username_keys]


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


def delete_account_rows(database, user_id):
    """Everything an account has, then the account. The tables would cascade, but only with foreign keys on and on
    databases made since those references existed, so each is emptied by name. If the account held a username_key that an older
    account of the same name in other capitals went without (see migration_15_username_keys), the key goes to the oldest of
    those, so its name does not become free to register again in other capitals."""
    for table in ('sessions', 'workouts', 'workout_versions', 'workout_bytes', 'active_sessions', 'user_state', 'password_resets',
                  'push_subscriptions'):
        database.execute(f'DELETE FROM {table} WHERE user_id = ?', (user_id,))
    row = database.execute('SELECT username_key FROM users WHERE id = ?', (user_id,)).fetchone()
    database.execute('DELETE FROM users WHERE id = ?', (user_id,))
    if row and row[0] is not None:
        # Accounts with no key are only those twins, so there are none to look through on almost every server.
        for other_id, username in database.execute('SELECT id, username FROM users WHERE username_key IS NULL ORDER BY id').fetchall():
            if username_key(username) == row[0]:
                database.execute('UPDATE users SET username_key = ? WHERE id = ?', (row[0], other_id))
                break


def forget_reminders(database, user_id, session=None, keep=None):
    """Stops the reminders that were set up under a session (its token's hash), or under every session but `keep`: the phone they
    were for is no longer signed in to the account, and must not go on being told when it trains. Reminders from before they
    were tied to a session (none recorded) are left alone, and tie themselves to one the next time their phone says hello."""
    if session is not None:
        database.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND session_hash = ?', (user_id, session))
    else:
        database.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND session_hash NOT IN ('', ?)", (user_id, keep))


def workout_tag(database, user_id):
    """The tag that changes with the account's workouts (see migration_12_workout_cache). An account with workouts from before
    the tags has none until now, and is given one."""
    row = database.execute('SELECT tag FROM workout_versions WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        database.execute('INSERT OR IGNORE INTO workout_versions (user_id, tag) VALUES (?, ?)', (user_id, secrets.token_hex(8)))
        row = database.execute('SELECT tag FROM workout_versions WHERE user_id = ?', (user_id,)).fetchone()
    return row['tag']
