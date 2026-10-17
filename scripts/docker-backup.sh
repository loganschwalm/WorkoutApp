#!/usr/bin/env bash
# Back up a Docker Compose install's database: a consistent snapshot taken inside the running container (a plain copy
# of workouts.db can miss recent changes still in workouts.db-wal), copied out to a directory on the host, keeping the
# newest KEEP (14 unless set). Run it from anywhere; it works from the checkout it is in.
#
#   scripts/docker-backup.sh [directory]            default /var/backups/workout-tracker
#   KEEP=30 scripts/docker-backup.sh
#
# Every day at about half past three, from /etc/cron.d/workout-tracker-backup on the Docker host:
#   30 3 * * * root /path/to/workout-tracker/scripts/docker-backup.sh
set -Eeuo pipefail
cd "$(dirname "$0")/.."

dest="${1:-/var/backups/workout-tracker}"
keep="${KEEP:-14}"
[[ "$keep" =~ ^[1-9][0-9]*$ ]] || { echo "KEEP must be a whole number of backups, not '$keep'." >&2; exit 1; }

# Every account's workouts are in here: readable by whoever runs this, and no one else, a directory that was already there
# included.
umask 077
mkdir -p "$dest"
chmod 0700 "$dest"
out="$dest/workouts-$(date +%Y%m%d-%H%M%S).db"
snapshot=/app/data/backup-in-progress.db

# The snapshot is a whole copy of the database left in the volume (as root, who docker compose exec runs as), and a copy
# cut short is no backup: both go however this ends. The copy is only named as a backup once it is whole.
cleanup() {
  docker compose exec -T workout-tracker rm -f "$snapshot" >/dev/null 2>&1 || true
  rm -f -- "$out.partial"
}
trap cleanup EXIT

docker compose exec -T workout-tracker python -c "
import os, sqlite3, sys
source = sqlite3.connect(os.environ.get('WORKOUT_DB', '/app/data/workouts.db'))
copy = sqlite3.connect(sys.argv[1])
source.backup(copy)
copy.close()
" "$snapshot"
docker compose cp "workout-tracker:$snapshot" "$out.partial"
# docker compose cp keeps the mode the file had in the container rather than following the umask.
chmod 0600 "$out.partial"
mv "$out.partial" "$out"

# The timestamp in each name sorts oldest to newest, so everything past the newest $keep goes.
find "$dest" -maxdepth 1 -name 'workouts-*.db' -printf '%f\n' | sort -r | tail -n +"$((keep + 1))" | while read -r old; do
  rm -f -- "$dest/$old"
done
echo "$out"
