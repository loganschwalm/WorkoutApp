"""The Content-Security-Policy in a real browser, stored text that looks like markup, and closed registration."""

import http.server
import json
import sqlite3
import threading
import time

from ..harness import free_port

INTERCEPT = False

# Collects every CSP violation on each page from the moment it starts loading.
RECORD_VIOLATIONS = """window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(`${e.violatedDirective} ${e.blockedURI} ${e.sourceFile}:${e.lineNumber}`));"""

# Each id marks markup that must never become a real element.
HOSTILE = '<img src=x id=pwn{n}>'


def run(t):
    cdp, check = t.cdp, t.check
    cdp.send('Page.addScriptToEvaluateOnNewDocument', source=RECORD_VIOLATIONS)

    def violations():
        return cdp.ev('window.__csp') or []

    def settle(path, ready):
        cdp.goto(path)
        cdp.wait(ready, timeout=10)
        cdp.pause(0.5)

    # ------------------------------------------------------------------ S1 the policy costs nothing
    print('S1  every page works under the Content-Security-Policy')
    settle('/index.html', "document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
    cdp.ev("document.querySelector('#templateList [data-template-action=start]').click()")
    cdp.pause(0.3)
    cdp.ev("document.getElementById('completedReps').value = '8'; document.getElementById('completeSetBtn').click()")
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('cancelSettings').click()")
    cdp.ev("document.getElementById('createTemplateBtn').click(); document.getElementById('cancelTemplate').click()")
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
    cdp.pause(0.5)
    check('the tracker: start, log a set, settings, template editor, saved workouts', violations() == [], violations())
    cdp.ev("confirm = () => true; document.getElementById('endWorkoutBtn').click()")

    settle('/history.html', "document.querySelectorAll('.history-workout').length >= 3")
    check('the History page', violations() == [], violations())

    settle('/progress.html', "document.querySelectorAll('#legend .legend-item').length >= 1")
    check('the Progress page, chart and legend', violations() == [], violations())
    swatch = cdp.ev("getComputedStyle(document.querySelector('#legend .legend-swatch')).backgroundColor")
    check('legend swatches still get their colour', swatch not in (None, '', 'rgba(0, 0, 0, 0)'), swatch)

    settle('/login.html', "!!document.getElementById('authForm')")
    check('the sign-in page', violations() == [], violations())

    # The same check with the policy doing its job: an injected inline script must not run.
    settle('/index.html', "document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
    cdp.ev("const s = document.createElement('script'); s.textContent = 'window.__inlineRan = true'; document.body.append(s);"
           "const i = document.createElement('img'); i.setAttribute('onerror', 'window.__handlerRan = true'); i.src = '/missing.png'; document.body.append(i);")
    cdp.pause(0.5)
    check('an injected inline script is blocked', cdp.ev('window.__inlineRan === undefined') is True)
    check('and so is an inline event handler', cdp.ev('window.__handlerRan === undefined') is True)
    check('and the browser reports both', len([v for v in violations() if 'script-src' in v]) >= 2, violations())

    # ------------------------------------------------------------------ S2 markup in stored data
    print('S2  text that looks like markup is shown as text everywhere')
    # Written straight into the database: whatever the API accepts, a stored value must never become markup.
    user_id = t.api('GET', '/api/auth/me', token=t.token)[0]['user']['id']
    payload = {
        'name': 'Hostile <b id=pwn0>name</b>', 'notes': HOSTILE.format(n=9), 'createdAt': int(time.time() * 1000),
        'exercises': [
            {'name': 'Bench Press', 'weight': HOSTILE.format(n=1), 'reps': HOSTILE.format(n=2)},
            {'name': 'Overhead Press', 'weight': 60, 'reps': 8,
             'sets': [{'weight': HOSTILE.format(n=3), 'reps': HOSTILE.format(n=4)}]},
        ],
    }
    db = sqlite3.connect(t.db_path('test.db'))
    db.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload) VALUES (?, ?, ?, ?, ?)',
               (user_id, payload['name'], payload['notes'], payload['createdAt'], json.dumps(payload)))
    db.commit()
    db.close()
    injected = "document.querySelectorAll('[id^=pwn]').length"

    settle('/index.html', "document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 4")
    cdp.ev("document.querySelectorAll('#savedWorkoutList [data-action=view]').forEach(b => b.click())")
    cdp.pause(0.8)
    check('the tracker creates no elements from it', cdp.ev(injected) == 0, cdp.ev(injected))
    text = cdp.ev("document.getElementById('savedWorkoutList').textContent")
    check('and shows it literally', '<img src=x id=pwn1>' in text, text[:200])

    settle('/history.html', "document.querySelectorAll('.history-workout').length >= 4")
    check('the History page creates no elements from it', cdp.ev(injected) == 0, cdp.ev(injected))
    text = cdp.ev("document.getElementById('historyList').textContent")
    check('and shows it literally', '<img src=x id=pwn3>' in text and '<img src=x id=pwn4>' in text, text[:300])

    settle('/progress.html', "document.querySelectorAll('#legend .legend-item').length >= 1")
    check('the Progress page creates no elements from it', cdp.ev(injected) == 0, cdp.ev(injected))

    # ------------------------------------------------------------------ S3 closed registration
    print('S3  the sign-in page follows the registration setting')
    settle('/login.html', "!!document.getElementById('registerTab')")
    cdp.pause(0.3)
    check('an open server offers Create account',
          cdp.ev("getComputedStyle(document.getElementById('registerTab')).display") != 'none')
    closed = t.start_server('closed.db', {'ALLOW_REGISTRATION': '0'})
    cdp.send('Page.navigate', url=closed.base_url + '/login.html')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(0.5)
    check('a closed server hides it', cdp.ev("getComputedStyle(document.getElementById('registerTab')).display") == 'none')
    check('and stays on Sign in', cdp.ev("document.getElementById('authSubmit').textContent") == 'Sign in')

    # ------------------------------------------------------------------ S4 another page on this address
    print('S4  a page on another port of this address cannot make changes')
    in_progress = {'name': 'Still Here', 'exercises': [], 'currentIndex': 0}
    t.api('POST', '/api/active-session', {'session': in_progress}, t.token)
    before = len(t.workouts())
    app = t.base_url
    # To the browser another port on the same address is the same site, so it sends this page the session cookie.
    pages = {
        '/fetch.html': f"""<script>
          fetch('{app}/api/active-session', {{ method: 'POST', credentials: 'include', headers: {{ 'Content-Type': 'text/plain' }},
            body: '{{"session":null}}' }}).then(() => 'answered', () => 'unreadable').then(outcome => {{ window.__done = outcome; }});
        </script>""",
        '/form.html': f"""<form method="post" enctype="text/plain" action="{app}/api/workouts">
          <input name='{{"name":"Forged","exercises":[],"x":"' value='"}}'></form><script>document.forms[0].submit();</script>""",
    }

    class Attacker(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path, '').encode()
            self.send_response(200 if body else 404)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class QuietServer(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            pass  # the browser dropping an idle connection as it navigates away

    attacker = QuietServer(('127.0.0.1', free_port()), Attacker)
    threading.Thread(target=attacker.serve_forever, daemon=True).start()
    try:
        elsewhere = f'http://127.0.0.1:{attacker.server_address[1]}'
        cdp.send('Page.navigate', url=elsewhere + '/fetch.html')
        check('the other page sends its request', cdp.wait('window.__done !== undefined', timeout=10), '')
        cdp.pause(0.5)
        check('which does not wipe the workout in progress', t.active_session() == in_progress, t.active_session())
        cdp.send('Page.navigate', url=elsewhere + '/form.html')
        check('a form it submits reaches the server', cdp.wait(f"location.href.startsWith('{app}/api/workouts')", timeout=10), '')
        cdp.pause(0.5)
        check('and is refused', 'from this site' in (cdp.ev('document.body.innerText') or ''), cdp.ev('document.body.innerText'))
        check('adding no workout', len(t.workouts()) == before, len(t.workouts()))
    finally:
        attacker.shutdown()
        attacker.server_close()
