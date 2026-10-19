#!/usr/bin/env bash
# What only root can check, as root on a machine to throw away: CI's runner, never a computer you use, since it installs a
# systemd service, writes to /etc, /opt and /var, and changes who owns files.
#
# Updating an install made by ct/workout-tracker.sh, end to end. It installs from a copy of this checkout and keeps a
# workout there, then updates to a version that migrates the database and then fails to start. That update must fail, put
# the previous version back with the database as it was before (the previous version refuses one a newer version
# migrated, so it only starts if the database really went back) and the systemd unit it had, and keep what the failed one
# left. The unit's sandbox is checked on the way, and that a database left readable by others is closed. A working update
# afterwards must go through with the workout still there, and one with nothing new must take no backup. The daily backup is run,
# pruned and then restored by the steps in the documentation.
#
# The Docker image's entrypoint handing the data directory to its user: what it can, saying what it cannot rather than
# stopping the container, and never the whole filesystem.
#
#   sudo bash tests/as-root.sh
set -Eeuo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo "Run this as root, on a machine to throw away." >&2; exit 1; }

port=6769
base="http://127.0.0.1:$port"
app=/opt/workout-tracker
db=/var/lib/workout-tracker/workouts.db
backups=/var/backups/workout-tracker
# On disk rather than in /tmp, which can be a tmpfs, where the entrypoint check's chattr does not work.
work="$(mktemp -d /var/tmp/as-root.XXXXXX)"
repo="$work/repo"
cookies="$work/cookies"

fail() {
  echo "  [FAIL] $*" >&2
  journalctl -u workout-tracker --no-pager --lines=60 >&2 || true
  exit 1
}
pass() { echo "  [PASS] $*"; }
commit() {
  git -C "$repo" add -A
  git -C "$repo" -c user.name=Test -c user.email=test@example.test commit --quiet -m "$1"
}
# Read whole, then searched: grep -q stops reading at the first match, which can fail curl's write under pipefail.
has_workout() { [[ "$(curl -fsS -b "$cookies" "$base/api/workouts")" == *'"Before The Update"'* ]]; }
# check <what it shows> <what was seen instead> <command...>: passes when the command succeeds.
check() {
  local label="$1" seen="$2"
  shift 2
  if "$@"; then pass "$label"; else fail "$label ($seen)"; fi
}
same() { [[ "$1" == "$2" ]]; }
not() { ! "$@"; }
broken_table_in() { [[ -n "$1" && -n "$(sqlite3 "$1" "SELECT name FROM sqlite_master WHERE name = 'broken_update'")" ]]; }
pre_update_backups() { find "$backups" -maxdepth 1 -name 'pre-update-*.db' | wc -l; }

echo 'I   installing from a copy of this checkout'
# The checkout belongs to the runner's user, which git run as root would refuse to read without being told it is safe.
mkdir -p "$repo"
git -c safe.directory="$PWD" archive HEAD | tar -x -C "$repo"
git -C "$repo" init --quiet --initial-branch=stable
commit 'The version installed first'
first="$(git -C "$repo" rev-parse HEAD)"
mkdir -p /etc/workout-tracker
cat >/etc/workout-tracker/install.conf <<EOF
REPO_URL='file://$repo'
BRANCH='stable'
APP_DIR='$app'
DATA_DIR='$(dirname "$db")'
SERVICE_USER='workout'
APP_PORT='$port'
PORT_DEFAULT_MOVED='1'
BRANCH_DEFAULT_MOVED='1'
BACKUP_KEEP='14'
EOF
bash ct/workout-tracker.sh || fail 'the install did not finish'
curl -fsS -c "$cookies" -H 'Content-Type: application/json' "$base/api/auth/register" \
  -d '{"username":"lifter","email":"lifter@example.test","password":"chalk-and-plates-42"}' >/dev/null || fail 'could not make an account'
curl -fsS -b "$cookies" -H 'Content-Type: application/json' "$base/api/workouts" \
  -d '{"name":"Before The Update","clientId":"before-update","exercises":[{"name":"Squat","reps":5}]}' >/dev/null || fail 'could not save a workout'
