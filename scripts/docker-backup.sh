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

# Every account's workouts are in here: readable by whoever runs this, and no one else.
umask 077
mkdir -p "$dest"
out="$dest/workouts-$(date +%Y%m%d-%H%M%S).db"
snapshot=/app/data/backup-in-progress.db

docker compose exec -T workout-tracker python -c "
import os, sqlite3, sys
source = sqlite3.connect(os.environ.get('WORKOUT_DB', '/app/data/workouts.db'))
copy = sqlite3.connect(sys.argv[1])
source.backup(copy)
copy.close()
" "$snapshot"
docker compose cp "workout-tracker:$snapshot" "$out"
docker compose exec -T workout-tracker rm -f "$snapshot"

# The timestamp in each name sorts oldest to newest, so everything past the newest $keep goes.
find "$dest" -maxdepth 1 -name 'workouts-*.db' -printf '%f\n' | sort -r | tail -n +"$((keep + 1))" | while read -r old; do
  rm -f -- "$dest/$old"
done
echo "$out"
