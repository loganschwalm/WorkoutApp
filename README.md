# Workout Tracker

A browser-based workout tracker for creating, completing, reviewing, and analyzing workouts. The app is built with plain HTML, CSS, and JavaScript and stores data locally in the browser.

## Features

### Workout tracking

- Create custom workouts with a name and workout date.
- Add exercises with weight and target reps.
- Edit exercise names, weights, and reps inline.
- Remove exercises before saving.
- Add notes to custom workouts.
- Validate exercise names, weights, reps, and dates with inline feedback.
- Save workouts locally for future sessions.

### Guided workouts

- Start workouts from built-in templates or saved workouts.
- Move through exercises one at a time.
- Enter the weight and reps completed for each set.
- See how you did last time on each exercise; its weight and reps are prefilled, and after each set the next one defaults to the set you just logged.
- View completed sets during the workout, correct a set's weight or reps in place, or remove a set that was logged by mistake.
- Go back to a previous exercise, or add an exercise in the middle of a workout.
- Exercises with no logged sets count as skipped and are left out of the saved workout, so they never appear as done in History or Progress.
- Automatically start a configurable rest timer after each set.
- Pause and reset the rest timer.
- Keep accurate rest time even when the screen locks or the tab is in the background; the timer alerts you with a sound and vibration when rest is over (configurable in Settings).
- Keep the screen awake during a workout (on browsers that support it).
- Move to the next exercise with the rest timer reset to the configured duration.
- Add notes while training.
- Restore an active workout after refreshing the page.
- Finish or cancel an active workout.

### Network drops

Logged sets, notes, and finished workouts are saved on the device first and uploaded to the server in the background.

- If the server cannot be reached, keep training. A notice explains that your sets are stored on this device, and they upload automatically when the connection returns (retries back off up to one minute).
- Reloading the page while the server is unreachable restores the in-progress workout from the device.
- Finishing a workout while offline queues it locally and shows how many workouts are waiting to sync. The History and Progress pages upload anything queued before they load your workouts.
- Uploads are safe to retry: each finished workout carries a unique `clientId`, and the server ignores a repeat of one it already stored.
- Local copies are kept per account, so another account signed in on the same browser never sees them.
- If your sign-in expires while a page is open, a banner offers to sign in again and returns you to the same page; nothing on screen is discarded, and a workout in progress stays on the device.

Limitation: the page itself must already be loaded. Reloading while your device has no connection to the server at all still fails because the app's files are not cached for offline use yet.

### Workout templates

The app includes five built-in templates:

- Push Day
- Pull Day
- Leg Day
- Upper Body
- Full Body

Users can also:

- Create custom templates.
- Duplicate built-in or custom templates.
- Edit custom template names and exercises.
- Add, remove, and reorder template exercises.
- Delete custom templates.
- Start a workout directly from any template.

Custom templates are stored locally in the browser.

### Workout history

- Review all saved workouts on the History page.
- See workout dates, exercises, weights, reps, completed sets, and notes.
- Start a saved workout again from its history entry.
- Navigate between Tracker, Progress, and History pages.

### Progress analytics

- View progress as a responsive chart.
- Track heaviest weight, best reps, or total volume.
- Filter by exercise.
- Filter by workout type.
- Filter by start and end date.
- See filtered workout counts and chart legends.
- Review repeated workouts as separate progress points.

### Settings

The gear button opens a settings modal available on every page. Settings include:

- Light or dark mode.
- Default rest duration from 15 to 600 seconds.
- Automatic rest-timer start toggle.
- End-workout confirmation toggle.
- Rest-timer alert: play a sound on or off, choose the alert sound (double beep, chime, or long tone), set the volume, and turn vibration on or off. The vibration option only appears on devices that support it.
- A Test alert button plays the alert with the current choices, before you save them.
- The signed-in account name and a Sign out button. Signing out warns first if a workout has not finished syncing; it stays on the device and uploads the next time you sign in to the same account.

Settings persist locally between visits.

### Responsive design

- Desktop and mobile layouts.
- Responsive navigation and template cards.
- Mobile-friendly workout inputs and active workout controls.
- Responsive progress chart and settings modal.

## Project structure

```text
frontend/        Browser pages, scripts, and shared styles
backend/server.py Self-hosted API, authentication, and static file server
data/            Runtime SQLite database directory
Dockerfile       Container image definition
docker-compose.yml Docker deployment with persistent storage
scripts/install-proxmox-lxc.sh Proxmox LXC installation helper
tests/           Browser-level end-to-end tests (see tests/README.md)
```

