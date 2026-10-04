"""Accounts: what a new username, email and password must be, how passwords are hashed and how many may be hashed at once, the limits
on failed sign-ins and reset codes, finding an account, and the email a reset code is sent in."""

import hashlib
import math
import re
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from http import HTTPStatus

from config import (
    LEGACY_ITERATIONS, LOGIN_ADDRESS_ATTEMPTS, LOGIN_ATTEMPTS, LOGIN_WINDOW, PASSWORD_HASHERS, PASSWORD_HASH_WAIT,
    PBKDF2_ITERATIONS, REGISTRATIONS_PER_HOUR, RESET_ADDRESS_EMAILS, RESET_CODE_TTL, RESET_EMAILS, RESET_EMAILS_DAILY,
    RESET_GUESSES, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_SECURITY, SMTP_TIMEOUT, SMTP_USERNAME
)
from validation import BadRequest, text


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
reset_daily_throttle = Throttle(RESET_EMAILS_DAILY, 24 * 60 * 60)
# Reset codes asked for from one client address, whichever email it names (RESET_ADDRESS_EMAILS; off at 0).
reset_address_throttle = Throttle(RESET_ADDRESS_EMAILS, 60 * 60) if RESET_ADDRESS_EMAILS > 0 else None
# Accounts made from one client address (REGISTRATIONS_PER_HOUR; off at 0).
register_throttle = Throttle(REGISTRATIONS_PER_HOUR, 60 * 60) if REGISTRATIONS_PER_HOUR > 0 else None
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


def device_label(user_agent):
    """The browser and system a User-Agent header names, as a person would say it: "Safari on iPhone", "Chrome on Windows". What
    it is told is the client's own say-so, and only ever shown to the account it belongs to, to tell its devices apart."""
    agent = str(user_agent or '')
    browser = next((name for marker, name in (('Edg/', 'Edge'), ('EdgA/', 'Edge'), ('OPR/', 'Opera'), ('FxiOS', 'Firefox'), ('Firefox/', 'Firefox'),
                                              ('CriOS', 'Chrome'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari')) if marker in agent), 'Browser')
    system = next((name for marker, name in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('CrOS', 'ChromeOS'), ('Windows', 'Windows'),
                                             ('Macintosh', 'Mac'), ('Mac OS X', 'Mac'), ('Linux', 'Linux')) if marker in agent), '')
    return f'{browser} on {system}' if system else browser


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
