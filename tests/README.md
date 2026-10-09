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
four suites at a time, on Python 3.9 (the oldest the README says the server runs on) and 3.12, and moves the `stable`
branch that installs follow once both pass on `main`. Before them it runs pyflakes, `tests/lint.py` and ShellCheck (on the two shell
scripts, settings in `.shellcheckrc`):

```bash
python -m pyflakes backend tests scripts docker-entrypoint.py   # slips in the Python (needs the requirements above)
python tests/lint.py                                            # the lists kept by hand agree with the files
```

`lint.py` needs no browser. It checks that every script a page loads is in the service worker's precache list (leave one
out and the page works online and breaks the first time it is opened offline), that no two scripts declare the same
top-level name (they share one scope), that the Python parses as 3.9, that the server and the pages agree on the parts of the account's state that sync, that every environment variable the server reads is
in the reference, that every colour theme's text is readable on what it sits on and its accent stands out from the page (the
contrast of every colour the stylesheet writes out), and that every suite is registered and has a row below. The `lint` suite shows each of those noticing a
fault put into a copy of the project, so a check that quietly stopped working would fail there.

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

Each run prints its own number of checks, so none is kept here: a count written down goes stale with the next check, and
a few vary by platform or by the day.

| Suite | Covers |
| --- | --- |
| `lint` | The project's own consistency checks (`tests/lint.py`, which also runs by itself in CI): that every script and stylesheet a page loads is in the service worker's precache list (and everything precached is there and used), that no top-level name is declared by two scripts, that the Python parses as 3.9, that the server and the pages agree on the parts of the account's state that sync, that every environment variable the server reads is in the reference, and that every suite is registered and described here; each check is shown to notice a fault put into a copy of the project |
| `api` | The HTTP API without a browser: cardio sessions (checked, exported as CSV rows of their own, and imported), every page leading to sign-in when signed out, a program you build (its name and up to 7 days, checked), the muscle and equipment of each exercise (checked against the app's lists, exported, and imported only for exercises that have none), bodyweight by day (checked, exported, and imported only for days that have none), the rules for a new username, email and password (and accounts from before them unaffected), password hashing capped so a flood of sign-ins cannot take every core (and a reset code used by two requests at once still working once), the route table (every route's method existing, exactly the sign-in routes open to anyone, every other one answering 401 signed out, and what nothing answers being 404 only to someone signed in), the schema created, versioned and upgraded at startup (every part of the account's state having its column, and a part added to the table being loaded, stored, checked, merged and imported with nothing else changed) (and a newer database refused), reads and writes while the database is busy, validation of workouts, templates, settings, training programs and active sessions, malformed and oversized request bodies, many copies of one upload arriving at once, upgrading a database from before `client_id`, `/frontend/` redirects, closed registration, sign-in throttling (per account, and per address across usernames, which signing in does not reset and 0 turns off), password hash strength and upgrades, `Secure` cookies, expired sessions, security headers and content types, paths that could redirect off-site, accounts' emails (registering, signing in with either name, changing it with the password), and password reset codes (the email that carries one, wrong, used, expired and replaced codes, the limits on tries and on emails, and replies that never say whether an address has an account), the account commands an admin runs on the server (listing accounts, setting a password, setting an email, and what they refuse), closing connections that go quiet, exporting an account as JSON and as CSV (dates in the browser's time zone, formula-like names kept as text) and importing it (never twice, never overwriting, all or nothing, and bigger than any other request may be), sessions stored hashed (and rehashed on upgrading), ten wrong reset codes a day per address across codes, changing the password (with the current one, signing out other sessions, and limited like signing in), sessions renewed by use, changes refused when they come from another page or not as JSON, text gzipped for browsers that take it (and a 304 still answered), deleting an account (and from the command line), answering a burst of simultaneous connections instead of refusing some, changes to the account state from two devices merged (each part's own way, a program's runs never mixed, at once, past the usual size limit, copies sent whose answer never came counted as starting points, and a part sent without its base replacing the stored one), the limits on an open server (accounts made per address, reset emails per address and per day, workouts per account and bytes per workout, one import at a time, where the server listens), the proxies whose `X-Forwarded-For` is believed, the devices signed in to an account (listed, signed out one at a time or all but one, their reminders going with them, and how a browser is named), the `Server` header saying no version, the ceiling on open connections and the deadlines on a request (a connection that sends nothing, or dribbles its headers, is closed; a slow body is not), and stopping at once on SIGTERM (`docker stop`; not checked on Windows) |
| `accounts` | The sign-in page with emails: the rules for a new username, email and password (the page judging them as the server does, pointing out a field before sending, and in Settings too), creating an account, signing in with an email, the whole forgot-password flow with codes read from the emails, each step on a phone, adding an email in Settings, what Forgot password? says on a server with no mail server, changing the password in Settings, the devices signed in being listed in Settings and signed out from there, and deleting the account there |
| `account_state` | Settings and templates changed offline surviving a reload and reaching the server, a change from another device still arriving, a second account on the same browser, adopting the copy kept by the previous version, a change here and one on another device meanwhile both kept (offline, from a page open since before, while an earlier change is still going up, and after one stored but unanswered, then changed back), and Export, Export sets as CSV and Import in Settings (waiting workouts included, offline, and a file that is not an export) |
| `workout_flow` | Cancelling a workout (at once with nothing logged, asking with sets logged, Undo, and nothing reaching History, last time, records, the program or the server), `?start=` links, replacing an in-progress workout, editing a finished workout a set at a time (changing, adding and removing sets, values that snap back (reps below 1 or not whole, weights below zero) or look like a slip, each exercise's weight and reps following its sets, Cancel leaving it as it was) and repeating one, progress-chart series, and a workout with no exercises (refused on starting, closed if one is left in progress, and one past its last exercise), and the account’s state arriving before the Tracker’s own script has run (nothing throws) |
| `program` | The training programs. Wendler 5/3/1: setting it up (one-rep maxes estimated from history, or training maxes), the planned cycle and its weights, planned sets filled in during a workout, the + set and its one-rep-max estimate, skipping days, a missed + set resetting a training max, rolling over to the next cycle, editing and ending the program, finishing a program workout offline, a set done showing what was lifted, and the phone layout. Reddit PPL: its six days and rep ranges, weight added after a good session, three misses in a row dropping a lift 10%, the go-heavier hint for accessories, the next week, editing, switching programs, and a program saved by the previous version still loading. Apartment Gym: every exercise using only its equipment, the equipment settings, double progression, the heaviest-dumbbell cap, and three sessions below the range dropping a lift 10% |
| `timer_and_sync` | Rest timer accuracy under a stalled clock, the screen wake lock, saving sets and finished workouts through a network drop, a workout the server keeps failing on not holding up the rest, a warning when the browser will not save, a workout the server refuses not holding up the ones queued behind it, a reload mid-workout on a connection that stalls instead of failing, the server's copy of the workout still winning when it changed on another device, two tabs uploading the same queue, a workout written in the form saved offline and only once however often Save is tapped, and 30 seconds more or less rest, running or paused, down to a quiet stop at zero |
| `sound_settings` | Alert tone, volume, vibration, the Test alert button, each change saved as it is made (a rest duration still being typed kept on closing), focus back on the gear once Settings closes, persistence across pages, settings saved before the feature existed, and on an iPhone, the alert taking playback audio (to play with the ringer silent) only while it sounds |
| `gym_usability` | Last time's numbers, correcting logged sets, the bar, plates and weight step from Settings (fewest plates, each unit its own), moving between exercises, skipped exercises, message visibility, the phone layout, session expiry, sign-in links crafted to lead off-site afterwards, signing out, the controls within reach (the set entry first, the −5/+5 buttons, the plates for barbell lifts, plates drawn to size, the rest timer staying on screen above or below, notes folded away), the phone's tab bar and small header, the rest of the Tracker out of the way during a workout, the exercise's ⋯ menu, undoing a removed set, even after moving on, until the offer lapses or the workout ends, a loaded lift with no weight asked about first (not a bodyweight one, nor a 0 typed in), Finish tapped twice, the edit form on a phone, a set far past your best asked about (logging, correcting, saying no and yes), reps that must be whole, and Finish early |
| `pwa` | The manifest and icons, service-worker registration, what is and is not cached, the theme colour, the signed-out redirect, a deploy reaching the next load, the install banner on phones (iPhone and Android wording, the Install button, dismissing, staying away once installed, and over plain HTTP, where only iPhones get it), a reload with the server killed, and one where the server accepts connections but never answers |
| `security` | The Content-Security-Policy leaving every page working (the Cardio page's timer and form included) while blocking injected scripts, stored text that looks like markup staying text on every page, the sign-in page on a server with registration closed, and a page on another port of the same address failing to make changes with the session cookie |
| `pages` | Bodyweight on Progress (logging, a weight far from the last asked about, the trend, units, removing, a phone), every page loading its scripts without an error and with the shared helpers, drawn in the Inter font served with the app, an older cached script (as served for one load after an update) still being able to declare its own `$`, Progress treating differently typed exercise names as one, the saved-workout buttons working from the list on screen (offline included), nothing marked hidden showing (the empty-chart message, the rest timer), sets written compactly (bodyweight as reps) in History, the Tracker and last time's line, the Tracker listing the 10 most recent workouts (3 of them until Show more), chart dates that never overlap, buttons in the page's own font, a number pad for every number field, and the theme following the device (live, before the page is drawn, on the sign-in page too) unless Light or Dark is chosen, the Tracker's order (Start again with the workout that is due first, templates folded once there is history and open for someone new, each saved workout showing only Start with the rest in its menu, on one line on a phone), and the training calendar: its days (tapping one to see its workouts), this week against the weekly goal, the current and best streaks, a goal changed in Settings, and moving between days with the arrow keys; the template editor giving focus back to its button; History a line a workout under month headings with their totals, the latest three months first, a search by name, exercise or note, a calendar day leading to its workouts, and the ⋯ menu's Copy as new, Edit (in the Tracker's form) and Delete (offline too); and Progress: opening on the exercise done most, workouts placed by date, values written only where they fit (with several workout types, on a phone), a tapped point, the chart described for a screen reader, its axis on round numbers from zero (and bodyweight's never below it), the estimated one-rep max, personal records, and goals (a target already lifted asked about first) |
| `units` | Kilograms: the unit setting, pound workouts shown in kilograms and back without being rewritten, logging in kilograms with the 20 kg plate calculator and 2.5 kg steps, a unit change mid-workout or from another device, Progress, programs in kilograms, converting a program, and the server refusing any other unit |
| `workout_tools` | Exercise name suggestions; the summary of a finished workout and its personal records (heaviest weight, estimated one-rep max, bodyweight reps, longest hold, none for a first time, offline too); going straight to any exercise; swapping an exercise, back again (in another unit too), and after sets are logged; swapping in a training program, which counts the day but leaves the main lift's weight; rest per exercise in programs and templates; timed exercises with their hold timer, in History and on Progress; and the server checking the new fields |
| `training_tools` | Progression in your own templates (sets and a rep range, going up once every set reaches the top, staying until then, a saved workout started again, and the server refusing a set count out of range), Notes kept with an exercise (across workouts and reloads, and removed), going heavier when every set reached its target (and not after a set that fell short or had no reps left), warm-up sets for barbell lifts (following the weight, not for other lifts, and off in Settings), the reps each set had left (optional, saved, off in Settings), past sessions in a workout and every session on Progress (with the note), History's links to them, and supersets made mid-workout and in the template editor |
| `exercise_library` | The exercise library: muscles and equipment guessed from names (every exercise in the templates and programs has a muscle, and names with words of two go to the right one), Sets per muscle on Progress (a week's sets by muscle, the average of the weeks before and only since the first workout, skipped and form-saved exercises, bars drawn to scale, moving between weeks, exercises not counted), the Exercises card (choosing a muscle or equipment, kept with the account, searching, adding and removing your own, on a phone), and on the Tracker, your own exercises suggested and the equipment deciding which lifts get plates |
| `program_builder` | Your own program: building a weekly split from templates (a name, adding, removing and moving days, up to 7), its card (the next day planned as its template progresses, each day's template, no numbers per lift), following it (workouts named after the day, History's label, skipping, the next week), editing it (days kept done where they keep their place and template), deleting a template a day does (asked first, then the day asks for another), a reload, a phone, ending it, and 5/3/1's First Set Last |
| `cardio` | The Cardio tab: the four tabs, an activity for each kind of cardio with when it was last done, Start the timer or Enter the time (remembered on the device), what each machine can be set to (in range, saved, in the summary, prefilled from last time), timing a session (the clock from when it started, paused, kept through a reload, cancelled with Undo, finished with the time filled in), the pace, speed or split worked out as the distance is typed, the summary and records, logging a session by hand (any activity and day, what it needs and what it refuses, Other's own name, floors for the stair climber, a pace far faster than your best asked about), editing, copying, starting again and deleting a session, miles or kilometres (following the weight unit until chosen, kept with the account, converted only for showing), History (a session's row, a ring on the calendar for a day of cardio only, links to the Cardio page), Progress (activities apart from exercises, each with its own measures, clocks for times, every session, and the records), the Strength page keeping to strength, and a phone |
| `stalls` | Stall detection: the lift whose best has not moved in three weeks over three sessions listed on Progress with the deload to try (10% off last time, on the weight step), and not a lift still going up, one done too few times, one not trained lately or one working back up from a deload; before the first set of a stalled lift, the hint and Use button, gone once a set is logged; and the deload in kilograms |
| `repeat_and_guides` | Same as last set (hidden until a set is logged, one tap logging the last set rather than what the fields were changed to, each tap one more set with the rest timer, the reps-left rating being the new set's own, per exercise, kept through a reload and in the saved workout, a timed exercise's seconds with its hold running, bodyweight reps) and How to do it (in the exercise's menu, closed by Close, the menu item and moving on, the steps and usual mistake, a video-search link that opens a new tab without access back, an exercise with no cues, a name that looks like markup, which guide each name gets and every program and template exercise having one), and both on a phone |
| `push` | Web push without a browser: the cryptography checked against known answers (the curve, NIST's AES-GCM cases, RFC 5869 and RFC 8291's example, and signatures checked the long way), which push services a subscription may name, a time zone and an offset giving a phone's clock; subscriptions (what is refused, updating, the 10 newest kept, moving to another account, deleting the account) and the test notification against a push service of the suite's own (readable only by the phone it was for, signed as the server, a 410 or 404 forgetting the phone, a failure keeping it); the schedule's checks in the settings; the reminders the server sends (on a training day from the time chosen, once, late but not too late, not on other days, not after a workout, again the next day, tried again after a failure); and messages going at once (six phones with slow push services sent in the time of one, a phone that cannot be reached failing alone, and a reminder not waiting for a push service that has stopped answering) |
| `calendar` | How the pages count days and weeks on any day, with the page's clock pinned and nothing seeded by date: the shared helpers (a day's key and start, a week's Monday, days and weeks on from them), the History calendar's weeks and streaks, Cardio's and Progress's week, and the schedule's planned days and nudge, on each of the seven weekdays, either side of clock changes, at midnight and a second before it, on a leap day and New Year's Eve, in time zones that change their clocks, are half an hour out, or are a day ahead of or behind UTC; expected from the browser's own formatting of dates, not from the helpers |
| `tracker_parts` | The pieces the Tracker's set logging and exercise screen are made of, each on its own: what the entry fields start the next set with (a planned set's weight and reps, an assistance exercise taking last time's weight, a rep range starting at the bottom, a repeat of the set before, a hold's target seconds, last time in the other unit), what is wrong with an entry (no reps, half a rep, a negative weight, and which field is looked at first), and the markup of the plan's chips and the completed sets (done, current and to come, corrected in place, held in seconds, and markup in a value staying text) |
| `summary` | The summary of a finished workout, piece by piece: the top set of some sets (the heaviest weight, then its reps; a hold's seconds; bodyweight's reps) and how it compares with last time's (up, down, the same, or a first, in the unit shown), the volume against the last workout of the same name (a whole percent, or the same), the goals a workout reached for the first time (in the goal's own unit, an exercise done twice counted once), what is taken from the history before the workout joins it (last times, the previous workout of the name in the unit shown, the records so far, the week's count with cardio), and what is shown for a first workout, for kilograms and for names that look like markup |
| `accessibility` | Ease of access: that everything the keyboard can reach shows a focus ring (the tracker, a workout, History, Progress, Cardio, Settings, sign-in), that the Text size setting scales the text, is saved, is there before the page is drawn and leaves nothing running off a phone's side, and that what is tapped is big enough to tap |
| `chart_parts` | The parts the Progress charts are drawn from: which labels there is room to write (a gap apart, the last always, a bigger gap leaving more out), where each value goes (right of its point, left at the edge, a clash dropped, the most recent latest value winning), the bodyweight chart's scale (room above and below, round steps, a flat line, a wide range, never below zero, every weight inside it), and the canvas sized to the screen's pixels with the page's colours following the theme |
| `settings_table` | The table the settings come from (`settings-fields.js`): the dialog's sections and controls made from it (no id used twice, every control the table makes in the dialog), every setting having a default and no two entries owning one, a form showing the defaults reading back as them, what is chosen coming back as chosen and what is no longer a choice as the default, the alert sounds having tones, controls the browser cannot use being hidden, and a setting added to the table being shown, read and defaulted with nothing else told |
| `program_calendar` | Add to calendar in the program card's menu: the program's remaining workouts saved as an .ics file (a calendar with one event for each, none from the next block, on the training days at their time, an hour long, a UID each that stays the same when saved again, the day's exercises in its description, and nothing saved, with a message, when no days are chosen), only the days chosen used, and the format's escaping and 75-octet folding of long and non-ASCII lines |
| `workout_cache` | Reading the workouts: the ETag on `GET /api/workouts` (a weak tag the browser keeps them under, 304 with no body for a page that has them, in the strong form, among others, or as `*`, never for someone signed out or another account), every change to the workouts changing it (saving, editing even to the same size, deleting, importing, a change made to the database by anything else, as triggers keep it) and nothing else doing so (settings, a retried upload, deleting what is gone), an account from before the tags given one, its tag going with the account, the index the workouts are read in and no sorting after it, signing out telling the browser to clear what it kept, and in the browser the first page downloading the history, the next only checking it (a few hundred bytes), a new workout downloaded with the rest, and a download again after signing out |
| `schedule` | The training schedule and reminders in the browser: choosing days and a time in Settings (kept at once, reaching the server and other devices, read safely when malformed), the Tracker's nudge (a training day, done for today, a day off, a missed day and who it is said to, the program's workout for each day, Start from it, out of the way during a workout), the planned days on History's calendar and Coming up (today, days to come, a day already trained, no days chosen), reminders from Settings to a notification (a browser that cannot, notifications blocked, turning on and off, the test, a subscription told again each day and when the clock changes, signing out, plain HTTP), and what the service worker does with a push and a tap on it |

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
- `t.text(id)`, `t.field(id)`, `t.visible(id)`, `t.click(id)`, `t.set_field(id, value)` — what an element says, its value, whether it is showing, a tap on it, and typing into it (heard as input and change)
- `t.pin_clock(datetime)` and `t.cdp.set_time_zone('America/Chicago')` — from the next page loaded, the page's clock says it is that time (and goes on from there) and is in that zone. The server's clock and what a suite seeds stay real, so this is for checking how a page counts days with nothing seeded by date (see `calendar`)
- `t.cdp.hold(path)` and `t.cdp.release_held()` — keep matching GET requests, so the page waits for them, then let them go: for making one file arrive after the others

### Things worth knowing

**A run is never split by midnight.** Seeded workouts and what a suite expects are counted in days from now, so the fixture
waits out the last three minutes before this machine's midnight (and says so) before it starts.

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
- Timing-sensitive checks use fixed pauses (about 470, in `t.cdp.pause`). On a heavily loaded machine, prefer
  `--jobs 1`. A pause that guards something that arrives, rather than a moment to be let pass, is better as
  `t.cdp.wait(...)` on what arrives.
- `pwa` relies on `127.0.0.1` counting as a secure context, which is how the
  browser is willing to run a service worker over plain HTTP. It therefore proves
  the worker behaves, not that any particular deployment is a secure context.
