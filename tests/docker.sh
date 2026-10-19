#!/usr/bin/env bash
# The Docker install as someone follows the README: `docker compose up -d --build` builds the image and starts it, and what it
# promises is checked from outside. The server answers and the container reports healthy; it runs as the workout user, not root;
# what is saved lives in the volume and survives a restart; scripts/docker-backup.sh makes a snapshot that opens and holds the
# workout, readable by its owner alone; and one that fails part way leaves nothing behind, in the backup directory or in the volume.
#
#   bash tests/docker.sh        (needs Docker with the compose plugin, and the ports 6769 free; it makes and removes a volume)
set -Eeuo pipefail
cd "$(dirname "$0")/.."

base=http://127.0.0.1:6769
work="$(mktemp -d)"
cookies="$work/cookies"

fail() {
  echo "  [FAIL] $*" >&2
  echo "::error::$*"
  docker compose logs --no-color --tail=60 >&2 || true
  exit 1
}
pass() { echo "  [PASS] $*"; }
check() {
  local label="$1" seen="$2"
  shift 2
  if "$@"; then pass "$label"; else fail "$label ($seen)"; fi
}
same() { [[ "$1" == "$2" ]]; }
not() { ! "$@"; }
# Whatever stops it is reported with the last command it ran and where (set -e ends it on a command that fails where nothing checks
# it), then the stack and the volume are taken away.
cleanup() {
  local status=$?
  ((status == 0)) || echo "::error::tests/docker.sh stopped with status $status at line $LINENO, in: $BASH_COMMAND"
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

has_workout() { [[ "$(curl -fsS -b "$cookies" "$base/api/workouts")" == *'"Docker Day"'* ]]; }
answering() { curl -fsS -o /dev/null "$base/api/auth/me"; }
# What the container's first process runs as: the entrypoint starts as root only to hand the volume over, and the server is not root.
server_user() { docker compose exec -T workout-tracker python -c "print(open('/proc/1/status').read().split('Uid:')[1].split()[0])"; }
in_volume() { docker compose exec -T workout-tracker ls /app/data; }

echo 'I   building the image and starting it as the README says'
docker compose up -d --build >/dev/null 2>&1 || fail 'docker compose up --build did not finish'
for _ in $(seq 1 120); do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' workout-tracker 2>/dev/null || true)" == healthy ]] && break
  sleep 2
done
check 'the container reports healthy' "$(docker inspect -f '{{.State.Health.Status}}' workout-tracker)" same "$(docker inspect -f '{{.State.Health.Status}}' workout-tracker)" healthy
check 'and the server answers outside it' 'no answer' answering
check 'the server is not running as root' "user $(server_user)" not same "$(server_user)" 0

echo 'S   what is saved lives in the volume'
curl -fsS -c "$cookies" -H 'Content-Type: application/json' "$base/api/auth/register" \
  -d '{"username":"lifter","email":"lifter@example.test","password":"chalk-and-plates-42"}' >/dev/null || fail 'could not make an account'
curl -fsS -b "$cookies" -H 'Content-Type: application/json' "$base/api/workouts" \
  -d '{"name":"Docker Day","clientId":"docker-day","exercises":[{"name":"Squat","reps":5}]}' >/dev/null || fail 'could not save a workout'
check 'a workout is saved' 'not listed' has_workout
docker compose restart >/dev/null 2>&1 || fail 'could not restart'
for _ in $(seq 1 60); do answering && break; sleep 1; done
check 'and is still there after the container restarts, signed in as before' 'gone' has_workout
check 'the database belongs to the workout user' "$(docker compose exec -T workout-tracker stat -c '%U' /app/data/workouts.db)" same "$(docker compose exec -T workout-tracker stat -c '%U' /app/data/workouts.db)" workout

echo 'B   scripts/docker-backup.sh'
backups="$work/backups"
snap="$(bash scripts/docker-backup.sh "$backups")"
check 'a backup is made' 'no file' test -f "$snap"
check 'it is a database that opens' "$(sqlite3 "$snap" 'PRAGMA integrity_check')" same "$(sqlite3 "$snap" 'PRAGMA integrity_check')" ok
check 'holding the workout' 'not there' same "$(sqlite3 "$snap" "SELECT COUNT(*) FROM workouts WHERE name = 'Docker Day'")" 1
check 'readable by its owner alone, in a directory of its owner alone' "$(stat -c '%a %a' "$snap" "$backups" | tr '\n' ' ')" same "$(stat -c '%a %a' "$snap" "$backups" | tr '\n' ' ')" '600 700 '
check 'and no copy is left in the volume' "$(in_volume | tr '\n' ' ')" not grep -q backup-in-progress < <(in_volume)

# docker compose cp is what fails here, after the snapshot has been made in the volume: the case the script's cleanup is for.
mkdir -p "$work/shim"
cat >"$work/shim/docker" <<SHIM
#!/usr/bin/env bash
if [[ "\$1 \$2" == "compose cp" ]]; then echo "docker: the copy failed, as a full disk would" >&2; exit 1; fi
exec $(command -v docker) "\$@"
SHIM
chmod +x "$work/shim/docker"
failed_backups="$work/failed-backups"
check 'a backup that fails part way fails' 'it said it worked' not env PATH="$work/shim:$PATH" bash scripts/docker-backup.sh "$failed_backups"
check 'and leaves nothing in the backup directory' "$(find "$failed_backups" -type f | wc -l) files" same "$(find "$failed_backups" -type f | wc -l)" 0
check 'nor a copy of the database in the volume' "$(in_volume | tr '\n' ' ')" not grep -q backup-in-progress < <(in_volume)
echo 'docker: every check passed'
