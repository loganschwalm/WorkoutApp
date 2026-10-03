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

GitHub Actions runs them all on every push and pull request (`.github/workflows/tests.yml`),
four suites at a time, and moves the `stable` branch that installs follow once they pass on `main`.

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
| `api` | 485 | The HTTP API without a browser: cardio sessions (checked, exported as CSV rows of their own, and imported), every page leading to sign-in when signed out, a program you build (its name and up to 7 days, checked), the muscle and equipment of each exercise (checked against the app's lists, exported, and imported only for exercises that have none), bodyweight by day (checked, exported, and imported only for days that have none), the rules for a new username, email and password (and accounts from before them unaffected), password hashing capped so a flood of sign-ins cannot take every core (and a reset code used by two requests at once still working once), the schema created, versioned and upgraded at startup (and a newer database refused), reads and writes while the database is busy, validation of workouts, templates, settings, training programs and active sessions, malformed and oversized request bodies, many copies of one upload arriving at once, upgrading a database from before `client_id`, `/frontend/` redirects, closed registration, sign-in throttling, password hash strength and upgrades, `Secure` cookies, expired sessions, security headers and content types, paths that could redirect off-site, accounts' emails (registering, signing in with either name, changing it with the password), and password reset codes (the email that carries one, wrong, used, expired and replaced codes, the limits on tries and on emails, and replies that never say whether an address has an account), the account commands an admin runs on the server (listing accounts, setting a password, setting an email, and what they refuse), closing connections that go quiet, exporting an account as JSON and as CSV (dates in the browser's time zone, formula-like names kept as text) and importing it (never twice, never overwriting, all or nothing, and bigger than any other request may be), sessions stored hashed (and rehashed on upgrading), ten wrong reset codes a day per address across codes, changing the password (with the current one, signing out other sessions, and limited like signing in), sessions renewed by use, changes refused when they come from another page or not as JSON, text gzipped for browsers that take it (and a 304 still answered), deleting an account (and from the command line), answering a burst of simultaneous connections instead of refusing some, and stopping at once on SIGTERM (`docker stop`; not checked on Windows) |
| `accounts` | 89 | The sign-in page with emails: the rules for a new username, email and password (the page judging them as the server does, pointing out a field before sending, and in Settings too), creating an account, signing in with an email, the whole forgot-password flow with codes read from the emails, each step on a phone, adding an email in Settings, what Forgot password? says on a server with no mail server, changing the password in Settings, and deleting the account there |
| `account_state` | 36 | Settings and templates changed offline surviving a reload and reaching the server, a change from another device still arriving, a second account on the same browser, adopting the copy kept by the previous version, and Export, Export sets as CSV and Import in Settings (waiting workouts included, offline, and a file that is not an export) |
| `workout_flow` | 43 | Cancelling a workout (at once with nothing logged, asking with sets logged, Undo, and nothing reaching History, last time, records, the program or the server), `?start=` links, replacing an in-progress workout, editing and repeating workouts that have logged sets, progress-chart series, and a workout with no exercises (refused on starting, closed if one is left in progress, and one past its last exercise) |
| `program` | 216 | The training programs. Wendler 5/3/1: setting it up (one-rep maxes estimated from history, or training maxes), the planned cycle and its weights, planned sets filled in during a workout, the + set and its one-rep-max estimate, skipping days, a missed + set resetting a training max, rolling over to the next cycle, editing and ending the program, finishing a program workout offline, a set done showing what was lifted, and the phone layout. Reddit PPL: its six days and rep ranges, weight added after a good session, three misses in a row dropping a lift 10%, the go-heavier hint for accessories, the next week, editing, switching programs, and a program saved by the previous version still loading. Apartment Gym: every exercise using only its equipment, the equipment settings, double progression, the heaviest-dumbbell cap, and three sessions below the range dropping a lift 10% |
| `timer_and_sync` | 139 | Rest timer accuracy under a stalled clock, the screen wake lock, saving sets and finished workouts through a network drop, a workout the server keeps failing on not holding up the rest, a warning when the browser will not save, a workout the server refuses not holding up the ones queued behind it, a reload mid-workout on a connection that stalls instead of failing, the server's copy of the workout still winning when it changed on another device, two tabs uploading the same queue, a workout written in the form saved offline and only once however often Save is tapped, and 30 seconds more or less rest, running or paused, down to a quiet stop at zero |
| `sound_settings` | 46 | Alert tone, volume, vibration, the Test alert button, each change saved as it is made (a rest duration still being typed kept on closing), focus back on the gear once Settings closes, persistence across pages, settings saved before the feature existed, and on an iPhone, the alert taking playback audio (to play with the ringer silent) only while it sounds |
| `gym_usability` | 151 | Last time's numbers, correcting logged sets, the bar, plates and weight step from Settings (fewest plates, each unit its own), moving between exercises, skipped exercises, message visibility, the phone layout, session expiry, sign-in links crafted to lead off-site afterwards, signing out, the controls within reach (the set entry first, the −5/+5 buttons, the plates for barbell lifts, plates drawn to size, the rest timer staying on screen above or below, notes folded away), the phone's tab bar and small header, the rest of the Tracker out of the way during a workout, the exercise's ⋯ menu, undoing a removed set, even after moving on, until the offer lapses or the workout ends, a loaded lift with no weight asked about first (not a bodyweight one, nor a 0 typed in), Finish tapped twice, and the edit form on a phone |
| `pwa` | 71 | The manifest and icons, service-worker registration, what is and is not cached, the theme colour, the signed-out redirect, a deploy reaching the next load, the install banner on phones (iPhone and Android wording, the Install button, dismissing, staying away once installed, and over plain HTTP, where only iPhones get it), a reload with the server killed, and one where the server accepts connections but never answers |
| `security` | 24 | The Content-Security-Policy leaving every page working (the Cardio page's timer and form included) while blocking injected scripts, stored text that looks like markup staying text on every page, the sign-in page on a server with registration closed, and a page on another port of the same address failing to make changes with the session cookie |
| `pages` | 203 | Bodyweight on Progress (logging, the trend, units, removing, a phone), every page loading its scripts without an error and with the shared helpers, drawn in the Inter font served with the app, an older cached script (as served for one load after an update) still being able to declare its own `$`, Progress treating differently typed exercise names as one, the saved-workout buttons working from the list on screen (offline included), nothing marked hidden showing (the empty-chart message, the rest timer), sets written compactly (bodyweight as reps) in History, the Tracker and last time's line, the Tracker listing the 10 most recent workouts (3 of them until Show more), chart dates that never overlap, buttons in the page's own font, a number pad for every number field, and the theme following the device (live, before the page is drawn, on the sign-in page too) unless Light or Dark is chosen, the Tracker's order (Start again with the workout that is due first, templates folded once there is history and open for someone new, each saved workout showing only Start with the rest in its menu, on one line on a phone), and the training calendar: its days (tapping one to see its workouts), this week against the weekly goal, the current and best streaks, a goal changed in Settings, and moving between days with the arrow keys; the template editor giving focus back to its button; History a line a workout under month headings with their totals, the latest three months first, a search by name, exercise or note, a calendar day leading to its workouts, and the ⋯ menu's Copy as new, Edit (in the Tracker's form) and Delete (offline too); and Progress: opening on the exercise done most, workouts placed by date, values written only where they fit (with several workout types, on a phone), a tapped point, the chart described for a screen reader, its axis on round numbers from zero (and bodyweight's never below it), the estimated one-rep max, and personal records |
| `units` | 44 | Kilograms: the unit setting, pound workouts shown in kilograms and back without being rewritten, logging in kilograms with the 20 kg plate calculator and 2.5 kg steps, a unit change mid-workout or from another device, Progress, programs in kilograms, converting a program, and the server refusing any other unit |
| `workout_tools` | 107 | Exercise name suggestions; the summary of a finished workout and its personal records (heaviest weight, estimated one-rep max, bodyweight reps, longest hold, none for a first time, offline too); going straight to any exercise; swapping an exercise, back again (in another unit too), and after sets are logged; swapping in a training program, which counts the day but leaves the main lift's weight; rest per exercise in programs and templates; timed exercises with their hold timer, in History and on Progress; and the server checking the new fields |
| `training_tools` | 71 | Progression in your own templates (sets and a rep range, going up once every set reaches the top, staying until then, a saved workout started again, and the server refusing a set count out of range), Notes kept with an exercise (across workouts and reloads, and removed), going heavier when every set reached its target (and not after a set that fell short or had no reps left), warm-up sets for barbell lifts (following the weight, not for other lifts, and off in Settings), the reps each set had left (optional, saved, off in Settings), past sessions in a workout and every session on Progress (with the note), History's links to them, and supersets made mid-workout and in the template editor |
| `exercise_library` | 40 | The exercise library: muscles and equipment guessed from names (every exercise in the templates and programs has a muscle, and names with words of two go to the right one), Sets per muscle on Progress (a week's sets by muscle, the average of the weeks before and only since the first workout, skipped and form-saved exercises, bars drawn to scale, moving between weeks, exercises not counted), the Exercises card (choosing a muscle or equipment, kept with the account, searching, adding and removing your own, on a phone), and on the Tracker, your own exercises suggested and the equipment deciding which lifts get plates |
| `program_builder` | 37 | Your own program: building a weekly split from templates (a name, adding, removing and moving days, up to 7), its card (the next day planned as its template progresses, each day's template, no numbers per lift), following it (workouts named after the day, History's label, skipping, the next week), editing it (days kept done where they keep their place and template), deleting a template a day does (asked first, then the day asks for another), a reload, a phone, ending it, and 5/3/1's First Set Last |
| `cardio` | 79 | The Cardio tab: the four tabs, an activity for each kind of cardio with when it was last done, Start the timer or Enter the time (remembered on the device), what each machine can be set to (in range, saved, in the summary, prefilled from last time), timing a session (the clock from when it started, paused, kept through a reload, cancelled with Undo, finished with the time filled in), the pace, speed or split worked out as the distance is typed, the summary and records, logging a session by hand (any activity and day, what it needs and what it refuses, Other's own name, floors for the stair climber), editing, copying, starting again and deleting a session, miles or kilometres (following the weight unit until chosen, kept with the account, converted only for showing), History (a session's row, a ring on the calendar for a day of cardio only, links to the Cardio page), Progress (activities apart from exercises, each with its own measures, clocks for times, every session, and the records), the Strength page keeping to strength, and a phone |
| `stalls` | 10 | Stall detection: the lift whose best has not moved in three weeks over three sessions listed on Progress with the deload to try (10% off last time, on the weight step), and not a lift still going up, one done too few times, one not trained lately or one working back up from a deload; before the first set of a stalled lift, the hint and Use button, gone once a set is logged; and the deload in kilograms |

Each suite gets a fresh server, database and browser profile, so they are
independent and safe to run concurrently.

## How a test is written

A suite is a module with an `INTERCEPT` flag and a `run(t)` function. `t` is the
fixture from `tests/harness/context.py`: a server, a browser page, three seeded
workouts and the page helpers the suites share.

`INTERCEPT = True` turns on request interception, which `t.cdp.block_api`,
`t.cdp.drop_responses` and `t.cdp.stall_paths` depend on. `block_api` fails requests at once,
like a dropped connection; `stall_paths` holds matching GET requests with no answer at all, like
a connection that stalls, until `t.cdp.release_stalled()`. With `INTERCEPT = False` those are inert and
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
