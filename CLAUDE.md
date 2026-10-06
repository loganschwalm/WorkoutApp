# Workout Tracker

A self-hosted workout tracker: plain HTML/CSS/JS pages and a Python server that uses only the standard library, with SQLite.
There is no build step and no package manager for the app. `readme-for-llm.md` is the full reference (features, settings, deploying,
how each part works); `README.md` is the short version for people; `tests/README.md` describes every test suite. Read the
reference section for whatever you are about to change rather than guessing.

## Run it and check it

```bash
python backend/server.py                 # http://localhost:6769/, database in data/ (gitignored)
python scripts/demo-server.py            # the same, on a fresh database with three weeks of 5/3/1 and cardio logged

python -m pyflakes backend tests scripts docker-entrypoint.py
python tests/lint.py                     # the lists kept by hand agree with the files; no browser needed
python tests/run.py api                  # one suite (the API one needs no browser); no name runs them all, in parallel
```

The browser suites need Chrome, Chromium or Edge and `pip install -r tests/requirements.txt`. CI runs everything on Python 3.9 and
3.12, and moves the `stable` branch (what installs follow) only once all of it passes on `main`. Run `lint.py` and the suite for
the area you touched before saying something works; a failing check prints the value it observed.

## Rules that are easy to break

- **Python 3.9 is the floor.** `lint.py` parses every Python file as 3.9, which catches newer syntax (`match`) but not newer library
  calls (`zip(strict=True)`, `int.bit_count`), so CI's 3.9 run is what catches those. The server imports only the standard library:
  never add a dependency to `backend/`. `websocket-client` is for the tests only.
- **Migrations only append.** Add `migration_N_...` to the end of `MIGRATIONS` in `backend/database.py`; never edit one that has
  shipped, because databases in the wild have already run it.
- **A part of the account's synced state** (settings, templates, program, notes, goals, bodyweight, exercise library) is one entry in
  `STATE_PARTS` (`backend/state.py`), a column from a new migration, and its name in `accountStateParts` in `frontend/offline.js`.
  `lint.py` fails if the server's list and the page's differ.
- **An API endpoint** is a method in the right `backend/api_*.py` and a line in `ROUTES` in `backend/api_routes.py`. Anything not in the
  table is 401 signed out and 404 signed in, so a forgotten route is unreachable rather than open.
- **A new script or stylesheet** goes in the page that loads it and in `PRECACHE` in `frontend/sw.js`, or the page breaks the first
  time it is opened offline. Bump `VERSION` in `sw.js` only to drop old caches (when `PRECACHE` changes).
- **Pages share one global scope.** Plain `<script>` tags, no modules: no two files may declare the same top-level name (`lint.py`
  checks), and load order matters (the order in the HTML, mirrored in `PRECACHE`).
- **A new environment variable** is read only in `backend/config.py` (or the file that already reads its kind) and must be added to
  the server settings table in `readme-for-llm.md`; `lint.py` checks.
- **A new test suite** is a module in `tests/suites/`, listed in `NAMES` in `tests/suites/__init__.py`, with a row in `tests/README.md`.
- **No inline script or style, and nothing from another origin.** The Content-Security-Policy (`backend/config.py`) allows only files
  served from here. Text from users goes into the page with `textContent` or `escapeHTML`, never raw into `innerHTML`.
- **Offline first.** Changes are saved on the device and uploaded later (`frontend/offline.js`), so a client may retry any upload and
  may send a change made against an older copy. Endpoints that create things must be safe to repeat (see `clientId`), and changes to
  state are merged, not overwritten (`merge_values` in `backend/state.py`).
- **Repository text is LF** (`.gitattributes`); shell scripts must stay LF because they are piped straight into bash.

## Style

Comments say why, in full sentences, and are plentiful in the places that look odd; match that density. Lines are long (about 130
characters) and wrapped by sense. Names are plain words (`forget_reminders`, `request_allowance`), not abbreviations. Follow the
surrounding file rather than imposing a formatter: there is none.

## Documentation moves with the code

Behaviour a person can see goes in `README.md` (briefly) and `readme-for-llm.md` (fully) in the same change; `lint.py` checks the parts
that can drift mechanically (environment variables, suites), the rest is on you.