## Self-hosted deployment

The app supports multi-user self-hosting. Each account has isolated workout records and active workout sessions in the server-side SQLite database. No external cloud provider is required.

### Docker Compose

On a Debian or Ubuntu VM/LXC running on Proxmox:

```bash
git clone <your-repository-url> workout-tracker
cd workout-tracker
docker compose up -d --build
```

Open `http://YOUR_SERVER_IP:8000` and create the first account. The SQLite database is stored in the persistent `workout_data` Docker volume and survives container restarts and upgrades.

Useful commands:

```bash
docker compose logs -f
docker compose restart
docker compose pull
docker compose up -d --build
```

For internet access, place the app behind a reverse proxy such as Caddy, Nginx Proxy Manager, or Traefik and enable HTTPS. Do not expose the raw HTTP port directly to the public internet without a reverse proxy and firewall rules.

### Proxmox guidance

1. Create a small Debian 12 VM or unprivileged LXC.
2. Give it a static DHCP lease or fixed IP.
3. Install Docker Engine and the Docker Compose plugin.
4. Clone the project into the VM/LXC.
5. Start it with `docker compose up -d --build`.
6. Back up the Docker volume containing `/app/data/workouts.db`.

The current server uses Python's standard library, SQLite, secure password hashing, HTTP-only session cookies, and per-user database queries.

### Proxmox helper script

The repository includes `scripts/install-proxmox-lxc.sh`. Run it as `root` on the Proxmox host to create an unprivileged Debian 12 LXC, install Docker and Docker Compose, clone the project, and start the application.

The script requires the Git repository URL:

```bash
chmod +x scripts/install-proxmox-lxc.sh
REPO_URL=https://github.com/your-account/workout-tracker.git \
	./scripts/install-proxmox-lxc.sh
```

By default it uses DHCP, `local-lvm`, `vmbr0`, 2 CPU cores, 1 GB RAM, and an 8 GB root disk. Configure a static address and other values with environment variables:

```bash
CTID=240 \
IP_CONFIG=192.168.1.50/24 \
GATEWAY=192.168.1.1 \
STORAGE=local-lvm \
BRIDGE=vmbr0 \
REPO_URL=https://github.com/your-account/workout-tracker.git \
	./scripts/install-proxmox-lxc.sh
```

The helper enables LXC `nesting` and `keyctl`, which Docker requires inside an unprivileged container. Review the script before running it in production and ensure your Proxmox backup plan includes the application data volume.

Existing workouts saved in the browser-only IndexedDB version are not automatically uploaded when the self-hosted server is enabled. They must be re-entered or migrated with a future import tool.

## Running locally

The app should be served over HTTP so IndexedDB works consistently across browsers, especially Firefox.

From the project directory, run:

```powershell
python backend/server.py
```

Then open:

- http://localhost:8000/index.html
- http://localhost:8000/progress.html
- http://localhost:8000/history.html

## Tests

The `tests/` directory holds end-to-end tests that drive a real headless browser
against a real server: no mocking, so a passing check means the feature works in a
browser. They cover the workout flow, the rest timer, offline syncing, the alert
settings, and in-workout usability.

```bash
pip install -r tests/requirements.txt
python tests/run.py
```

They need `websocket-client` and a Chrome, Chromium or Edge install; the app itself
still needs nothing beyond the Python standard library. See `tests/README.md` for the
suite breakdown and for how to add a test.

## Data storage

In the static browser-only mode, workout records, active sessions, and settings are stored in the browser using:

- IndexedDB for saved workouts and active workout recovery.
- `localStorage` for settings and custom templates.

Data is local to the browser and localhost origin. Clearing browser storage or using a different browser/device will not share the same data.

In self-hosted mode, saved workouts, active sessions, custom templates, and preferences are stored server-side per account in SQLite. Authentication uses PBKDF2 password hashing and HTTP-only session cookies. Browser local storage remains as a fallback for static browser-only use.

Each user's workout records are protected by the authenticated user ID in every database query. The SQLite file should be included in your regular Proxmox backup plan.

## Technology

- HTML5
- CSS3
- Vanilla JavaScript
- IndexedDB
- Local Storage
- HTML Canvas for progress charts
- Python standard library HTTP server
- SQLite
- Docker Compose