check 'installed, with a workout saved' 'not listed' has_workout
unit=/etc/systemd/system/workout-tracker.service
check 'the unit makes what the service writes private to it' "$(systemctl show -p UMask --value workout-tracker)" same "$(systemctl show -p UMask --value workout-tracker)" 0077
check 'and keeps all but the data directory read-only to it' "$(systemctl show -p ProtectSystem --value workout-tracker)" same "$(systemctl show -p ProtectSystem --value workout-tracker)" strict
check 'so the database it made is readable by it alone' "$(stat -c '%U %a' "$db")" same "$(stat -c '%U %a' "$db")" 'workout 600'

# --- host actions (begin) ---
echo 'H   ACTION and CTID say what the script on a Proxmox host does, with no menu: stand-in pct, pvesm and pvesh record what it asks of them'
stubs="$work/stubs"
pctlog="$work/pct.log"
mkdir -p "$stubs"
cat >"$stubs/pct" <<'STUB'
#!/usr/bin/env bash
# What a Proxmox host's pct answers: containers 105 and 106 are running, 107 is not, and the ones in STUB_INSTALLED have the app.
echo "pct $*" >>"$PCT_LOG"
case "$1" in
  list) printf 'VMID Status Lock Name\n105 running  workout\n106 running  other\n107 stopped  stopped\n' ;;
  config) echo "hostname: lxc-$2" ;;
  exec)
    id="$2"
    shift 3
    case "$*" in
      test\ -f\ *) [[ " ${STUB_INSTALLED:-105} " == *" $id "* ]] ;;
      ip\ *) echo '2: eth0    inet 192.0.2.5/24 brd 192.0.2.255 scope global eth0' ;;
      sh\ -c\ *) printf 6769 ;;
    esac ;;
esac
STUB
printf '#!/usr/bin/env bash\nexit 0\n' >"$stubs/pvesm"
printf '#!/usr/bin/env bash\necho 200\n' >"$stubs/pvesh"
chmod +x "$stubs/pct" "$stubs/pvesm" "$stubs/pvesh"
# The installer as it would be run on the host (no terminal here, so no menu), its answers in $work/host.out.
host() { PATH="$stubs:$PATH" PCT_LOG="$pctlog" env "$@" bash ct/workout-tracker.sh >"$work/host.out" 2>&1; }
asked() { grep -q -- "$1" "$pctlog"; }

: >"$pctlog"
check 'ACTION=bogus is refused' 'it went on' not host ACTION=bogus
check 'before it asked the host for anything' "$(grep -c . "$pctlog") calls" same "$(grep -c . "$pctlog")" 0
check 'and says what the choices are' 'no word of it' grep -q 'install, update or https' "$work/host.out"
check 'ACTION=advanced, which is all questions, needs a terminal' 'it went on' not host ACTION=advanced
check 'ACTION=update for a container that does not have the app is refused' 'it went on' not host ACTION=update CTID=106
check 'whatever else is installed, nothing is changed' 'it pushed something' not asked 'pct push'
check 'as is a container that is not running' 'it went on' not host ACTION=update CTID=107
STUB_INSTALLED="105 106"
export STUB_INSTALLED
check 'ACTION=update with a choice of containers and none named is refused' 'it picked one' not host ACTION=update
check 'and says which there are' 'no list' grep -q '105, 106' "$work/host.out"
check 'with nothing pushed to either' 'it pushed something' not asked 'pct push'
unset STUB_INSTALLED
: >"$pctlog"
check 'ACTION=update CTID=105 updates that container' 'it did not finish' host ACTION=update CTID=105
check 'by sending it the setup and running it there' 'no push' asked 'pct push 105 '
check 'once' "$(grep -c 'pct exec 105 -- bash /root/workout-tracker-setup.sh' "$pctlog") runs" same "$(grep -c 'pct exec 105 -- bash /root/workout-tracker-setup.sh' "$pctlog")" 1
check 'and creates nothing' 'it created a container' not asked 'pct create'
: >"$pctlog"
check 'with one container that has the app, update needs no CTID' 'it did not finish' host ACTION=update
check 'and it is that one' 'wrong container' asked 'pct exec 105 -- bash /root/workout-tracker-setup.sh'
# --- host actions (end) ---

