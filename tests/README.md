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
| `api` | 222 | The HTTP API without a browser: the schema created, versioned and upgraded at startup (and a newer database refused), reads and writes while the database is busy, validation of workouts, templates, settings, training programs and active sessions, malformed and oversized request bodies, many copies of one upload arriving at once, upgrading a database from before `client_id`, `/frontend/` redirects, closed registration, sign-in throttling, password hash strength and upgrades, `Secure` cookies, expired sessions, security headers and content types, paths that could redirect off-site, accounts' emails (registering, signing in with either name, changing it with the password), and password reset codes (the email that carries one, wrong, used, expired and replaced codes, the limits on tries and on emails, and replies that never say whether an address has an account), the account commands an admin runs on the server (listing accounts, setting a password, setting an email, and what they refuse), closing connections that go quiet, and answering a burst of simultaneous connections instead of refusing some |
| `accounts` | 42 | The sign-in page with emails: creating an account, signing in with an email, the whole forgot-password flow with codes read from the emails, each step on a phone, adding an email in Settings, and what Forgot password? says on a server with no mail server |
| `account_state` | 21 | Settings and templates changed offline surviving a reload and reaching the server, a change from another device still arriving, a second account on the same browser, and adopting the copy kept by the previous version |
| `workout_flow` | 22 | `?start=` links, replacing an in-progress workout, editing and repeating workouts that have logged sets, progress-chart series |
| `program` | 194 | The training programs. Wendler 5/3/1: setting it up (one-rep maxes estimated from history, or training maxes), the planned cycle and its weights, planned sets filled in during a workout, the + set and its one-rep-max estimate, skipping days, a missed + set resetting a training max, rolling over to the next cycle, editing and ending the program, finishing a program workout offline, and the phone layout. Reddit PPL: its six days and rep ranges, weight added after a good session, three misses in a row dropping a lift 10%, the go-heavier hint for accessories, the next week, editing, switching programs, and a program saved by the previous version still loading. Apartment Gym: every exercise using only its equipment, the equipment settings, double progression, the heaviest-dumbbell cap, and three sessions below the range dropping a lift 10% |
| `timer_and_sync` | 70 | Rest timer accuracy under a stalled clock, the screen wake lock, saving sets and finished workouts through a network drop, a workout the server refuses not holding up the ones queued behind it, and 30 seconds more or less rest, running or paused, down to a quiet stop at zero |
| `sound_settings` | 31 | Alert tone, volume, vibration, the Test alert button, persistence across pages, and settings saved before the feature existed |
| `gym_usability` | 114 | Last time's numbers, correcting logged sets, moving between exercises, skipped exercises, message visibility, the phone layout, session expiry, sign-in links crafted to lead off-site afterwards, signing out, the controls within reach (the set entry first, the −5/+5 buttons, the plates for barbell lifts, the rest timer staying on screen, notes folded away), and undoing a removed set, even after moving on, until the offer lapses or the workout ends |
| `pwa` | 62 | The manifest and icons, service-worker registration, what is and is not cached, the theme colour, the signed-out redirect, a deploy reaching the next load, the install banner on phones (iPhone and Android wording, the Install button, dismissing, staying away once installed, and over plain HTTP, where only iPhones get it), and a reload with the server killed |
| `security` | 16 | The Content-Security-Policy leaving every page working while blocking injected scripts, stored text that looks like markup staying text on every page, and the sign-in page on a server with registration closed |
| `pages` | 85 | Every page loading its scripts without an error and with the shared helpers, an older cached script (as served for one load after an update) still being able to declare its own `$`, Progress treating differently typed exercise names as one, the saved-workout buttons working from the list on screen (offline included), nothing marked hidden showing (the empty-chart message, the rest timer), sets written compactly (bodyweight as reps) in History, the Tracker and last time's line, the Tracker listing the 10 most recent workouts, chart dates that never overlap, buttons in the page's own font, a number pad for every number field, and the theme following the device (live, before the page is drawn, on the sign-in page too) unless Light or Dark is chosen, the Tracker's order (Start again with the workout that is due first, templates folded once there is history and open for someone new, each saved workout showing only Start with the rest in its menu, on one line on a phone), and the training calendar: its days (tapping one to see its workouts), this week against the weekly goal, the current and best streaks, and a goal changed in Settings |
| `units` | 44 | Kilograms: the unit setting, pound workouts shown in kilograms and back without being rewritten, logging in kilograms with the 20 kg plate calculator and 2.5 kg steps, a unit change mid-workout or from another device, Progress, programs in kilograms, converting a program, and the server refusing any other unit |
| `workout_tools` | 107 | Exercise name suggestions; the summary of a finished workout and its personal records (heaviest weight, estimated one-rep max, bodyweight reps, longest hold, none for a first time, offline too); going straight to any exercise; swapping an exercise, back again (in another unit too), and after sets are logged; swapping in a training program, which counts the day but leaves the main lift's weight; rest per exercise in programs and templates; timed exercises with their hold timer, in History and on Progress; and the server checking the new fields |

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

`MAIL = True` gives the server a mail server to send password reset codes to:
`t.mail`, a stand-in from `tests/harness/mail.py` that keeps every message.
Without it the server has no mail settings, even if your shell sets `SMTP_*`.

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
- `t.server.admin('reset-password', 'tester', stdin='new-password\n')` — run one of `server.py`'s account commands on that server's database; returns `(exit status, stdout, stderr)`
- `t.mail.wait(address, count)` — with `MAIL = True`, the newest email to `address` once it has had `count`; `t.mail.code(message)` reads the 6-digit code out of it
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
