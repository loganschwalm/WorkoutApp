"""Headless Chrome plus a small Chrome DevTools Protocol client.

The client is deliberately synchronous: `_send` writes one command and then reads
the socket until the matching reply arrives, handling any events that turn up on
the way. That means CDP events are only processed while a command is in flight,
which is why `pause()` polls with a trivial evaluate instead of sleeping -- a
plain sleep would leave intercepted requests hanging until the next command.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import websocket

CHROME_ENV = 'WORKOUT_TEST_CHROME'

# Chrome installed for a single user (no admin rights) lives under %LOCALAPPDATA%, not Program Files.
_LOCAL_APP_DATA = os.environ.get('LOCALAPPDATA')
_PER_USER_WINDOWS = [
    os.path.join(_LOCAL_APP_DATA, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    os.path.join(_LOCAL_APP_DATA, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
] if _LOCAL_APP_DATA else []

# Checked only after the PATH lookup below, so a PATH install always wins.
_INSTALL_PATHS = {
    'win32': [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    ] + _PER_USER_WINDOWS,
    'darwin': [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ],
    'linux': [
        '/opt/google/chrome/chrome',
        '/usr/lib/chromium/chromium',
        '/usr/lib/chromium-browser/chromium-browser',
        '/snap/bin/chromium',
    ],
}
_PATH_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'microsoft-edge')


def find_chrome():
    """Locate a Chromium-family browser, or explain how to point the tests at one."""
    override = os.environ.get(CHROME_ENV)
    if override:
        if not os.path.exists(override):
            raise RuntimeError(f'{CHROME_ENV} is set to {override!r}, which does not exist.')
        return override
    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in _INSTALL_PATHS.get(sys.platform, []):
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        'No Chrome, Chromium or Edge executable found. Install one, or set '
        f'{CHROME_ENV} to its full path.'
    )


def free_port():
    """Ask the OS for an unused port. Racy in principle, fine for a local test run."""
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Chrome:
    """A headless browser process with one page target attached."""

    def __init__(self, profile_dir, window='1200,900'):
        self.port = free_port()
        command = [
            find_chrome(),
            '--headless=new',
            f'--remote-debugging-port={self.port}',
            f'--user-data-dir={profile_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-gpu',
            f'--window-size={window}',
        ]
        # Chrome refuses to start as root without this, which is the normal case in
        # containers and CI. The sandbox stays on for ordinary users.
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            command += ['--no-sandbox', '--disable-dev-shm-usage']
        self.process = subprocess.Popen(command + ['about:blank'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.target = self._await_target()
        except BaseException:
            # The constructor never returned, so nobody holds a reference to stop() this later.
            self.process.kill()
            raise

    def _await_target(self):
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f'Chrome exited immediately with code {self.process.returncode}.')
            try:
                pages = json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json', timeout=2))
                return next(page for page in pages if page['type'] == 'page')
            except Exception:
                time.sleep(0.1)
        raise RuntimeError('Chrome did not expose a debuggable page within 30s.')

    def connect(self, base_url):
        return CDP(self.target['webSocketDebuggerUrl'], base_url)

    def stop(self):
        self.process.kill()


class CDP:
    """Drives one page: evaluate JavaScript, intercept requests, capture dialogs."""

    # Native dialogs are unreliable in headless Chrome -- it can auto-dismiss one
    # before Page.handleJavaScriptDialog arrives, which silently answers "cancel".
    # Stubbing confirm/alert in the page makes the answer deterministic and reports
    # each call over the console channel.
    STUB = """(() => {
      const log = (kind, message) => console.debug('__DIALOG__' + JSON.stringify({ kind, message: String(message) }));
      window.__answer = __ANSWER__;
      window.confirm = message => { log('confirm', message); return window.__answer; };
      window.alert = message => { log('alert', message); };
      window.prompt = message => { log('prompt', message); return null; };
    })();"""

    def __init__(self, websocket_url, base_url):
        self.ws = websocket.create_connection(websocket_url, timeout=30, suppress_origin=True)
        self.base_url = base_url
        self.n = 0
        self.dialogs = []
        self.console = []
        self.block_api = False          # fail every intercepted API request
        self.block_paths = []           # fail only requests whose URL contains one of these
        self.drop_responses = 0         # discard this many successful POST responses
        self.dropped = 0
        self._answer = True
        self._stub_id = None
        self._stubs_ready = False

    # ---- dialogs ----------------------------------------------------------

    @property
    def answer(self):
        """What window.confirm returns in the page."""
        return self._answer

    @answer.setter
    def answer(self, value):
        self._answer = bool(value)
        if self._stubs_ready:
            self._install_stubs()

    def _install_stubs(self):
        if self._stub_id:
            self._send('Page.removeScriptToEvaluateOnNewDocument', identifier=self._stub_id)
        source = self.STUB.replace('__ANSWER__', 'true' if self._answer else 'false')
        self._stub_id = self._send('Page.addScriptToEvaluateOnNewDocument', source=source)['result']['identifier']
        # addScriptToEvaluateOnNewDocument only affects future documents; update the current one too.
        self._send('Runtime.evaluate', expression='window.__answer = ' + ('true' if self._answer else 'false'))

    # ---- protocol ---------------------------------------------------------

    def send(self, method, **params):
        msg = self._send(method, **params)
        if method == 'Page.enable' and not self._stubs_ready:
            self._stubs_ready = True
            self._install_stubs()
        return msg

    def _send(self, method, **params):
        self.n += 1
        mine = self.n
        self.ws.send(json.dumps({'id': mine, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('method') == 'Fetch.requestPaused':
                self._handle_paused(msg['params'])
            elif self._is_dialog_report(msg):
                self.dialogs.append(json.loads(msg['params']['args'][0]['value'][len('__DIALOG__'):])['message'])
            elif msg.get('method') in ('Runtime.consoleAPICalled', 'Runtime.exceptionThrown'):
                self.console.append(self._describe(msg))
            elif msg.get('method') == 'Page.javascriptDialogOpening':
                # Only reached if something bypasses the stub; answer it so the page never wedges.
                self.dialogs.append(msg['params']['message'])
                self.n += 1
                self.ws.send(json.dumps({'id': self.n, 'method': 'Page.handleJavaScriptDialog',
                                         'params': {'accept': self._answer}}))
            elif msg.get('id') == mine:
                return msg

    def _handle_paused(self, params):
        self.n += 1
        request_id = params['requestId']
        if 'responseStatusCode' in params:
            if self.drop_responses and params['request']['method'] == 'POST':
                self.drop_responses -= 1
                self.dropped += 1
                command, extra = 'Fetch.failRequest', {'errorReason': 'ConnectionReset'}
            else:
                command, extra = 'Fetch.continueResponse', {}
        elif self.block_api or any(path in params['request']['url'] for path in self.block_paths):
            command, extra = 'Fetch.failRequest', {'errorReason': 'InternetDisconnected'}
        else:
            command, extra = 'Fetch.continueRequest', {}
        self.ws.send(json.dumps({'id': self.n, 'method': command, 'params': {'requestId': request_id, **extra}}))

    @staticmethod
    def _is_dialog_report(msg):
        if msg.get('method') != 'Runtime.consoleAPICalled':
            return False
        args = msg['params'].get('args') or []
        return bool(args) and str(args[0].get('value', '')).startswith('__DIALOG__')

    @staticmethod
    def _describe(msg):
        params = msg['params']
        kind = msg['method'].split('.')[1]
        if 'args' in params:
            body = ' '.join(str(a.get('value', a.get('description', ''))) for a in params['args'])
        else:
            details = params['exceptionDetails']
            body = details.get('exception', {}).get('description', details.get('text', ''))
        return f'{kind}: {body}'

    # ---- page helpers -----------------------------------------------------

    def ev(self, expression):
        """Evaluate JavaScript and return the value. Raises RuntimeError if the page threw."""
        msg = self.send('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        result = msg.get('result', {})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'].get('exception', {}).get('description', 'eval error'))
        return result.get('result', {}).get('value')

    def wait(self, expression, timeout=8):
        """Poll until the expression is truthy. Errors count as not-yet-true."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.ev(expression):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.1)
        return False

    def pause(self, seconds):
        """Let the page run. Keeps the CDP event pump turning (see module docstring)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.ev('1')
            time.sleep(0.1)

    def goto(self, path):
        self.send('Page.navigate', url=self.base_url + path)
        time.sleep(0.4)
        self.wait("document.readyState === 'complete'")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
