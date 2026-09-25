"""Runs backend/server.py against a throwaway database and talks to its API."""

import http.client
import json
import os
import subprocess
import sys
import time

from .browser import free_port

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AppServer:
    """The real application server, on its own port with an empty database."""

    def __init__(self, db_path, frontend_dir=None, env=None):
        self.port = free_port()
        self.base_url = f'http://127.0.0.1:{self.port}'
        # Mail settings from the shell are left out, so a test server can only email the sink a suite gives it.
        inherited = {name: value for name, value in os.environ.items() if not name.startswith('SMTP_')}
        self.env = dict(
            inherited,
            PORT=str(self.port),
            WORKOUT_DB=db_path,
            APP_ROOT=frontend_dir or os.path.join(REPO_ROOT, 'frontend'),
            **(env or {}),
        )
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(REPO_ROOT, 'backend', 'server.py')],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._await_ready()
        except BaseException:
            # The constructor never returned, so nobody holds a reference to stop() this later.
            self.process.kill()
            raise

    def admin(self, *args, stdin='', env=None):
        """Run one of server.py's account commands on this server's database, as an admin would while it runs.

        `stdin` is what is typed; a password is read from its first line. `env` overrides this server's environment.
        Returns (exit status, stdout, stderr).
        """
        result = subprocess.run([sys.executable, os.path.join(REPO_ROOT, 'backend', 'server.py'), *args],
                                env={**self.env, **(env or {})}, input=stdin, capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def _await_ready(self):
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f'Server exited immediately with code {self.process.returncode}.')
            try:
                self.api('GET', '/api/auth/me')
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f'Server did not answer on port {self.port} within 15s.')

    def api(self, method, path, body=None, token=None):
        """Call the API directly, bypassing the browser. Returns (parsed body, Set-Cookie)."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Cookie'] = f'session={token}'
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        data = response.read()
        cookie = response.getheader('Set-Cookie')
        conn.close()
        return (json.loads(data) if data else None), cookie

    def request(self, method, path, body=None, headers=None, token=None):
        """Send exactly these bytes and headers. Returns (status, headers, parsed JSON or raw bytes).

        For requests the app itself would never make: malformed bodies, odd headers, oversized uploads.
        """
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = dict(headers or {})
        if token:
            headers['Cookie'] = f'session={token}'
        conn.putrequest(method, path)
        if body is not None and 'Content-Length' not in headers:
            headers['Content-Length'] = str(len(body))
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders()
        if body:
            conn.send(body)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = data
        return response.status, {k.lower(): v for k, v in response.getheaders()}, parsed

    def raw(self, method, path):
        """A request with no session cookie, for checking redirects and status codes."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path)
        response = conn.getresponse()
        status, location = response.status, response.getheader('Location')
        response.read()
        conn.close()
        return status, location

    def stop(self):
        self.process.kill()
