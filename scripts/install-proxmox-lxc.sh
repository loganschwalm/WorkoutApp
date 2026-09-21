#!/usr/bin/env bash
set -Eeuo pipefail

# Install the Workout Tracker in a Docker-enabled Debian LXC on a Proxmox host.
# Run this script as root on the Proxmox host itself.

CTID="${CTID:-}" 
CT_HOSTNAME="${CT_HOSTNAME:-workout-tracker}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
IP_CONFIG="${IP_CONFIG:-dhcp}"
GATEWAY="${GATEWAY:-}"
REPO_URL="${REPO_URL:-}"
APP_DIR="${APP_DIR:-/opt/workout-tracker}"
CORES="${CORES:-2}"
MEMORY="${MEMORY:-1024}"
SWAP="${SWAP:-512}"
DISK="${DISK:-8}"
START="${START:-1}"

usage() {
  cat <<'EOF'
Usage:
  REPO_URL=https://github.com/you/workout-tracker.git ./install-proxmox-lxc.sh

Required:
  REPO_URL       Git repository containing the Workout Tracker project

Optional environment variables:
  CTID            LXC ID; automatically selects the next available ID when omitted
  CT_HOSTNAME     Container hostname (default: workout-tracker)
  STORAGE         Proxmox storage for the root disk (default: local-lvm)
  BRIDGE          Network bridge (default: vmbr0)
  IP_CONFIG       dhcp or a static CIDR such as 192.168.1.50/24
  GATEWAY         Gateway required for static IP configuration
  APP_DIR         App path inside the container (default: /opt/workout-tracker)
  CORES           Container CPU cores (default: 2)
  MEMORY          Container memory in MB (default: 1024)
  SWAP            Container swap in MB (default: 512)
  DISK            Root disk size in GB (default: 8)
  START           Start container after installation, 1 or 0 (default: 1)

Example with a static address:
  CTID=240 IP_CONFIG=192.168.1.50/24 GATEWAY=192.168.1.1 \
    REPO_URL=https://github.com/you/workout-tracker.git \
    ./install-proxmox-lxc.sh
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

[[ "${EUID}" -eq 0 ]] || fail "Run this script as root on the Proxmox host."
[[ -n "$REPO_URL" ]] || { usage; fail "REPO_URL is required."; }
require_command pct
require_command pveam

if [[ -z "$CTID" ]]; then
  CTID="$(pvesh get /cluster/nextid)"
fi
[[ "$CTID" =~ ^[0-9]+$ ]] || fail "CTID must be numeric."
[[ "$IP_CONFIG" == "dhcp" || "$IP_CONFIG" =~ ^[^/]+/[0-9]+$ ]] || fail "IP_CONFIG must be dhcp or a CIDR address."
if [[ "$IP_CONFIG" != "dhcp" && -z "$GATEWAY" ]]; then
  fail "GATEWAY is required when IP_CONFIG is static."
fi

if pct status "$CTID" >/dev/null 2>&1; then
  fail "LXC $CTID already exists."
fi

TEMPLATE_NAME="$(pveam available --section system | awk '$2 ~ /^debian-12-standard_.*amd64/ {print $2}' | sort -V | tail -n 1)"
[[ -n "$TEMPLATE_NAME" ]] || fail "Could not find a Debian 12 amd64 LXC template."
TEMPLATE_PATH="$STORAGE:vztmpl/$TEMPLATE_NAME"
if ! pveam list "$STORAGE" | awk '{print $1}' | grep -Fxq "$TEMPLATE_PATH"; then
  echo "Downloading $TEMPLATE_NAME to $STORAGE..."
  pveam download "$STORAGE" "$TEMPLATE_NAME"
fi

if [[ "$IP_CONFIG" == "dhcp" ]]; then
  NET0="name=eth0,bridge=$BRIDGE,ip=dhcp,type=veth"
else
  NET0="name=eth0,bridge=$BRIDGE,ip=$IP_CONFIG,gw=$GATEWAY,type=veth"
fi

echo "Creating unprivileged LXC $CTID..."
pct create "$CTID" "$TEMPLATE_PATH" \
  --hostname "$CT_HOSTNAME" \
  --unprivileged 1 \
  --cores "$CORES" \
  --memory "$MEMORY" \
  --swap "$SWAP" \
  --rootfs "$STORAGE:$DISK" \
  --net0 "$NET0" \
  --features nesting=1,keyctl=1 \
  --onboot 1

pct start "$CTID"
for attempt in $(seq 1 30); do
  if pct exec "$CTID" -- true >/dev/null 2>&1; then break; fi
  sleep 1
done
pct exec "$CTID" -- true >/dev/null 2>&1 || fail "LXC did not become ready."

echo "Installing Docker, Compose, Git, and certificates..."
pct exec "$CTID" -- bash -lc 'export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y ca-certificates curl git docker.io docker-compose; systemctl enable --now docker'

pct exec "$CTID" -- bash -lc "rm -rf '$APP_DIR'; mkdir -p \"$(dirname "$APP_DIR")\"; git clone '$REPO_URL' '$APP_DIR'"
pct exec "$CTID" -- bash -lc "cd '$APP_DIR'; docker-compose up -d --build"

CONTAINER_IP="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
cat <<EOF

Workout Tracker installed successfully.

LXC ID:       $CTID
Hostname:     $CT_HOSTNAME
Container IP: ${CONTAINER_IP:-unknown}
App URL:      http://${CONTAINER_IP:-<container-ip>}:8000
Project path: $APP_DIR

Create the first user account from the app login page.
Back up the Docker volume or the SQLite file at $APP_DIR/data/workouts.db.
EOF
