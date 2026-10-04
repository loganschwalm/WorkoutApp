"""Web push: the server's own signing key (VAPID), sending messages to a browser through its push service, and the loop that reminds
an account on its training days. The cryptography is in webpush_crypto.py."""

import concurrent.futures
import datetime
import json
import os
import secrets
import threading
import time
import traceback
import urllib.request
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import DEFAULT_REMINDER_TIME, SMTP_FROM
from database import connection
from webpush_crypto import P256_N, b64url, b64url_decode, ec_multiply, ecdsa_sign, encode_point, encrypt_push_payload


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
