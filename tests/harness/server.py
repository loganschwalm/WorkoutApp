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

    def __init__(self, db_path, frontend_dir=None):
        self.port = free_port()
        self.base_url = f'http://127.0.0.1:{self.port}'
        env = dict(
            os.environ,
            PORT=str(self.port),
            WORKOUT_DB=db_path,
            APP_ROOT=frontend_dir or os.path.join(REPO_ROOT, 'frontend'),
        )
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(REPO_ROOT, 'backend', 'server.py')],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._await_ready()
        except BaseException:
            # The constructor never returned, so nobody holds a reference to stop() this later.
            self.process.kill()
            raise

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
