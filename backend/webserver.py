"""The web server: the handler every request goes through, and serve(), which starts it."""

import datetime
import email.utils
import gzip
import http.server
import io
import json
import os
import re
import signal
import threading
import time
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import quote, unquote, urlparse

from accounts import check_mail_settings
from api_accounts import AccountApi
from api_data import DataApi
from api_push import PushApi
from api_routes import find_route
from config import (
    COMPRESSIBLE, MAX_BODY, MIN_COMPRESS, RANGED, REQUEST_TIMEOUT, ROOT, SECURE_COOKIES, SECURITY_HEADERS, SESSION_RENEW,
    SESSION_TTL, SHORT_SESSION_RENEW, SHORT_SESSION_TTL, SMTP_HOST, SMTP_PORT, SMTP_SECURITY
)
from database import connection, init_database, session_hash
from validation import BadRequest
from webpush import reminder_loop


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


class WebHandler(http.server.SimpleHTTPRequestHandler):
    """The web side of the server: static files (gzipped for a browser that takes it, ranged for video), JSON in and out, the session cookie
    and who is signed in, and the route table's dispatch. What each API request does is in the mixins AppHandler adds (api_*.py)."""

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

    def handle_api(self):
        """Answers a request for /api/...: from this site, then by the route table (api_routes.py): the method it names, with the signed-in account
        unless the route is for anyone; a request no route has is for no one, and is told there is nothing there once it is known who asks."""
        try:
            # The session cookie is SameSite=Lax, which keeps it off requests from other sites, but not from other pages
            # on the same one: another port on this address, or another subdomain behind the same proxy. Browsers say
            # where a request came from, so a change asked for by any page but this site's own is refused.
            if self.command != 'GET' and self.headers.get('Sec-Fetch-Site', '').strip().lower() in ('same-site', 'cross-site'):
                raise BadRequest('Changes can only be made from this site.', HTTPStatus.FORBIDDEN)
            handler, public = find_route(self.command, self.api_path)
            if public:
                getattr(self, handler)()
                return
            user = self.require_user()
            if not user:
                return
            if handler is None:
                self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Endpoint not found.'})
                return
            getattr(self, handler)(user)
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
            self.api_path = parsed.path
            self.handle_api()
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

    def answer_api(self):
        """POST, PUT, PATCH and DELETE: the API's, and nothing else is answered."""
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            self.api_path = parsed.path
            self.handle_api()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    do_POST = do_PUT = do_PATCH = do_DELETE = answer_api


class AppHandler(AccountApi, DataApi, PushApi, WebHandler):
    """Every request: the web side (WebHandler) and what each endpoint does (the Api mixins), which the route table (api_routes.py) joins up."""


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
