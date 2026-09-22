# Workout Tracker

A workout tracker for creating, completing, reviewing, and analyzing workouts.

The frontend is plain HTML, CSS, and JavaScript. The backend is a single Python file that uses
nothing outside the standard library and stores data in SQLite, so self-hosting needs no package
manager, no build step, and no external database. Multiple accounts are supported, each with its
own workouts, templates, and settings.

**[Install it on Proxmox with one command.](#one-line-install-on-proxmox)**

## Features

### Workout tracking

- Create custom workouts with a name and workout date.
- Add exercises with weight and target reps.
- Edit exercise names, weights, and reps inline.
- Remove exercises before saving.
- Add notes to custom workouts.
- Validate exercise names, weights, reps, and dates with inline feedback.
- Save workouts to your account, so they follow you to any browser or device.

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

Custom templates are saved to your account on the server, and cached in the browser so they
still work while the server is unreachable.

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

Settings are saved to your account on the server and cached in the browser, so they persist
between visits and follow you to another device.

### Responsive design

- Desktop and mobile layouts.
- Responsive navigation and template cards.
- Mobile-friendly workout inputs and active workout controls.
- Responsive progress chart and settings modal.

## Project structure

```text
frontend/               Browser pages, scripts, and shared styles
backend/server.py       API, authentication, and static file server
data/                   SQLite database when run from a git checkout (gitignored)
ct/workout-tracker.sh   Proxmox VE one-line installer and updater
Dockerfile              Container image definition
docker-compose.yml      Docker deployment with a persistent volume
tests/                  Browser-level end-to-end tests (see tests/README.md)
```

## Self-hosting

Every account gets its own workouts, active session, templates, and settings, all kept in a
server-side SQLite file. Nothing is sent to an external service.

### One-line install on Proxmox

Open a **shell on the Proxmox VE host** (Datacenter → your node → Shell, or SSH as `root`) and run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/loganschwalm/WorkoutApp/main/ct/workout-tracker.sh)"
```

A menu offers default settings, advanced settings, or updating an existing install. The script then:

1. Downloads a Debian LXC template, to whichever storage on your node accepts templates.
2. Creates an unprivileged LXC with networking on `vmbr0` via DHCP.
3. Installs `python3`, `git`, and `sqlite3` inside it.
4. Clones this repository to `/opt/workout-tracker`.
5. Creates a `workout` system user and a `workout-tracker` systemd service that starts on boot.
6. Waits until the app actually answers on its port, then prints the URL.

If the service does not come up, the script fails loudly and prints the last 40 journal lines
rather than reporting success.

There is no Docker inside the container. The app is a single standard-library Python process, so a
systemd unit is both smaller and one less moving part than Docker nested in an unprivileged LXC.

When it finishes, open the printed URL and **register the first account**.

#### Defaults

| | |
|---|---|
| Container | unprivileged Debian 12, next free CTID, hostname `workout-tracker` |
| Resources | 1 core, 512 MB RAM, 512 MB swap, 4 GB disk |
| Network | bridge `vmbr0`, DHCP, starts on boot |
| App | `http://<container-ip>:8000` |
| Code | `/opt/workout-tracker` |
| Database | `/var/lib/workout-tracker/workouts.db` |

The database lives outside the code directory on purpose, so updates cannot touch your data.

#### Choosing settings without the menu

Every setting is also an environment variable, which is how you script the install or run it
non-interactively:

```bash
CTID=240 \
IP_CONFIG=192.168.1.50/24 \
GATEWAY=192.168.1.1 \
DNS_SERVER=192.168.1.1 \
MEMORY=1024 \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/loganschwalm/WorkoutApp/main/ct/workout-tracker.sh)"
```

| Variable | Default | Meaning |
|---|---|---|
| `CTID` | next free ID | LXC container ID |
| `CT_HOSTNAME` | `workout-tracker` | Container hostname |
| `CT_PASSWORD` | *(none)* | Root password; blank means console login is disabled and you use `pct enter` |
| `DEBIAN_VERSION` | `12` | Debian template major version, `12` or `13` |
| `STORAGE` | auto | Storage for the root disk, e.g. `local-lvm` |
| `TEMPLATE_STORAGE` | auto | Storage for the LXC template, e.g. `local` |
| `BRIDGE` | `vmbr0` | Network bridge |
| `IP_CONFIG` | `dhcp` | `dhcp`, or a CIDR address such as `192.168.1.50/24` |
| `GATEWAY` | *(none)* | Required with a static `IP_CONFIG` |
| `DNS_SERVER` | host's | DNS server for the container |
| `VLAN` | *(none)* | VLAN tag |
| `CORES` / `MEMORY` / `SWAP` / `DISK` | `1` / `512` / `512` / `4` | Cores, MB, MB, GB |
| `UNPRIVILEGED` | `1` | `0` creates a privileged container |
| `ONBOOT` | `1` | Start the container with the host |
| `APP_PORT` | `8000` | Port the app listens on |
| `REPO_URL` / `BRANCH` | this repo / `main` | Source to install from |
| `APP_DIR` / `DATA_DIR` | `/opt/workout-tracker` / `/var/lib/workout-tracker` | Code and database paths |

