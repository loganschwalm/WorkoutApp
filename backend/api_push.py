"""Web push endpoints (see api_routes.py)."""

import time
from http import HTTPStatus

from config import TEST_PUSH_WAIT
from database import connection, session_hash
from validation import BadRequest, text
from webpush import (
    MAX_SUBSCRIPTIONS, REST_ALERT_MAX_SECONDS, push_endpoint_allowed, push_test_lock, push_test_times, schedule_rest_alert, send_all, settle_pushes,
    vapid_key
)
from webpush_crypto import b64url_decode, decode_point


class PushApi:
    """The endpoints of web push: the key to subscribe against, subscribing and unsubscribing a device, and the test notification."""

    def push_key(self, user):
        self.send_json(HTTPStatus.OK, {'publicKey': vapid_key()[1]})

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
        # What it is for, when the page says: reminders on training days and the alert at the end of a rest. A page that does not say
        # (an older one, still telling the server about its phone once a day) changes neither.
        purposes = {}
        for name, column in (('reminders', 'reminders'), ('restAlerts', 'rest_alerts')):
            if name in data:
                if not isinstance(data[name], bool):
                    raise BadRequest(f'{name} must be true or false.')
                purposes[column] = int(data[name])
        with connection() as database:
            # Tied to the session it is set up under, so signing that session out stops the reminders too (see forget_reminders).
            database.execute('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, tz, offset_minutes, created_at, session_hash, reminders, rest_alerts) '
                             'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
                             'ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth, '
                             'tz=excluded.tz, offset_minutes=excluded.offset_minutes, session_hash=excluded.session_hash',
                             (user['id'], endpoint, keys['p256dh'], keys['auth'], zone, offset, int(time.time() * 1000), session_hash(self.session_token()),
                              purposes.get('reminders', 1), purposes.get('rest_alerts', 0)))
            for column, value in purposes.items():
                database.execute(f'UPDATE push_subscriptions SET {column} = ? WHERE endpoint = ? AND user_id = ?', (value, endpoint, user['id']))
            if purposes.get('rest_alerts') == 0:
                schedule_rest_alert(endpoint, user['id'], None)
            database.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND id NOT IN '
                             '(SELECT id FROM push_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT ?)', (user['id'], user['id'], MAX_SUBSCRIPTIONS))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def push_unsubscribe(self, user):
        endpoint = self.read_json().get('endpoint')
        if not isinstance(endpoint, str):
            raise BadRequest('endpoint must be the address to stop sending to.')
        with connection() as database:
            database.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?', (user['id'], endpoint))
        schedule_rest_alert(endpoint, user['id'], None)
        self.send_json(HTTPStatus.OK, {'ok': True})

    def push_rest(self, user):
        """A rest is on the clock on a phone that is about to be locked: send it "Rest over" in `seconds` (1 to an hour), or `null` to take
        that back (the page is on screen again). For a subscription of this account that has rest alerts on, and no other."""
        data = self.read_json()
        endpoint, seconds = data.get('endpoint'), data.get('seconds')
        if not isinstance(endpoint, str):
            raise BadRequest('endpoint must be the address of this device’s subscription.')
        if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 1 <= seconds <= REST_ALERT_MAX_SECONDS):
            raise BadRequest(f'seconds must be the time left of the rest, from 1 to {REST_ALERT_MAX_SECONDS}, or null.')
        with connection() as database:
            wanted = database.execute('SELECT 1 FROM push_subscriptions WHERE user_id = ? AND endpoint = ? AND rest_alerts = 1', (user['id'], endpoint)).fetchone()
        if not wanted:
            # Taking one back is always fine; asking for one for a device that has not turned them on is not.
            if seconds is None:
                self.send_json(HTTPStatus.OK, {'ok': True})
                return
            raise BadRequest('This device has not turned on rest alerts.', HTTPStatus.NOT_FOUND)
        schedule_rest_alert(endpoint, user['id'], seconds)
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
