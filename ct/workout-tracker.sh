#!/usr/bin/env bash
# Workout Tracker — Proxmox VE helper script
#
# Creates an unprivileged Debian LXC, installs the Workout Tracker as a systemd
# service, and prints the URL. Re-run it later to update.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/loganschwalm/WorkoutApp/main/ct/workout-tracker.sh)"
#
# Run as root on the Proxmox VE host. The same script also runs inside an
# already-installed container, where it performs an in-place update.
#
# License: MIT

set -Eeuo pipefail

APP="Workout Tracker"
SERVICE="workout-tracker"
CONF_DIR="/etc/workout-tracker"
CONF_FILE="$CONF_DIR/install.conf"

# Remember which app settings came from the environment, so an update inside a
# container can let them win over the values stored at install time.
_ENV_REPO_URL="${REPO_URL-}"
_ENV_BRANCH="${BRANCH-}"
_ENV_APP_DIR="${APP_DIR-}"
_ENV_DATA_DIR="${DATA_DIR-}"
_ENV_SERVICE_USER="${SERVICE_USER-}"
_ENV_APP_PORT="${APP_PORT-}"

REPO_URL="${REPO_URL:-https://github.com/loganschwalm/WorkoutApp.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/workout-tracker}"
DATA_DIR="${DATA_DIR:-/var/lib/workout-tracker}"
SERVICE_USER="${SERVICE_USER:-workout}"
APP_PORT="${APP_PORT:-8000}"

CTID="${CTID:-}"
CT_HOSTNAME="${CT_HOSTNAME:-workout-tracker}"
CT_PASSWORD="${CT_PASSWORD:-}"
DEBIAN_VERSION="${DEBIAN_VERSION:-12}"
STORAGE="${STORAGE:-}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-}"
BRIDGE="${BRIDGE:-vmbr0}"
IP_CONFIG="${IP_CONFIG:-dhcp}"
GATEWAY="${GATEWAY:-}"
DNS_SERVER="${DNS_SERVER:-}"
VLAN="${VLAN:-}"
CORES="${CORES:-1}"
MEMORY="${MEMORY:-512}"
SWAP="${SWAP:-512}"
DISK="${DISK:-4}"
UNPRIVILEGED="${UNPRIVILEGED:-1}"
ONBOOT="${ONBOOT:-1}"

if [[ -t 2 ]]; then
  RD=$'\033[01;31m'; GN=$'\033[1;92m'; YW=$'\033[33m'; BL=$'\033[36m'; CL=$'\033[m'
else
  RD=''; GN=''; YW=''; BL=''; CL=''
fi

# Progress goes to stderr so that functions can return values on stdout.
msg_info() { echo -e " ${BL}*${CL} $*" >&2; }
msg_ok()   { echo -e " ${GN}OK${CL} $*" >&2; }
msg_warn() { echo -e " ${YW}!${CL}  $*" >&2; }
die()      { echo -e " ${RD}ERROR: $*${CL}" >&2; exit 1; }

trap 'die "failed at line $LINENO: ${BASH_COMMAND}"' ERR

