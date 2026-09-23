# Browser tests

End-to-end tests that drive a real headless browser against a real server. They
start `backend/server.py` on a spare port with an empty database, launch Chrome,
and then click through the app the way a person would — logging sets, reloading
mid-workout, pulling the network out from under it.

There is no mocking of the frontend. If a check passes, the feature works in a
browser.

## Running them

```bash
pip install -r tests/requirements.txt

python tests/run.py                  # every suite, in parallel (about 90 seconds)
python tests/run.py gym_usability    # one suite, in this process
python tests/run.py --jobs 1         # one at a time, for a quieter machine
python tests/run.py --list           # suite names
```

Exit status is 0 only if every check passed. Failures print the reason inline:

```
  [FAIL] set inputs are wide enough to use  ({'overflow': 0, 'minInput': 59.06, 'vw': 375})
```

### Requirements

- Python 3 (developed and run on 3.11; older versions are untested)
- `websocket-client` (the only dependency; the app itself stays standard-library only)
- Chrome, Chromium or Edge

The browser is found on `PATH`, then at the usual install locations for the
platform. If yours lives somewhere else, point the tests at it:

```bash
WORKOUT_TEST_CHROME="/opt/chrome/chrome" python tests/run.py
```

## What each suite covers

| Suite | Checks | Covers |
| --- | --- | --- |
| `api` | 128 | The HTTP API without a browser: the schema created, versioned and upgraded at startup (and a newer database refused), reads and writes while the database is busy, validation of workouts, templates, settings and active sessions, malformed and oversized request bodies, many copies of one upload arriving at once, upgrading a database from before `client_id`, `/frontend/` redirects, closed registration, sign-in throttling, password hash strength and upgrades, `Secure` cookies, expired sessions, security headers and content types, and paths that could redirect off-site |
| `account_state` | 21 | Settings and templates changed offline surviving a reload and reaching the server, a change from another device still arriving, a second account on the same browser, and adopting the copy kept by the previous version |
| `workout_flow` | 22 | `?start=` links, replacing an in-progress workout, editing and repeating workouts that have logged sets, progress-chart series |
| `timer_and_sync` | 57 | Rest timer accuracy under a stalled clock, the screen wake lock, saving sets and finished workouts through a network drop, and a workout the server refuses not holding up the ones queued behind it |
| `sound_settings` | 31 | Alert tone, volume, vibration, the Test alert button, persistence across pages, and settings saved before the feature existed |
| `gym_usability` | 81 | Last time's numbers, correcting logged sets, moving between exercises, skipped exercises, message visibility, the phone layout, session expiry and signing out |
| `pwa` | 39 | The manifest and icons, service-worker registration, what is and is not cached, the theme colour, the signed-out redirect, a deploy reaching the next load, and a reload with the server killed |
| `security` | 16 | The Content-Security-Policy leaving every page working while blocking injected scripts, stored text that looks like markup staying text on every page, and the sign-in page on a server with registration closed |
| `pages` | 29 | Every page loading its scripts without an error and with the shared helpers, an older cached script (as served for one load after an update) still being able to declare its own `$`, Progress treating differently typed exercise names as one, the saved-workout buttons working from the list on screen (offline included), and nothing marked hidden showing (the empty-chart message, the rest timer) |

Each suite gets a fresh server, database and browser profile, so they are
independent and safe to run concurrently.

## How a test is written

A suite is a module with an `INTERCEPT` flag and a `run(t)` function. `t` is the
fixture from `tests/harness/context.py`: a server, a browser page, three seeded
workouts and the page helpers the suites share.

`INTERCEPT = True` turns on request interception, which `t.cdp.block_api` and
`t.cdp.drop_responses` depend on. With `INTERCEPT = False` those two are inert and
changing them does nothing, so a suite that simulates a network failure must keep it
on. Suites that never touch the network conditions can turn it off (as
`workout_flow` does); leaving the flag out defaults to on.

A suite that only talks to the API can set `BROWSER = False`; it then starts
without Chrome, and `t.cdp` is `None`.

To add a suite, create `tests/suites/<name>.py` and append `<name>` to `NAMES` in
`tests/suites/__init__.py`; the runner only knows the suites listed there.

```python
def run(t):
    cdp, check = t.cdp, t.check

    t.open_tracker()
    t.start(0)                      # first built-in template
    t.log_set(8)
    check('the set is listed', cdp.ev("document.querySelectorAll('#completedSets li').length") == 1)
```

`check(name, ok, detail='')` records a result; `detail` is printed only when the
check fails, so put the observed value there.

Useful pieces of `t`:

- `t.cdp.ev(js)` — evaluate JavaScript in the page and return the value
- `t.cdp.wait(js, timeout=8)` — poll until the expression is truthy
- `t.cdp.pause(seconds)` — let the page run (see the note on the event pump below)
- `t.cdp.block_api = True` — make every API request fail, simulating an unreachable server
- `t.cdp.drop_responses = 1` — let a request through but discard its reply
- `t.cdp.answer = False` — what `window.confirm` returns; `t.cdp.dialogs` lists what was asked
- `t.api(method, path, body, token)` — call the API directly, around the browser
- `t.request(method, path, body_bytes, headers, token)` — send exact bytes and headers, for requests the app would never make; returns `(status, headers, body)`
- `t.start_server(db_name, env)` — a second server with its own database and environment variables, stopped with the suite
- `t.wait_for(predicate)` — poll a Python condition while the page keeps running

### Two things worth knowing

**The CDP client only processes events while a command is in flight.** That is why
`t.cdp.pause()` polls with a trivial evaluate instead of sleeping — a plain
`time.sleep` would leave intercepted requests hanging. Use `t.cdp.pause()`, not
`time.sleep()`, whenever the page needs to make progress.

**Dialogs are stubbed in the page, not handled natively.** Headless Chrome can
auto-dismiss a native dialog before the test answers it, which silently reads as
"cancel" and produced two tests that failed roughly one run in five. The harness
replaces `window.confirm` and `window.alert` instead, so `t.cdp.answer` is
honoured every time.

## Known limits

- Phone layouts are checked by emulating a 375px viewport in desktop Chrome, not
  on a real device. Vibration, audio output and the wake lock are stubbed, so the
  tests confirm the app *asks* for them, not that hardware responds.
- Notes typed during a workout (or when building one) are not exercised by any
  suite, including their offline syncing.
- `t.cdp.ev()` returns `None` if Chrome answers an evaluate with a protocol-level
  error, rather than raising. Checks written as `== value` or `is True` fail
  visibly in that case, but a negated check (`not ...`) could pass. Raising
  instead was considered and left out: evaluates that race a navigation
  legitimately return that error, and several suites rely on tolerating it.
- The suites are sequential inside a single browser page and depend on the order
  of their own sections; they are not individually runnable.
- Timing-sensitive checks use fixed pauses. On a heavily loaded machine, prefer
  `--jobs 1`.
- `pwa` relies on `127.0.0.1` counting as a secure context, which is how the
  browser is willing to run a service worker over plain HTTP. It therefore proves
  the worker behaves, not that any particular deployment is a secure context.
