"""Account endpoints (see api_routes.py for which request each answers)."""

import re
import secrets
import threading
import time
from http import HTTPStatus

from accounts import (
    DUMMY_HASH, address_throttle, device_label, email_address, email_reset_code, find_account, login_throttle, needs_rehash, new_password,
    new_username, password_hash, password_matches, public_user, register_throttle, reset_address_throttle, reset_code_hash,
    reset_daily_throttle, reset_guess_throttle, reset_throttle, wait_words
)
from config import ALLOW_REGISTRATION, RESET_CODE_ATTEMPTS, RESET_CODE_TTL, SESSION_TTL, SHORT_SESSION_TTL, SMTP_HOST
from database import connection, delete_account_rows, forget_reminders, session_hash
from validation import BadRequest, text


class AccountApi:
    """The endpoints of accounts: signing up and in and out, resetting a password by email, and changing the email or password or deleting the account."""

    def auth_me(self):
        user = self.session_user()
        self.send_json(HTTPStatus.OK, {'user': user, 'registrationOpen': ALLOW_REGISTRATION, 'passwordReset': bool(SMTP_HOST)})

    def sign_out(self):
        token = self.session_token()
        if token:
            with connection() as database:
                user = database.execute('SELECT user_id FROM sessions WHERE token = ?', (session_hash(token),)).fetchone()
                database.execute('DELETE FROM sessions WHERE token = ?', (session_hash(token),))
                if user:
                    # Reminders set up under this session go with it.
                    forget_reminders(database, user['user_id'], session_hash(token))
        # The workouts are kept by the browser between visits (see GET /api/workouts), so signing out clears them, on a
        # browser that understands this (Safari does not) and over HTTPS or localhost, the only places it is honoured.
        self.send_json(HTTPStatus.OK, {'ok': True}, [self.session_cookie('', 0)], headers={'Clear-Site-Data': '"cache"'})

    def start_session(self, database, user_id, remember=True):
        """Sign this account in: a new session, and the cookie that carries it. One that is not remembered ends when the
        browser closes, or after SHORT_SESSION_TTL without use."""
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        lifetime = SESSION_TTL if remember else SHORT_SESSION_TTL
        database.execute('DELETE FROM sessions WHERE expires_at <= ?', (now,))
        database.execute('INSERT INTO sessions (token, user_id, expires_at, remember, created_at, last_used, label, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (session_hash(token), user_id, now + lifetime, int(remember), now, now, device_label(self.headers.get('User-Agent')), self.client_ip()))
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
        address = self.client_ip()
        # Asked before anything is looked up or hashed, so a script gets nothing for its tries, and counted when an account is made.
        wait = register_throttle.retry_after(address) if register_throttle else 0
        if wait:
            self.send_wait(wait, 'Too many accounts have been made from this address.')
            return
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
        if register_throttle:
            register_throttle.record(address)
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
            address = self.client_ip()
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
        # Each limit counts every request, whether or not an account uses the address, so none of them says which do. The one
        # for this client address comes first: it is the one a person spraying addresses meets, and says so.
        address = self.client_ip()
        wait = reset_address_throttle.retry_after(address) if reset_address_throttle else 0
        if wait:
            self.send_wait(wait, 'Too many codes asked for from this address.')
            return
        wait = max(reset_throttle.retry_after(email), reset_daily_throttle.retry_after(email))
        if wait:
            self.send_wait(wait, 'Too many codes asked for.')
            return
        reset_throttle.record(email)
        reset_daily_throttle.record(email)
        if reset_address_throttle:
            reset_address_throttle.record(address)
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
            # Whoever knew the old password is signed out everywhere, and no phone is left with reminders for an account it is not signed in to.
            database.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
            database.execute('DELETE FROM push_subscriptions WHERE user_id = ?', (user['id'],))
            cookie = self.start_session(database, user['id'])
        reset_guess_throttle.clear(email)
        login_throttle.clear((self.client_ip(), user['username'].lower()))
        self.send_json(HTTPStatus.OK, {'user': public_user(user)}, [cookie])

    def confirm_password(self, database, user, password, wrong='That password is not right.'):
        """Check the signed-in account's password, asked again before a change only its owner should make: a signed-in
        page may not be its owner's. Wrong ones count as failed sign-ins, and the same wait applies."""
        throttle_key = (self.client_ip(), user['username'].lower())
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
            signed_out = self.sign_out_others_rows(database, user)
            database.execute('DELETE FROM password_resets WHERE user_id = ?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'signedOut': signed_out})

    def sign_out_others_rows(self, database, user):
        """Ends every session of the account but this one, and the reminders set up under them. How many sessions it ended."""
        current = session_hash(self.session_token())
        forget_reminders(database, user['id'], keep=current)
        return database.execute('DELETE FROM sessions WHERE user_id = ? AND token != ?', (user['id'], current)).rowcount

    def list_sessions(self, user):
        """The devices signed in to this account: its sessions that have not run out, the one asking marked."""
        current = session_hash(self.session_token())
        with connection() as database:
            rows = database.execute('SELECT rowid AS id, token, created_at, last_used, label, address, remember FROM sessions '
                                    'WHERE user_id = ? AND expires_at > ? ORDER BY last_used DESC, rowid DESC', (user['id'], int(time.time()))).fetchall()
        # Times in milliseconds, as the pages count them; none for a session from before they were kept.
        self.send_json(HTTPStatus.OK, {'sessions': [
            {'id': row['id'], 'label': row['label'], 'address': row['address'], 'createdAt': row['created_at'] * 1000 or None,
             'lastUsed': row['last_used'] * 1000 or None, 'remembered': bool(row['remember']), 'current': row['token'] == current}
            for row in rows]})

    def revoke_session(self, user):
        """Signs one of the account's other devices out. Asking again for one already gone is fine: nothing is left to do."""
        wanted = self.read_json().get('id')
        if isinstance(wanted, bool) or not isinstance(wanted, int):
            raise BadRequest('id must be the id of a signed-in device.')
        with connection() as database:
            row = database.execute('SELECT token FROM sessions WHERE rowid = ? AND user_id = ?', (wanted, user['id'])).fetchone()
            if row and row['token'] == session_hash(self.session_token()):
                raise BadRequest('That is the device you are using. Use Sign out for it.')
            if row:
                database.execute('DELETE FROM sessions WHERE token = ?', (row['token'],))
                forget_reminders(database, user['id'], row['token'])
        self.send_json(HTTPStatus.OK, {'signedOut': 1 if row else 0})

    def sign_out_others(self, user):
        with connection() as database:
            signed_out = self.sign_out_others_rows(database, user)
        self.send_json(HTTPStatus.OK, {'signedOut': signed_out})

    def delete_account(self, user):
        password = self.read_json().get('password')
        with connection() as database:
            self.confirm_password(database, user, password)
            delete_account_rows(database, user['id'])
        print(f"Deleted the account {user['username']} at its owner's request.", flush=True)
        self.send_json(HTTPStatus.OK, {'ok': True}, [self.session_cookie('', 0)])