header() {
  echo -e "${BL}"
  cat <<'EOF'
 __        __         _               _     _____              _
 \ \      / /__  _ __| | _____  _   _| |_  |_   _| __ __ _  ___| | _____ _ __
  \ \ /\ / / _ \| '__| |/ / _ \| | | | __|   | || '__/ _` |/ __| |/ / _ \ '__|
   \ V  V / (_) | |  |   < (_) | |_| | |_    | || | | (_| | (__|   <  __/ |
    \_/\_/ \___/|_|  |_|\_\___/ \__,_|\__|   |_||_|  \__,_|\___|_|\_\___|_|
EOF
  echo -e "${CL}"
}

interactive() { [[ -t 0 && -t 2 ]] && command -v whiptail >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Container payload — runs inside the LXC for both install and update.
# ---------------------------------------------------------------------------
container_payload() {
  cat <<'PAYLOAD'
#!/usr/bin/env bash
set -Eeuo pipefail

CONF_FILE=/etc/workout-tracker/install.conf
[[ -f "$CONF_FILE" ]] || { echo "missing $CONF_FILE" >&2; exit 1; }
# shellcheck source=/dev/null
. "$CONF_FILE"

: "${REPO_URL:?}" "${BRANCH:?}" "${APP_DIR:?}" "${DATA_DIR:?}" "${APP_PORT:?}" "${SERVICE_USER:?}"

export DEBIAN_FRONTEND=noninteractive
step() { echo "    -> $*"; }

step "installing packages"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates curl git python3 sqlite3 tzdata >/dev/null

step "fetching source from $REPO_URL ($BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" remote set-url origin "$REPO_URL"
  git -C "$APP_DIR" fetch --quiet --force --depth 1 origin "$BRANCH:refs/remotes/origin/$BRANCH"
  git -C "$APP_DIR" checkout --quiet -f -B "$BRANCH" "refs/remotes/origin/$BRANCH"
  git -C "$APP_DIR" clean -qfd
else
  rm -rf "$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

if [[ ! -f "$APP_DIR/backend/server.py" || ! -d "$APP_DIR/frontend" ]]; then
  echo "unexpected repository layout in $APP_DIR (no backend/server.py or frontend/)" >&2
  exit 1
fi
step "source at $(git -C "$APP_DIR" rev-parse --short HEAD)"

step "preparing service account and data directory"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

step "writing systemd unit"
cat >/etc/systemd/system/workout-tracker.service <<UNIT
[Unit]
Description=Workout Tracker
Documentation=https://github.com/loganschwalm/WorkoutApp
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=PORT=$APP_PORT
Environment=APP_ROOT=$APP_DIR/frontend
Environment=WORKOUT_DB=$DATA_DIR/workouts.db
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $APP_DIR/backend/server.py
Restart=always
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=yes
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
UNIT

cat >/usr/local/bin/workout-tracker-backup <<'BACKUP'
#!/usr/bin/env bash
# Consistent snapshot of the Workout Tracker database, safe while it is running.
set -Eeuo pipefail
. /etc/workout-tracker/install.conf
dest="${1:-/var/backups/workout-tracker}"
mkdir -p "$dest"
out="$dest/workouts-$(date +%Y%m%d-%H%M%S).db"
sqlite3 "$DATA_DIR/workouts.db" ".backup '$out'"
echo "$out"
BACKUP
chmod 0755 /usr/local/bin/workout-tracker-backup

step "starting service"
systemctl daemon-reload
systemctl enable --quiet workout-tracker
systemctl restart workout-tracker

for _attempt in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${APP_PORT}/login.html"; then
    step "answering on port $APP_PORT"
    exit 0
  fi
  sleep 1
done

echo "workout-tracker did not answer on port $APP_PORT" >&2
systemctl status workout-tracker --no-pager --lines=0 >&2 || true
journalctl -u workout-tracker --no-pager --lines=40 >&2 || true
exit 1
PAYLOAD
}

render_conf() {
  cat <<EOF
# Written by the Workout Tracker Proxmox helper script.
REPO_URL='$REPO_URL'
BRANCH='$BRANCH'
APP_DIR='$APP_DIR'
DATA_DIR='$DATA_DIR'
SERVICE_USER='$SERVICE_USER'
APP_PORT='$APP_PORT'
EOF
}

# ---------------------------------------------------------------------------
# In-container mode: update this installation in place.
# ---------------------------------------------------------------------------
run_in_container() {
  [[ $EUID -eq 0 ]] || die "run this as root inside the container."

  # shellcheck source=/dev/null
  . "$CONF_FILE"
  [[ -n "$_ENV_REPO_URL" ]] && REPO_URL="$_ENV_REPO_URL"
  [[ -n "$_ENV_BRANCH" ]] && BRANCH="$_ENV_BRANCH"
  [[ -n "$_ENV_APP_DIR" ]] && APP_DIR="$_ENV_APP_DIR"
  [[ -n "$_ENV_DATA_DIR" ]] && DATA_DIR="$_ENV_DATA_DIR"
  [[ -n "$_ENV_SERVICE_USER" ]] && SERVICE_USER="$_ENV_SERVICE_USER"
  [[ -n "$_ENV_APP_PORT" ]] && APP_PORT="$_ENV_APP_PORT"

  local tmp
  tmp="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT

  mkdir -p "$CONF_DIR"
  render_conf >"$CONF_FILE"
  chmod 0644 "$CONF_FILE"
  container_payload >"$tmp/setup.sh"

  msg_info "Updating $APP in place"
  bash "$tmp/setup.sh"
  msg_ok "$APP updated and restarted"
}

# ---------------------------------------------------------------------------
# Proxmox host helpers
# ---------------------------------------------------------------------------
pick_storage() {
  # $1 = content type, $2 = prompt, $3 = preferred storage name
  local content="$1" prompt="$2" preferred="$3" s choice
  local -a list=() menu=()
  mapfile -t list < <(pvesm status --content "$content" 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')

  if [[ ${#list[@]} -eq 0 ]]; then
    die "no active Proxmox storage accepts '$content' content. Enable it under Datacenter > Storage."
  fi
  if [[ ${#list[@]} -eq 1 ]]; then
    printf '%s' "${list[0]}"
    return 0
  fi
  if ! interactive; then
    for s in "${list[@]}"; do
      if [[ "$s" == "$preferred" ]]; then
        printf '%s' "$s"
        return 0
      fi
    done
    printf '%s' "${list[0]}"
    return 0
  fi

  for s in "${list[@]}"; do menu+=("$s" "$content"); done
  choice="$(whiptail --title "$APP" --menu "$prompt" 16 62 6 "${menu[@]}" 3>&1 1>&2 2>&3)" ||
    die "cancelled."
  printf '%s' "$choice"
}

resolve_template() {
  local arch name volid
  arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  pveam update >/dev/null 2>&1 || true

  name="$(pveam available --section system 2>/dev/null |
    awk -v v="$DEBIAN_VERSION" -v a="$arch" \
      '$2 ~ "^debian-" v "-standard_.*_" a "[.]tar[.](zst|gz|xz)$" { print $2 }' |
    sort -V | tail -n1)"
  [[ -n "$name" ]] ||
    die "no Debian $DEBIAN_VERSION $arch LXC template is available. Try DEBIAN_VERSION=13."

  volid="$TEMPLATE_STORAGE:vztmpl/$name"
  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | awk '{print $1}' | grep -Fxq "$volid"; then
    msg_info "Downloading template $name to $TEMPLATE_STORAGE"
    pveam download "$TEMPLATE_STORAGE" "$name" >/dev/null
  fi
  msg_ok "Template ready: $name"
  printf '%s' "$volid"
}

container_ip() {
  local ip="" _attempt
  for _attempt in $(seq 1 45); do
    ip="$(pct exec "$1" -- ip -4 -o addr show scope global 2>/dev/null |
      awk '{print $4}' | cut -d/ -f1 | head -n1 || true)"
    [[ -n "$ip" ]] && break
    sleep 1
  done
  printf '%s' "$ip"
}

wait_for_container() {
  local _attempt
  for _attempt in $(seq 1 60); do
    pct exec "$CTID" -- test -d /proc/1 >/dev/null 2>&1 && break
    sleep 1
  done
  pct exec "$CTID" -- test -d /proc/1 >/dev/null 2>&1 || die "LXC $CTID did not become ready."

  msg_info "Waiting for network and DNS"
  for _attempt in $(seq 1 60); do
    if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then
      msg_ok "Network is up"
      return 0
    fi
    sleep 2
  done
  die "LXC $CTID has no working network or DNS. Check BRIDGE, IP_CONFIG, GATEWAY and DNS_SERVER."
}

installed_containers() {
  local id name
  while read -r id; do
    [[ -n "$id" ]] || continue
    if pct exec "$id" -- test -f "$CONF_FILE" >/dev/null 2>&1; then
      name="$(pct config "$id" 2>/dev/null | awk -F': ' '/^hostname:/ {print $2}')"
      echo "$id ${name:-lxc-$id}"
    fi
  done < <(pct list 2>/dev/null | awk 'NR>1 && $2=="running" {print $1}')
}

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
validate_settings() {
  [[ "$CTID" =~ ^[0-9]+$ && "$CTID" -ge 100 ]] || die "CTID must be a number >= 100 (got '$CTID')."
  [[ "$DEBIAN_VERSION" =~ ^[0-9]+$ ]] || die "DEBIAN_VERSION must be a number, such as 12 or 13."
  [[ "$CORES" =~ ^[0-9]+$ && "$CORES" -ge 1 ]] || die "CORES must be a positive integer."
  [[ "$MEMORY" =~ ^[0-9]+$ && "$MEMORY" -ge 128 ]] || die "MEMORY must be at least 128 (MB)."
  [[ "$SWAP" =~ ^[0-9]+$ ]] || die "SWAP must be an integer (MB)."
  [[ "$DISK" =~ ^[0-9]+$ && "$DISK" -ge 2 ]] || die "DISK must be at least 2 (GB)."
  [[ "$APP_PORT" =~ ^[0-9]+$ && "$APP_PORT" -ge 1 && "$APP_PORT" -le 65535 ]] ||
    die "APP_PORT must be between 1 and 65535."
  [[ "$UNPRIVILEGED" == "0" || "$UNPRIVILEGED" == "1" ]] || die "UNPRIVILEGED must be 0 or 1."
  [[ "$IP_CONFIG" == "dhcp" || "$IP_CONFIG" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] ||
    die "IP_CONFIG must be 'dhcp' or a CIDR address such as 192.168.1.50/24."
  if [[ "$IP_CONFIG" != "dhcp" && -z "$GATEWAY" ]]; then
    die "GATEWAY is required when IP_CONFIG is a static address."
  fi
  if [[ -n "$CT_PASSWORD" && ${#CT_PASSWORD} -lt 5 ]]; then
    die "CT_PASSWORD must be at least 5 characters (a Proxmox requirement)."
  fi
  if pct status "$CTID" >/dev/null 2>&1; then
    die "LXC $CTID already exists. Set CTID to a free ID."
  fi
  return 0
}

ask() {
  local answer
  answer="$(whiptail --title "$APP" --inputbox "$1" 9 66 "$2" 3>&1 1>&2 2>&3)" || die "cancelled."
  printf '%s' "${answer:-$2}"
}

advanced_settings() {
  CTID="$(ask "Container ID" "$CTID")"
  CT_HOSTNAME="$(ask "Hostname" "$CT_HOSTNAME")"
  DEBIAN_VERSION="$(ask "Debian version (12 or 13)" "$DEBIAN_VERSION")"
  CORES="$(ask "CPU cores" "$CORES")"
  MEMORY="$(ask "RAM in MB" "$MEMORY")"
  SWAP="$(ask "Swap in MB" "$SWAP")"
  DISK="$(ask "Disk in GB" "$DISK")"
  STORAGE="$(pick_storage rootdir "Storage for the container root disk" "local-lvm")"
  TEMPLATE_STORAGE="$(pick_storage vztmpl "Storage for the Debian template" "local")"
  BRIDGE="$(ask "Network bridge" "$BRIDGE")"
  IP_CONFIG="$(ask "IP address: 'dhcp' or CIDR such as 192.168.1.50/24" "$IP_CONFIG")"
  if [[ "$IP_CONFIG" != "dhcp" ]]; then
    GATEWAY="$(ask "Gateway" "$GATEWAY")"
    DNS_SERVER="$(ask "DNS server (blank uses the Proxmox host's)" "$DNS_SERVER")"
  fi
  VLAN="$(ask "VLAN tag (blank for none)" "$VLAN")"
  APP_PORT="$(ask "Port the app listens on" "$APP_PORT")"
  REPO_URL="$(ask "Git repository URL" "$REPO_URL")"
  BRANCH="$(ask "Git branch" "$BRANCH")"
  CT_PASSWORD="$(whiptail --title "$APP" --passwordbox \
    "Root password for the container.\n\nLeave blank for no password: you can always get a shell with 'pct enter' from the Proxmox host." \
    12 66 3>&1 1>&2 2>&3)" || die "cancelled."
  if whiptail --title "$APP" --yesno "Create an unprivileged container?\n\nYes is recommended." 10 66; then
    UNPRIVILEGED=1
  else
    UNPRIVILEGED=0
  fi
}

summary() {
  local privilege="unprivileged"
  [[ "$UNPRIVILEGED" == "1" ]] || privilege="privileged"
  cat >&2 <<EOF

  ${BL}Container${CL}   ID $CTID - $CT_HOSTNAME - Debian $DEBIAN_VERSION - $privilege
  ${BL}Resources${CL}   $CORES core(s) - $MEMORY MB RAM - $SWAP MB swap - $DISK GB disk
  ${BL}Storage${CL}     root disk: $STORAGE - template: $TEMPLATE_STORAGE
  ${BL}Network${CL}     $BRIDGE - $IP_CONFIG${GATEWAY:+ - gateway $GATEWAY}${VLAN:+ - vlan $VLAN}
  ${BL}App${CL}         $REPO_URL ($BRANCH) on port $APP_PORT

EOF
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
do_install() {
  local template net tmp ip
  template="$(resolve_template)"

  if [[ "$IP_CONFIG" == "dhcp" ]]; then
    net="name=eth0,bridge=$BRIDGE,ip=dhcp"
  else
    net="name=eth0,bridge=$BRIDGE,ip=$IP_CONFIG,gw=$GATEWAY"
  fi
  [[ -n "$VLAN" ]] && net="$net,tag=$VLAN"

  local -a create=(
    "$CTID" "$template"
    --hostname "$CT_HOSTNAME"
    --unprivileged "$UNPRIVILEGED"
    --cores "$CORES"
    --memory "$MEMORY"
    --swap "$SWAP"
    --rootfs "$STORAGE:$DISK"
    --net0 "$net"
    --features nesting=1
    --ostype debian
    --timezone host
    --onboot "$ONBOOT"
  )
  [[ -n "$DNS_SERVER" ]] && create+=(--nameserver "$DNS_SERVER")
  [[ -n "$CT_PASSWORD" ]] && create+=(--password "$CT_PASSWORD")

  msg_info "Creating LXC $CTID"
  pct create "${create[@]}" >/dev/null
  pct set "$CTID" --tags "workout-tracker" >/dev/null 2>&1 || true
  msg_ok "LXC $CTID created"

  msg_info "Starting LXC $CTID"
  pct start "$CTID" >/dev/null
  wait_for_container

  tmp="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT
  render_conf >"$tmp/install.conf"
  container_payload >"$tmp/setup.sh"

  pct exec "$CTID" -- mkdir -p "$CONF_DIR"
  pct push "$CTID" "$tmp/install.conf" "$CONF_FILE" --perms 0644
  pct push "$CTID" "$tmp/setup.sh" /root/workout-tracker-setup.sh --perms 0755

  msg_info "Installing $APP inside the container"
  pct exec "$CTID" -- bash /root/workout-tracker-setup.sh
  msg_ok "$APP installed"

  ip="$(container_ip "$CTID")"
  cat <<EOF

${GN}  $APP is ready.${CL}

  URL          http://${ip:-<container-ip>}:$APP_PORT
  Container    $CTID ($CT_HOSTNAME)
  Shell        pct enter $CTID
  Logs         pct exec $CTID -- journalctl -u $SERVICE -f
  Restart      pct exec $CTID -- systemctl restart $SERVICE
  App files    $APP_DIR
  Database     $DATA_DIR/workouts.db
  Backup       pct exec $CTID -- workout-tracker-backup

  Open the URL and register the first account. Registration is open to anyone
  who can reach the port, so create your accounts now and keep the app on a
  trusted network, or put it behind a reverse proxy that requires auth.

  To update later, run this same command again on the Proxmox host.

EOF
}

# ---------------------------------------------------------------------------
# Update an existing container, from the host
# ---------------------------------------------------------------------------
do_update() {
  local target tmp row
  local -a found=() menu=()
  msg_info "Looking for running containers with $APP installed"
  mapfile -t found < <(installed_containers)
  [[ ${#found[@]} -gt 0 ]] ||
    die "no running container has $APP installed. Start it first, or create a new one."

  if [[ ${#found[@]} -eq 1 ]] || ! interactive; then
    target="${found[0]%% *}"
    if [[ ${#found[@]} -gt 1 ]]; then
      msg_warn "${#found[@]} containers have $APP installed; updating LXC $target."
      msg_warn "Run this from a terminal to choose, or use 'pct enter <CTID>' on the one you want."
    fi
  else
    for row in "${found[@]}"; do menu+=("${row%% *}" "${row#* }"); done
    target="$(whiptail --title "$APP" --menu "Update which container?" 16 62 6 "${menu[@]}" \
      3>&1 1>&2 2>&3)" || die "cancelled."
  fi

  if [[ -n "$_ENV_REPO_URL$_ENV_BRANCH$_ENV_APP_PORT$_ENV_APP_DIR$_ENV_DATA_DIR$_ENV_SERVICE_USER" ]]; then
    msg_warn "An update reuses the settings stored in the container."
    msg_warn "Edit $CONF_FILE inside LXC $target to change them."
  fi

  tmp="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT
  container_payload >"$tmp/setup.sh"
  pct push "$target" "$tmp/setup.sh" /root/workout-tracker-setup.sh --perms 0755

  msg_info "Updating $APP in LXC $target"
  pct exec "$target" -- bash /root/workout-tracker-setup.sh
  msg_ok "$APP in LXC $target updated"
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main() {
  if ! command -v pct >/dev/null 2>&1; then
    if [[ -f "$CONF_FILE" ]]; then
      run_in_container
      return 0
    fi
    die "run this on a Proxmox VE host ('pct' not found), or inside an existing $APP container."
  fi

  [[ $EUID -eq 0 ]] || die "run this as root on the Proxmox VE host."
  command -v pvesm >/dev/null 2>&1 || die "'pvesm' not found; this does not look like a Proxmox VE host."

  header

  local action="install" choice
  if interactive; then
    choice="$(whiptail --title "$APP" --menu "Proxmox VE helper script" 15 66 4 \
      "1" "Create a new LXC with default settings" \
      "2" "Create a new LXC with advanced settings" \
      "3" "Update an existing $APP container" \
      "4" "Exit" 3>&1 1>&2 2>&3)" || die "cancelled."
    case "$choice" in
      1) action="install" ;;
      2) action="advanced" ;;
      3) action="update" ;;
      *) msg_info "Nothing to do."; return 0 ;;
    esac
  fi

  if [[ "$action" == "update" ]]; then
    do_update
    return 0
  fi

  [[ -n "$CTID" ]] || CTID="$(pvesh get /cluster/nextid)"
  [[ -n "$STORAGE" ]] || STORAGE="$(pick_storage rootdir "Storage for the container root disk" "local-lvm")"
  [[ -n "$TEMPLATE_STORAGE" ]] ||
    TEMPLATE_STORAGE="$(pick_storage vztmpl "Storage for the Debian template" "local")"

  if [[ "$action" == "advanced" ]]; then
    advanced_settings
  fi

  validate_settings
  summary

  if interactive && ! whiptail --title "$APP" --yesno "Create the container with these settings?" 8 66; then
    die "cancelled."
  fi

  do_install
}

main "$@"