echo 'F   an update to a version that migrates the database and then does not start'
# The unit as this install left it, marked, so that going back is seen to put the unit back as well as the code and the database.
echo '# the unit from before the update' >>"$unit"
systemctl daemon-reload
python3 - "$repo" <<'EOF'
import pathlib
import sys

backend = pathlib.Path(sys.argv[1]) / 'backend'
database = backend / 'database.py'
database.write_text(database.read_text() + "\n\ndef migration_broken_update(database):\n"
                    "    database.execute('CREATE TABLE broken_update (id INTEGER)')\n\n\nMIGRATIONS.append(migration_broken_update)\n")
webserver = backend / 'webserver.py'
text = webserver.read_text()
start = '    init_database()\n    port = '
assert text.count(start) == 1, 'serve() no longer starts the way this test expects'
webserver.write_text(text.replace(start, "    init_database()\n    raise SystemExit('This version fails on purpose, once it has migrated the database.')\n    port = "))
EOF
commit 'A version that migrates the database and then fails'
broken="$(git -C "$repo" rev-parse HEAD)"
if bash ct/workout-tracker.sh; then
  fail 'the update reported success, though the new version never answered'
fi
pass 'the update says it failed'
check 'the version from before is checked out again' "$(git -C "$app" rev-parse HEAD)" same "$(git -C "$app" rev-parse HEAD)" "$first"
check 'and answering' 'no answer' curl -fsS -o /dev/null "$base/api/auth/me"
check 'with the workout and the session from before the update' 'gone' has_workout
check 'and the unit is the one from before the update' 'the failed update left its own' grep -q 'the unit from before the update' "$unit"
check 'the database is back as it was before the update' 'it still has what the failed update added' not broken_table_in "$db"
check 'owned by the service, readable by it alone' "$(stat -c '%U %a' "$db")" same "$(stat -c '%U %a' "$db")" 'workout 600'
check 'the backup taken before the update is kept' "$(pre_update_backups) of them" same "$(pre_update_backups)" 1
failed_db="$(find "$backups" -path '*/failed-update-*'"${broken:0:7}"'/workouts.db' | head -n 1)"
check 'and what the failed update left is kept beside it' "${failed_db:-none}" broken_table_in "$failed_db"

echo 'U   an update that works, then one with nothing new'
git -C "$repo" -c user.name=Test -c user.email=test@example.test revert --quiet --no-edit HEAD
fixed="$(git -C "$repo" rev-parse HEAD)"
# A database from before the unit set its UMask is readable by anyone who can reach the directory; an update closes it.
chmod 0644 "$db"
bash ct/workout-tracker.sh || fail 'a working update failed'
check 'an update closes a database left open to others' "$(stat -c '%U %a' "$db")" same "$(stat -c '%U %a' "$db")" 'workout 600'
check 'a working update writes the unit again' 'it kept the old one' not grep -q 'the unit from before the update' "$unit"
check 'a working update goes through' "$(git -C "$app" rev-parse HEAD)" same "$(git -C "$app" rev-parse HEAD)" "$fixed"
check 'with the workout still there' 'gone' has_workout
check 'having backed the database up first' "$(pre_update_backups) of them" same "$(pre_update_backups)" 2
bash ct/workout-tracker.sh || fail 'an update with nothing new failed'
check 'an update with nothing new takes no backup' "$(pre_update_backups) of them" same "$(pre_update_backups)" 2