`STORAGE` and `TEMPLATE_STORAGE` are detected from the storages your node actually has: the script
asks when there is more than one candidate, and only offers storages that accept the right content
type. A template cannot live on `local-lvm`, so it is normally `local` even when the root disk is not.

#### Updating

Run the same command again on the Proxmox host and choose **Update an existing container**. That
fetches the latest commit, rewrites the systemd unit, and restarts the service. Your database is
untouched. You can also update from inside the container:

```bash
pct enter <CTID>
bash -c "$(curl -fsSL https://raw.githubusercontent.com/loganschwalm/WorkoutApp/main/ct/workout-tracker.sh)"
```

#### Managing the container

```bash
pct enter <CTID>                                     # shell
pct exec <CTID> -- systemctl status workout-tracker  # service state
pct exec <CTID> -- journalctl -u workout-tracker -f  # follow logs
pct exec <CTID> -- systemctl restart workout-tracker # restart
```

#### Backups

The install adds a `workout-tracker-backup` helper that takes a consistent snapshot while the app
keeps running, which a plain file copy of a live SQLite database does not give you:

```bash
pct exec <CTID> -- workout-tracker-backup            # writes to /var/backups/workout-tracker
```

For the whole container, use a normal Proxmox `vzdump` backup job. Because the database sits at
`/var/lib/workout-tracker/workouts.db` inside the container's root disk, a container backup covers it.

### Before you expose it

The server was written for a home network, and the defaults reflect that:

- **Registration is open.** Anyone who can reach the port can create an account. There is no admin
  role and no invite system, so create your accounts right after installing.
- **There is no HTTPS and no rate limiting.** Passwords are hashed with PBKDF2-SHA256 and sessions
  use `HttpOnly`, `SameSite=Lax` cookies, but the cookie is not marked `Secure`, so plain HTTP sends
  it in the clear.

Keep it on a trusted LAN, or put it behind a reverse proxy such as Caddy, Nginx Proxy Manager, or
Traefik that terminates TLS and adds authentication. Do not forward the port straight to the internet.

### Docker Compose

Useful if you already run Docker, or are self-hosting somewhere other than Proxmox. It needs
**Compose v2** (`docker compose`, the plugin). Debian's older `docker-compose` package is v1 and
misreads this compose file, so install Docker from Docker's own repository:

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/loganschwalm/WorkoutApp.git workout-tracker
cd workout-tracker
docker compose up -d --build
```

Open `http://YOUR_SERVER_IP:8000`. The database lives in the `workout_data` volume and survives
restarts and rebuilds.

```bash
docker compose logs -f                      # logs
docker compose down && git pull && docker compose up -d --build   # update
docker run --rm -v workout_data:/data -v "$PWD":/backup alpine \
  cp /data/workouts.db /backup/workouts.db  # back up
```

### Manual install on any Linux host

No container, no Docker. You need Python 3.9 or newer, with a SQLite that has JSON support (any
current distro), and nothing else.

```bash
sudo git clone https://github.com/loganschwalm/WorkoutApp.git /opt/workout-tracker
sudo useradd --system --no-create-home --shell /usr/sbin/nologin workout
sudo mkdir -p /var/lib/workout-tracker
sudo chown workout:workout /var/lib/workout-tracker

sudo tee /etc/systemd/system/workout-tracker.service >/dev/null <<'EOF'
[Unit]
Description=Workout Tracker
After=network-online.target
Wants=network-online.target

[Service]
User=workout
Group=workout
WorkingDirectory=/opt/workout-tracker
Environment=PORT=8000
Environment=APP_ROOT=/opt/workout-tracker/frontend
Environment=WORKOUT_DB=/var/lib/workout-tracker/workouts.db
ExecStart=/usr/bin/python3 /opt/workout-tracker/backend/server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now workout-tracker
```

The server reads three environment variables: `PORT` (default `8000`), `APP_ROOT` (the directory of
static files to serve, default `frontend/`), and `WORKOUT_DB` (the SQLite path, default `data/workouts.db`).

### Migrating from the browser-only version

Workouts saved in the older browser-only IndexedDB build are not uploaded automatically when you
move to a self-hosted server. They have to be re-entered; there is no import tool yet.

## Running locally

Serve it over HTTP rather than opening the files directly, so that IndexedDB and session cookies
behave the same as in a real deployment. From the project directory:

```bash
python backend/server.py
```

Then open <http://localhost:8000/> and register an account. Visiting a page while signed out
redirects to the login form, so start at the root rather than at `index.html`.

The database goes to `data/workouts.db` in the checkout, which is gitignored. Override any of
`PORT`, `APP_ROOT`, or `WORKOUT_DB` to change that:

```bash
PORT=9000 WORKOUT_DB=/tmp/scratch.db python backend/server.py
```

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

Each user's workout records are protected by the authenticated user ID in every database query.
Include the SQLite file in your backup plan: it is at `/var/lib/workout-tracker/workouts.db` in an
LXC install, and in the `workout_data` volume under Docker.

## Technology

- HTML5
- CSS3
- Vanilla JavaScript
- IndexedDB
- Local Storage
- HTML Canvas for progress charts
- Python standard library HTTP server
- SQLite
- systemd, Docker Compose, and a Proxmox LXC helper script for self-hosting
