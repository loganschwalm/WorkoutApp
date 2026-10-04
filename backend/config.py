"""What the server is told by its environment, and the fixed limits it keeps: the one place a setting is read, so the
reference (readme-for-llm.md, Server settings) has one place to be checked against."""

import ipaddress
import os


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
# What one account may keep, so no one account (or a flood of them) can fill the disk. A workout is a few kilobytes: ten years of
# training six days a week is about 3,000 of them. MAX_WORKOUTS=0 takes the limit off, for a server only its owner uses.
MAX_WORKOUTS = int(os.environ.get('MAX_WORKOUTS', '50000'))
# The most one stored workout may be (as the JSON the server keeps), in bytes.
MAX_WORKOUT_BYTES = 256 * 1024
# Imports read up to MAX_IMPORT bytes into memory and parse them, so only this many run at once; another is told to try again.
MAX_IMPORTS_AT_ONCE = 1


def env_flag(name, default):
    value = os.environ.get(name, '').strip().lower()
    return default if not value else value not in ('0', 'false', 'no', 'off')


# Set ALLOW_REGISTRATION=0 once your accounts exist, so nobody else who can reach the port can make one.
ALLOW_REGISTRATION = env_flag('ALLOW_REGISTRATION', True)
# The cookie is also marked Secure whenever a reverse proxy says the request arrived over HTTPS.
SECURE_COOKIES = env_flag('SECURE_COOKIES', False)
# After this many failed sign-ins for one username from one address, that pair waits until the oldest failure
# is LOGIN_WINDOW seconds old. Behind a reverse proxy every request shares the proxy's address, unless TRUSTED_PROXIES names it.
LOGIN_ATTEMPTS = int(os.environ.get('LOGIN_ATTEMPTS', '5'))
LOGIN_WINDOW = int(os.environ.get('LOGIN_WINDOW', str(15 * 60)))
# Failed sign-ins from one address across every username before it waits the same way, so trying one common password
# against many usernames gets no further than many passwords against one. Not cleared by signing in, which an account of
# one's own could otherwise do between guesses. Behind a reverse proxy that TRUSTED_PROXIES does not name, every request
# shares the proxy's address, and one person's guessing would make everyone wait: 0 turns it off.
LOGIN_ADDRESS_ATTEMPTS = int(os.environ.get('LOGIN_ADDRESS_ATTEMPTS', '20'))


def proxy_networks(value):
    """The addresses and networks (192.168.1.10, 172.16.0.0/12) of TRUSTED_PROXIES."""
    try:
        return tuple(ipaddress.ip_network(part.strip(), strict=False) for part in value.split(',') if part.strip())
    except ValueError as error:
        raise SystemExit(f'TRUSTED_PROXIES must be addresses or networks separated by commas: {error}')


# Reverse proxies whose X-Forwarded-For is believed: a request from one of these is taken to come from the address the proxy
# says, so the sign-in limits above count each person behind it apart. A request from anywhere else is taken to come from
# where it came from, whatever it says, so a header cannot be used to dodge a limit by anyone who reaches the port directly.
TRUSTED_PROXIES = proxy_networks(os.environ.get('TRUSTED_PROXIES', ''))
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
# Reset emails are also limited per address that asks, whichever email it names, so one person cannot use the form to send
# a stream of emails to anyone (an address's own limit, RESET_EMAILS, would allow 120 a day to each), and per email a day.
# Behind a reverse proxy that TRUSTED_PROXIES does not name, everyone shares one address: 0 turns the per-address limit off.
RESET_ADDRESS_EMAILS = int(os.environ.get('RESET_ADDRESS_EMAILS', '10'))
RESET_EMAILS_DAILY = 10
# New accounts per address in an hour, so a script cannot fill the database with them. 0 turns it off.
REGISTRATIONS_PER_HOUR = int(os.environ.get('REGISTRATIONS_PER_HOUR', '5'))

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


# How long a request waits for another request's write to finish before giving up, in seconds.
BUSY_TIMEOUT = 10


# The time of day to remind at until one is chosen: the same as the page's default (settings-fields.js; tests/lint.py checks).
DEFAULT_REMINDER_TIME = '17:00'
