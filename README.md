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
- View completed sets during the workout.
- Automatically start a configurable rest timer after each set.
- Pause and reset the rest timer.
- Move to the next exercise with the rest timer reset to the configured duration.
- Add notes while training.
- Restore an active workout after refreshing the page.
- Finish or cancel an active workout.

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