echo 'B   the daily backup, and putting one back by the steps in the documentation'
newest_kept() { [[ -f "$snap_after" && -f "$snap" && -f "$backups/workouts-20200104-000000.db" && ! -f "$backups/workouts-20200101-000000.db" ]]; }
has_after() { [[ "$(curl -fsS -b "$cookies" "$base/api/workouts")" == *'"After The Backup"'* ]]; }
daily() { find "$backups" -maxdepth 1 -name 'workouts-*.db' | wc -l; }
snap="$(workout-tracker-backup)"
check 'a backup made now is a database that opens' "$(sqlite3 "$snap" 'PRAGMA integrity_check')" same "$(sqlite3 "$snap" 'PRAGMA integrity_check')" ok
check 'with the workout saved before it' 'it is not there' same "$(sqlite3 "$snap" "SELECT COUNT(*) FROM workouts WHERE name = 'Before The Update'")" 1
check 'readable by root alone, in a directory of root alone' "$(stat -c '%a %a' "$snap" "$backups" | tr '\n' ' ')" same "$(stat -c '%a %a' "$snap" "$backups" | tr '\n' ' ')" '600 700 '
check 'and the backups taken before the updates are not touched by it' "$(pre_update_backups) of them" same "$(pre_update_backups)" 2
# Only the newest few are kept: older ones, named as a day's are, go; whatever else is there stays.
find "$backups" -maxdepth 1 -name 'workouts-*.db' ! -path "$snap" -delete
for day in 1 2 3 4; do cp "$snap" "$backups/workouts-2020010$day-000000.db"; done
sleep 1
cp /etc/workout-tracker/install.conf "$work/install.conf.kept"
sed -i "s/^BACKUP_KEEP=.*/BACKUP_KEEP='3'/" /etc/workout-tracker/install.conf
snap_after="$(workout-tracker-backup)"
cp "$work/install.conf.kept" /etc/workout-tracker/install.conf
check 'with BACKUP_KEEP at 3, three daily backups are left' "$(daily) of them" same "$(daily)" 3
check 'the newest ones' 'an old one stayed' newest_kept
check 'and the ones from before updates are still there' "$(pre_update_backups) of them" same "$(pre_update_backups)" 2

# The documented steps, as written under "Backups": the app is stopped, the backup put in place of the database, and the app started.
curl -fsS -b "$cookies" -H 'Content-Type: application/json' "$base/api/workouts" \
  -d '{"name":"After The Backup","clientId":"after-backup","exercises":[{"name":"Row","reps":8}]}' >/dev/null || fail 'could not save a workout after the backup'
check 'a workout saved after the backup is there' 'it is not' has_after
systemctl stop workout-tracker
cp "$snap" /var/lib/workout-tracker/workouts.db
rm -f /var/lib/workout-tracker/workouts.db-wal /var/lib/workout-tracker/workouts.db-shm
chown workout:workout /var/lib/workout-tracker/workouts.db
systemctl start workout-tracker
for _ in $(seq 1 30); do curl -fsS -o /dev/null "$base/api/auth/me" && break; sleep 1; done
check 'restored, the app answers' 'no answer' curl -fsS -o /dev/null "$base/api/auth/me"
check 'with the workout from before the backup' 'gone' has_workout
check 'and not the one saved after it' 'it is still there' not has_after
check 'the database is readable by the service alone again' "$(stat -c '%U %a' "$db")" same "$(stat -c '%U %a' "$db")" 'workout 600'

echo 'D   the Docker entrypoint hands the data directory over'
volume="$work/volume"
mkdir -p "$volume/inner"
touch "$volume/workouts.db" "$volume/inner/stuck.db"
# An immutable file stands in for one root cannot change: a volume on NFS that squashes root, or one mounted read-only.
chattr +i "$volume/inner/stuck.db"
nobody="$(id -u nobody):$(id -g nobody)"
cat >"$work/hand_over.py" <<'PYTHON'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location('entrypoint', 'docker-entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)
uid, gid = int(sys.argv[2]), int(sys.argv[3])
entrypoint.hand_over(sys.argv[1], uid, gid)
entrypoint.hand_over('/', uid, gid)
PYTHON
said="$(python3 "$work/hand_over.py" "$volume" "$(id -u nobody)" "$(id -g nobody)" 2>&1)" || fail "the entrypoint stopped: $said"
chattr -i "$volume/inner/stuck.db"
owner_of() { stat -c '%u:%g' "$1"; }
says() { grep -q "$1" <<<"$said"; }
check 'what it can change is handed over' "$(owner_of "$volume/workouts.db")" same "$(owner_of "$volume/workouts.db")" "$nobody"
check 'past what it cannot, without stopping' "$(owner_of "$volume/inner")" same "$(owner_of "$volume/inner")" "$nobody"
check 'and says what it could not' "$said" says 'stuck.db'
check 'the whole filesystem is never handed over' "$(owner_of /etc)" same "$(owner_of /etc)" '0:0'
check 'and it says why' "$said" says 'whole filesystem'
echo 'as-root: every check passed'
