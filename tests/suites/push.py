"""Web push, without a browser: the cryptography checked against known answers, subscriptions and the test notification
against a push service of the suite's own, and the reminders the server sends on training days."""

import datetime
import hashlib
import http.server
import importlib.util
import json
import os
import secrets
import sqlite3
import threading
import time

from ..harness import REPO_ROOT, free_port

INTERCEPT = False
BROWSER = False

ACCOUNT_PASSWORD = 'chalk-and-plates-42'
DAY_MS = 86400000


class PushService(http.server.ThreadingHTTPServer):
    """What a browser maker's push service is to the app: takes a POST at an address, and answers with a status. Every
    request is kept, and `answers` says what to answer for an address (a list, used up one by one, then 201)."""

    def __init__(self):
        super().__init__(('127.0.0.1', free_port()), PushHandler)
        self.received = []
        self.answers = {}
        self.lock = threading.Lock()
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def to(self, name):
        with self.lock:
            return [item for item in self.received if item['path'] == f'/push/{name}']


def load_server():
    """backend/server.py as a module, for the functions that check what it sends."""
    spec = importlib.util.spec_from_file_location('push_server', os.path.join(REPO_ROOT, 'backend', 'server.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decrypt_message(server, body, receiver_private, receiver_public, auth):
    """A message read as the browser reads it (RFC 8188 and 8291), or an assertion error if it was not for this key."""
    salt, size, length = body[:16], int.from_bytes(body[16:20], 'big'), body[20]
    sender_public, sealed = body[21:21 + length], body[21 + length:]
    assert size == 4096 and length == 65 and len(sealed) <= size
    shared = server.ec_multiply(receiver_private, server.decode_point(sender_public))[0].to_bytes(32, 'big')
    material = server.hkdf(auth, shared, b'WebPush: info\0' + receiver_public + sender_public, 32)
    key, nonce = server.hkdf(salt, material, b'Content-Encoding: aes128gcm\0', 16), server.hkdf(salt, material, b'Content-Encoding: nonce\0', 12)
    round_keys = server.aes_round_keys(key)
    assert server.gcm_tag(round_keys, nonce, sealed[:-16]) == sealed[-16:], 'the tag does not match'
    record = server.gcm_keystream_xor(round_keys, nonce, sealed[:-16])
    assert record.endswith(b'')
    return record[:-1]


class PushHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        with self.server.lock:
            self.server.received.append({'path': self.path, 'headers': {k.lower(): v for k, v in self.headers.items()}, 'body': body})
            answers = self.server.answers.get(self.path, [])
            status = answers.pop(0) if answers else 201
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *args):
        pass


def run(t):
    check = t.check

    server = load_server()

    def b64(value):
        return server.b64url(value)

    # ------------------------------------------------------------------ K the cryptography
    print('K   the cryptography, against known answers')
    check('the generator is on the curve', server.ec_on_curve(*server.P256_G))
    check('and the group has the order it should', server.ec_multiply(server.P256_N) is None)
    check('twice the generator is the point NIST lists', server.ec_multiply(2) == (
        0x7CF27B188D034F7E8A52380304B51AC3C08969E277F21B35A60B48FC47669978, 0x07775510DB8ED040293D9AC69F7430DBBA7DADE63CE982299E04B79D227873D1))
    check('a point not on the curve is refused', not server.ec_on_curve(1, 1) and server.ec_on_curve(server.P256_G[0] + 1, server.P256_G[1]) is False)
    a, b = secrets.randbelow(server.P256_N - 1) + 1, secrets.randbelow(server.P256_N - 1) + 1
    check('two keys reach the same shared secret from each other’s public key',
          server.ec_multiply(a, server.ec_multiply(b))[0] == server.ec_multiply(b, server.ec_multiply(a))[0])
    check('the S-box starts as AES’s does', [server.AES_SBOX[i] for i in (0, 1, 0x53, 255)] == [0x63, 0x7c, 0xed, 0x16])
    check('AES-GCM: the key, IV and empty text of NIST’s first test case give its tag',
          server.aes_gcm_seal(bytes(16), bytes(12), b'').hex() == '58e2fccefa7e3061367f1d57a4e7455a')
    check('and its second case gives its ciphertext and tag',
          server.aes_gcm_seal(bytes(16), bytes(12), bytes(16)).hex() == '0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf')
    check('HKDF gives RFC 5869’s first test case', server.hkdf(bytes.fromhex('000102030405060708090a0b0c'), bytes.fromhex('0b' * 22),
          bytes.fromhex('f0f1f2f3f4f5f6f7f8f9'), 42).hex() == '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865')
    # The example in RFC 8291's appendix: a message to a browser, with the keys and salt it used.
    message = server.encrypt_push_payload(b'When I grow up, I want to be a watermelon', server.b64url_decode(
        'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4'), server.b64url_decode('BTBZMqHH6r4Tts7J_aSIgg'),
        sender_private=int.from_bytes(server.b64url_decode('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), salt=server.b64url_decode('DGv6ra1nlYgDCS1FRnbzlw'))
    check('the message in RFC 8291’s appendix comes out as it does there', b64(message) == 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')

    def add(first, second):
        """Two affine points added, for checking signatures."""
        x, y, z = server.ec_add((*first, 1), (*second, 1))
        inverse = pow(z, -1, server.P256_P)
        return x * inverse * inverse % server.P256_P, y * inverse ** 3 % server.P256_P

    def verifies(public, signed, signature):
        """An ES256 signature checked the long way, apart from the code that made it."""
        r, s = int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')
        if not (0 < r < server.P256_N and 0 < s < server.P256_N):
            return False
        z, w = int.from_bytes(hashlib.sha256(signed).digest(), 'big'), pow(s, -1, server.P256_N)
        point = add(server.ec_multiply(z * w % server.P256_N), server.ec_multiply(r * w % server.P256_N, public))
        return point[0] % server.P256_N == r

    private = secrets.randbelow(server.P256_N - 1) + 1
    public = server.ec_multiply(private)
    signature = server.ecdsa_sign(private, b'a message')
    check('an ES256 signature checks out against the public key', verifies(public, b'a message', signature))
    check('and not for another message, or another key', not verifies(public, b'another message', signature) and not verifies(server.ec_multiply(private + 1), b'a message', signature))

    def decrypt(body, receiver_private, receiver_public, auth):
        return decrypt_message(server, body, receiver_private, receiver_public, auth)

    receiver = secrets.randbelow(server.P256_N - 1) + 1
    receiver_public, auth = server.encode_point(*server.ec_multiply(receiver)), secrets.token_bytes(16)
    sealed = server.encrypt_push_payload(b'{"title":"Hi"}', receiver_public, auth)
    check('a message is read by the key it was made for', decrypt(sealed, receiver, receiver_public, auth) == b'{"title":"Hi"}')
    check('and each one has a key and salt of its own', server.encrypt_push_payload(b'{"title":"Hi"}', receiver_public, auth)[:16] != sealed[:16])
    try:
        decrypt(sealed, receiver + 1, receiver_public, auth)
        read = True
    except AssertionError:
        read = False
    check('but not by another', not read)
    try:
        server.encrypt_push_payload(b'x' * 4100, receiver_public, auth)
        refused = False
    except ValueError:
        refused = True
    check('one too long for a push message is refused', refused)

    allowed = server.push_endpoint_allowed
    check('the browser makers’ push services are allowed over https', all(allowed(url) for url in (
        'https://fcm.googleapis.com/fcm/send/abc', 'https://updates.push.services.mozilla.com/wpush/v2/abc', 'https://web.push.apple.com/abc', 'https://wns2.notify.windows.com/w/?token=x')))
    check('and nothing else is: another host, plain http, another port, a look-alike host, an address with a login, a private address',
          not any(allowed(url) for url in ('https://evil.example/x', 'http://fcm.googleapis.com/x', 'https://fcm.googleapis.com:8443/x', 'https://fcm.googleapis.com.evil.example/x', 'https://storage.googleapis.com/a-bucket/x', 'https://googleapis.com/x',
                                           'https://user@fcm.googleapis.com/x', 'https://fcm.googleapis.com@evil.example/x', 'https://192.168.1.5/x', 'https://127.0.0.1/x', 'ftp://fcm.googleapis.com/x', '', 'https:///x')))
    now = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo('America/Chicago')
        zones = True
    except Exception:
        zones = False
    if zones:
        check('a phone’s time zone is used, summer and winter', server.device_clock({'tz': 'America/Chicago', 'offset_minutes': 0}, now).hour == 7
              and server.device_clock({'tz': 'America/Chicago', 'offset_minutes': 0}, now.replace(month=1)).hour == 6)
    check('and the offset it last gave when the server does not know that zone', server.device_clock({'tz': 'Not/AZone', 'offset_minutes': -300}, now).hour == 7
          and server.device_clock({'tz': '', 'offset_minutes': 90}, now).minute == 30)

    # ------------------------------------------------------------------ S subscriptions
    print('S   subscriptions and the test notification')
    service = PushService()
    host = f'http://127.0.0.1:{service.server_address[1]}'
    app = t.start_server('push.db', {'PUSH_ALLOWED_HOSTS': '127.0.0.1', 'REMINDER_TICK_SECONDS': '0.4'})
    db_path = t.db_path('push.db')

    def signed_up(name):
        return app.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': ACCOUNT_PASSWORD})[1].split('session=')[1].split(';')[0]

    def post(path, body, token):
        status, _, reply = app.request('POST', path, json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=token)
        return status, reply

    def database(sql, *args):
        db = sqlite3.connect(db_path)
        try:
            rows = db.execute(sql, args).fetchall()
            db.commit()
            return rows
        finally:
            db.close()

    class Phone:
        """A browser's subscription: a name at the push service, and the keys that go with it."""

        def __init__(self, name, offset=0, zone=''):
            self.name, self.offset, self.zone = name, offset, zone
            self.private = secrets.randbelow(server.P256_N - 1) + 1
            self.public = server.encode_point(*server.ec_multiply(self.private))
            self.auth = secrets.token_bytes(16)
            self.endpoint = f'{host}/push/{name}'

        def body(self, **changes):
            return {'endpoint': self.endpoint, 'keys': {'p256dh': b64(self.public), 'auth': b64(self.auth)}, 'timeZone': self.zone, 'utcOffset': self.offset, **changes}

        def subscribe(self, token):
            return post('/api/push/subscribe', self.body(), token)

        def messages(self):
            return [json.loads(decrypt(item['body'], self.private, self.public, self.auth)) for item in service.to(self.name)]

    owner, other = signed_up('lifter'), signed_up('another')
    status, _, _ = app.request('GET', '/api/push/key')
    check('the server’s key is for those signed in', status == 401, status)
    key = app.api('GET', '/api/push/key', token=owner)[0]['publicKey']
    check('it is a P-256 public key, which stays the same', server.decode_point(server.b64url_decode(key)) is not None and app.api('GET', '/api/push/key', token=owner)[0]['publicKey'] == key and len(key) == 87, key)
    check('and is kept in the database', database("SELECT COUNT(*) FROM server_keys WHERE name = 'vapid'")[0][0] == 1)

    phone = Phone('phone')
    check('signed out, a subscription is refused', app.request('POST', '/api/push/subscribe', json.dumps(phone.body()).encode(), {'Content-Type': 'application/json'})[0] == 401)
    problems = {
        'a push service that is not allowed': phone.body(endpoint='https://evil.example/push/abc'),
        'no endpoint': {k: v for k, v in phone.body().items() if k != 'endpoint'},
        'an endpoint that is not text': phone.body(endpoint=5),
        'no keys': {k: v for k, v in phone.body().items() if k != 'keys'},
        'a key that is not on the curve': phone.body(keys={'p256dh': b64(b'\x04' + bytes(64)), 'auth': b64(phone.auth)}),
        'a key of the wrong length': phone.body(keys={'p256dh': b64(phone.public[:40]), 'auth': b64(phone.auth)}),
        'an auth secret of the wrong length': phone.body(keys={'p256dh': b64(phone.public), 'auth': b64(phone.auth[:8])}),
        'keys that are not base64': phone.body(keys={'p256dh': '!!!', 'auth': 'a b'}),
        'a time zone that is not text': phone.body(timeZone=5),
        'an offset that is not minutes': phone.body(utcOffset='UTC'),
        'an offset of more than a day': phone.body(utcOffset=1441),
        'a true offset': phone.body(utcOffset=True),
    }
    for name, body in problems.items():
        status, reply = post('/api/push/subscribe', body, owner)
        check(f'{name} is refused', status == 400 and reply.get('error'), f'{status} {reply}')
    check('and none of them was kept', database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 0)
    check('a good one is kept, with the phone’s clock', phone.subscribe(owner)[0] == 200
          and database('SELECT endpoint, tz, offset_minutes FROM push_subscriptions') == [(phone.endpoint, '', 0)])
    check('and asking again updates it rather than adding another', post('/api/push/subscribe', phone.body(timeZone='America/Chicago', utcOffset=-300), owner)[0] == 200
          and database('SELECT tz, offset_minutes FROM push_subscriptions') == [('America/Chicago', -300)])
    phone.zone, phone.offset = '', 0
    phone.subscribe(owner)

    status, reply = post('/api/push/test', {}, owner)
    check('a test notification reaches the phone', status == 200 and reply == {'devices': 1, 'sent': 1, 'forgotten': 0, 'failed': 0}, f'{status} {reply}')
    got = service.to('phone')
    check('as one message', len(got) == 1, len(got))
    headers = got[0]['headers']
    check('encrypted for it, with a lifetime', headers.get('content-encoding') == 'aes128gcm' and headers.get('content-type') == 'application/octet-stream'
          and int(headers.get('ttl', 0)) > 0, headers)
    check('which can read it', phone.messages() == [{'title': 'Workout Tracker', 'body': 'Reminders work on this device.', 'url': '/index.html', 'tag': 'test'}], phone.messages())
    scheme, _, rest = headers['authorization'].partition(' ')
    fields = dict(part.strip().split('=', 1) for part in rest.split(','))
    token_text = fields['t']
    header_part, claims_part, signature_part = token_text.split('.')
    claims = json.loads(server.b64url_decode(claims_part))
    check('and signed as the server, by the key it gave out', scheme == 'vapid' and fields['k'] == key and json.loads(server.b64url_decode(header_part)) == {'typ': 'JWT', 'alg': 'ES256'}
          and verifies(server.decode_point(server.b64url_decode(key)), f'{header_part}.{claims_part}'.encode(), server.b64url_decode(signature_part)), headers['authorization'][:80])
    check('for the push service it was sent to, for under a day, from someone who can be reached', claims['aud'] == host and 0 < claims['exp'] - time.time() <= 24 * 3600
          and claims['sub'].startswith('mailto:'), claims)
    status, reply = post('/api/push/test', {}, owner)
    check('another test at once is asked to wait', status == 429 and 'Wait' in reply.get('error', ''), f'{status} {reply}')
    check('a different account is not held up by it, and has no phones to send to', post('/api/push/test', {}, other) == (200, {'devices': 0, 'sent': 0, 'forgotten': 0, 'failed': 0}))

    time.sleep(3.1)
    service.answers['/push/phone'] = [500]
    status, reply = post('/api/push/test', {}, owner)
    check('a push service that fails leaves the phone subscribed, and says so', status == 200 and reply['failed'] == 1 and reply['sent'] == 0
          and database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 1, f'{status} {reply}')
    time.sleep(3.1)
    service.answers['/push/phone'] = [410]
    status, reply = post('/api/push/test', {}, owner)
    check('one that says the phone is gone (410) has it forgotten', status == 200 and reply['forgotten'] == 1 and database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 0, f'{status} {reply}')
    phone.subscribe(owner)
    time.sleep(3.1)
    service.answers['/push/phone'] = [404]
    check('and so does a 404', post('/api/push/test', {}, owner)[1]['forgotten'] == 1 and database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 0)

    phone.subscribe(owner)
    check('Stop sending removes it', post('/api/push/unsubscribe', {'endpoint': phone.endpoint}, owner)[0] == 200 and database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 0)
    check('and doing it again is no trouble', post('/api/push/unsubscribe', {'endpoint': phone.endpoint}, owner)[0] == 200)
    check('an endpoint is needed to stop', post('/api/push/unsubscribe', {}, owner)[0] == 400)
    phone.subscribe(owner)
    post('/api/push/unsubscribe', {'endpoint': phone.endpoint}, other)
    check('another account cannot remove it', database('SELECT COUNT(*) FROM push_subscriptions')[0][0] == 1)
    check('but signing in on the same browser and subscribing moves it to that account', phone.subscribe(other)[0] == 200
          and database('SELECT COUNT(*) FROM push_subscriptions WHERE user_id = (SELECT id FROM users WHERE username = ?)', 'another')[0][0] == 1)
    for index in range(12):
        Phone(f'many{index}').subscribe(other)
    kept = [row[0] for row in database('SELECT endpoint FROM push_subscriptions WHERE user_id = (SELECT id FROM users WHERE username = ?) ORDER BY id', 'another')]
    check('an account keeps its 10 newest subscriptions', len(kept) == 10 and kept[-1].endswith('many11') and not any(url.endswith('/phone') for url in kept), kept)
    mallory = signed_up('leaver')
    Phone('leaving').subscribe(mallory)
    status, _ = post('/api/account/delete', {'password': ACCOUNT_PASSWORD}, mallory)
    check('deleting an account deletes its subscriptions', status == 200 and database("SELECT COUNT(*) FROM push_subscriptions WHERE endpoint LIKE '%/leaving'")[0][0] == 0, status)

    # ------------------------------------------------------------------ V the schedule
    print('V   the schedule in the account’s settings')

    def put_schedule(schedule, token):
        status, _, reply = app.request('PUT', '/api/state', json.dumps({'settings': {'schedule': schedule}}).encode(), {'Content-Type': 'application/json'}, token=token)
        return status, reply

    check('days and a time are kept', put_schedule({'days': [1, 3, 5], 'time': '06:30'}, owner)[0] == 200
          and app.api('GET', '/api/state', token=owner)[0]['settings']['schedule'] == {'days': [1, 3, 5], 'time': '06:30'})
    check('no days is a schedule too, and the time may be left out', put_schedule({'days': []}, owner)[0] == 200 and put_schedule({'days': [0, 6]}, owner)[0] == 200)
    for name, schedule in {'a schedule that is not an object': [1, 2], 'a day that is not a number': {'days': ['Mon']}, 'a day past Saturday': {'days': [7]},
                           'a day before Sunday': {'days': [-1]}, 'a day written twice': {'days': [1, 1]}, 'a true for a day': {'days': [True]},
                           'days that are not a list': {'days': 3}, 'more than seven days': {'days': [0, 1, 2, 3, 4, 5, 6, 0]},
                           'an hour of 24': {'days': [1], 'time': '24:00'}, 'minutes of 60': {'days': [1], 'time': '10:60'}, 'a time with no leading zero': {'days': [1], 'time': '9:00'},
                           'a time that is a number': {'days': [1], 'time': 900}}.items():
        status, reply = put_schedule(schedule, owner)
        check(f'{name} is refused', status == 400 and 'schedule' in reply.get('error', ''), f'{status} {reply}')
    check('and the one that was kept is still there', app.api('GET', '/api/state', token=owner)[0]['settings']['schedule'] == {'days': [0, 6]})
    status, _, reply = app.request('PATCH', '/api/state', json.dumps({'settings': {'value': {'schedule': {'days': [9]}}}}).encode(), {'Content-Type': 'application/json'}, token=owner)
    check('a change from another device is checked the same way', status == 400, status)

    # ------------------------------------------------------------------ R reminders
    print('R   reminders on training days')

    def device_now(offset):
        return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=offset)

    def midday_offset():
        """An offset that puts the phone's clock near midday, whatever time it is here, so a time earlier or later on the same
        day is always available."""
        utc = datetime.datetime.now(datetime.timezone.utc)
        return 720 - (utc.hour * 60 + utc.minute)

    def hhmm(minutes):
        return f'{minutes // 60:02d}:{minutes % 60:02d}'

    def local_minutes(offset):
        local = device_now(offset)
        return local.hour * 60 + local.minute

    def today_number(offset):
        return (device_now(offset).weekday() + 1) % 7

    def wait_until(condition, timeout=6):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.1)
        return False

    offset = midday_offset()
    now_minutes = local_minutes(offset)
    today = today_number(offset)
    others = [day for day in range(7) if day != today]

    def workout(token, created_at):
        post('/api/workouts', {'name': 'Workout', 'notes': '', 'createdAt': created_at, 'exercises': [{'name': 'Bench Press', 'weight': 100, 'reps': 5, 'sets': [{'reps': 5, 'weight': 100}]}]}, token)

    def account(name, days, minutes, zone='', trained_at=None):
        """An account that trains on these days and is reminded from this time, with a phone; a workout it saved first, if it saved one."""
        token = signed_up(name)
        if trained_at is not None:
            workout(token, trained_at)
        put_schedule({'days': days, 'time': hhmm(minutes)}, token)
        phone = Phone(name, offset, zone)
        phone.subscribe(token)
        return token, phone

    ready_token, ready = account('ready', [today], now_minutes - 1)
    _, wrong_day = account('wrongday', others, now_minutes - 1)
    _, too_early = account('tooearly', [today], now_minutes + 60)
    _, late = account('tardy', [today], now_minutes - 120)
    _, too_late = account('missed', [today], now_minutes - 240)
    _, trained = account('trained', [today], now_minutes - 1, trained_at=int(time.time() * 1000))
    _, silent = account('silent', [], now_minutes - 1)
    _, yesterday = account('yesterday', [today], now_minutes - 1, trained_at=int(time.time() * 1000) - 36 * 3600 * 1000)
    # A phone that is asked, and does not answer in time: the next look tries again.
    service.answers['/push/retry'] = [500, 500]
    service.answers['/push/gone'] = [410]
    retry_token, retrying = account('retry', [today], now_minutes - 1)
    gone_token, gone = account('gone', [today], now_minutes - 1)

    check('on a training day, from the time chosen, the phone is reminded', wait_until(lambda: len(ready.messages()) >= 1), len(service.received))
    reminder = ready.messages()[0]
    check('with a message that opens the app', reminder == {'title': 'Time to train', 'body': 'Today is a training day. Tap to open Workout Tracker.', 'url': '/index.html', 'tag': 'training-day'}, reminder)
    check('and signed for this server, like any other', service.to('ready')[0]['headers']['authorization'].endswith(f'k={key}'))
    wait_until(lambda: len(retrying.messages()) >= 3)
    time.sleep(1.5)
    check('once that day, however often the server looks', len(ready.messages()) == 1, len(ready.messages()))
    check('and the day is remembered, by the phone’s own clock', database("SELECT last_sent FROM push_subscriptions WHERE endpoint LIKE '%/ready'")[0][0] == device_now(offset).date().isoformat())
    check('not on a day it is not training', wrong_day.messages() == [] and silent.messages() == [])
    check('not before the time', too_early.messages() == [])
    check('late by an hour or two is still worth it', len(late.messages()) == 1, len(late.messages()))
    check('but not by four', too_late.messages() == [], len(too_late.messages()))
    check('not after a workout is saved that day', trained.messages() == [], len(trained.messages()))
    check('though one from the day before is no reason not to', len(yesterday.messages()) == 1, len(yesterday.messages()))
    check('a push service that fails is tried again on the next look, until it takes it', len(retrying.messages()) == 3, len(retrying.messages()))
    check('and one that says the phone is gone has it forgotten', wait_until(lambda: database("SELECT COUNT(*) FROM push_subscriptions WHERE endpoint LIKE '%/gone'")[0][0] == 0))
    database("UPDATE push_subscriptions SET last_sent = '2000-01-01' WHERE endpoint LIKE '%/ready'")
    check('the next training day it is reminded again', wait_until(lambda: len(ready.messages()) == 2), len(ready.messages()))
    put_schedule({'days': [], 'time': hhmm(now_minutes - 1)}, ready_token)
    database("UPDATE push_subscriptions SET last_sent = '2000-01-01' WHERE endpoint LIKE '%/ready'")
    time.sleep(1.5)
    check('and with the days taken away, not at all', len(ready.messages()) == 2, len(ready.messages()))
    put_schedule({'days': [today], 'time': hhmm(now_minutes - 1)}, ready_token)
    time.sleep(1.5)
    check('and with them put back, it carries on', len(ready.messages()) == 3, len(ready.messages()))
    check('no page of the app sees any of it: the server stays up throughout', app.api('GET', '/api/auth/me')[0] is not None)
