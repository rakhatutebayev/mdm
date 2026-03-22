#!/usr/bin/env bash
# NOCKO Linux Proxy Agent — bootstrap installer (TZ §5 One-Command Deploy)
#
# One-liner (MDM injects NOCKO_MDM_BASE):
#   curl -fsSL "https://<mdm>/api/v1/agent/bootstrap/install.sh" | sudo bash -s -- '<enrollment_token>'
#
# Local tree (dev / air-gapped):
#   sudo bash install.sh '<token>'
#
# Update / uninstall (after install, from /opt copy):
#   sudo /opt/nocko-agent/install.sh --update
#   sudo /opt/nocko-agent/install.sh --uninstall
#
# Env: NOCKO_MDM_BASE — MDM origin (https://...) for remote download & API calls

set -euo pipefail

AGENT_USER="nocko-agent"
INSTALL_DIR="/opt/nocko-agent"
DATA_DIR="/var/lib/nocko-agent"
CERT_DIR="/etc/nocko-agent/certs"
LOG_DIR="/var/log/nocko-agent"
SERVICE_NAME="nocko-agent"
PYTHON_MIN="3.11"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

usage() {
  cat <<EOF
Usage:
  sudo bash install.sh [options] [<enrollment_token>]

Options:
  --update      Download latest linux bundle from MDM, verify sha256, replace /opt (rollback on failure)
  --uninstall   Stop service, POST /api/v1/agent/unregister, remove install dirs (keep $DATA_DIR)
  -h, --help    This help

Remote install requires NOCKO_MDM_BASE or bootstrap URL from MDM (injected automatically).
EOF
}

# ─── Args ─────────────────────────────────────────────────────────────────────
ACTION="install"
ENROLLMENT_TOKEN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --update)   ACTION="update"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) ENROLLMENT_TOKEN="${1:-}"; shift ;;
  esac
done

SELF="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"

# ─── Remote bootstrap: no local proxy-agent tree (e.g. curl | bash) ────────────
if [[ ! -f "$SCRIPT_DIR/watcher.py" ]]; then
  remote_bootstrap() {
    [[ $EUID -eq 0 ]] || error "Must run as root (sudo bash)"
    [[ -n "${NOCKO_MDM_BASE:-}" ]] || error \
      "NOCKO_MDM_BASE not set. Use: curl -fsSL '<mdm>/api/v1/agent/bootstrap/install.sh' | sudo bash -s -- '<token>'"
    NOCKO_MDM_BASE="${NOCKO_MDM_BASE%/}"
    info "Remote bootstrap from $NOCKO_MDM_BASE"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates openssl
    if ! command -v python3 >/dev/null 2>&1; then
      apt-get install -y -qq python3-minimal
    fi
    META=$(curl -fsSL "${NOCKO_MDM_BASE}/api/v1/agent/linux-bundle") \
      || error "Failed to GET ${NOCKO_MDM_BASE}/api/v1/agent/linux-bundle"
    URL=$(printf '%s' "$META" | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])")
    SHA=$(printf '%s' "$META" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha256'])")
    SIGURL=$(printf '%s' "$META" | python3 -c "import json,sys; print(json.load(sys.stdin).get('signature_url') or '')")
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    curl -fSL "$URL" -o "$TMP/bundle.tar.gz"
    if command -v sha256sum >/dev/null 2>&1; then
      echo "$SHA  $TMP/bundle.tar.gz" | sha256sum -c - || error "SHA256 mismatch — bundle rejected (TZ §5.3)"
    else
      echo "$SHA  $TMP/bundle.tar.gz" | shasum -a 256 -c - || error "SHA256 mismatch — bundle rejected (TZ §5.3)"
    fi
    if [[ -n "$SIGURL" ]] && command -v minisign >/dev/null 2>&1; then
      curl -fsSL "$SIGURL" -o "$TMP/bundle.minisig" || true
      if [[ -f "$TMP/bundle.minisig" ]]; then
        minisign -V -p /etc/nocko-agent/minisign.pub -m "$TMP/bundle.tar.gz" -s "$TMP/bundle.minisig" \
          2>/dev/null || warn "minisign verify skipped or failed (install /etc/nocko-agent/minisign.pub to enforce)"
      fi
    fi
    tar xzf "$TMP/bundle.tar.gz" -C "$TMP"
    [[ -f "$TMP/proxy-agent/install.sh" ]] || error "Invalid bundle: expected proxy-agent/install.sh in tarball"
    # Remote path only supports fresh install; pass enrollment token only
    exec bash "$TMP/proxy-agent/install.sh" ${ENROLLMENT_TOKEN:+"$ENROLLMENT_TOKEN"}
  }
  # Re-exec passes ACTION only if not install; token as last arg
  if [[ "$ACTION" == "install" ]]; then
    remote_bootstrap
  else
    error "Remote mode only supports fresh install. For --update/--uninstall use: sudo $INSTALL_DIR/install.sh ..."
  fi
fi

# ─── From here: full tree present (local or extracted bundle) ────────────────

# ─── Uninstall (TZ §5.4) ───────────────────────────────────────────────────────
if [[ "$ACTION" == "uninstall" ]]; then
  [[ $EUID -eq 0 ]] || error "Must run as root"
  info "Stopping $SERVICE_NAME..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload 2>/dev/null || true

  CFG="$INSTALL_DIR/config.json"
  MDM_URL=""
  if [[ -f "$CFG" ]]; then
    MDM_URL=$(python3 -c "import json; print(json.load(open('$CFG')).get('mdm_url',''))" 2>/dev/null || true)
  fi
  DB_PATH="$DATA_DIR/agent.db"
  TOKEN=""
  if [[ -f "$DB_PATH" ]] && command -v sqlite3 >/dev/null 2>&1; then
    TOKEN=$(sqlite3 "$DB_PATH" "select value from agent_config where key='auth_token';" 2>/dev/null || true)
  fi
  if [[ -n "${MDM_URL:-}" && -n "${TOKEN:-}" ]]; then
    MDM_URL="${MDM_URL%/}"
    info "Unregistering agent on MDM..."
    curl -fsSL -X POST "${MDM_URL}/api/v1/agent/unregister" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" -d '{}' \
      || warn "Unregister request failed (agent may already be revoked)"
  else
    warn "Skipping unregister (no mdm_url or auth_token in local DB)"
  fi

  rm -rf "$INSTALL_DIR" "$CERT_DIR" "$LOG_DIR"
  info "Removed install, cert, and log dirs. Preserved data (TZ §5.4): $DATA_DIR"
  exit 0
fi

# ─── Update (TZ §5.3) ──────────────────────────────────────────────────────────
if [[ "$ACTION" == "update" ]]; then
  [[ $EUID -eq 0 ]] || error "Must run as root"
  CFG="$INSTALL_DIR/config.json"
  [[ -f "$CFG" ]] || error "Not installed ($CFG missing)"
  MDM_URL=$(python3 -c "import json; print(json.load(open('$CFG')).get('mdm_url',''))" 2>/dev/null || true)
  MDM_URL="${MDM_URL%/}"
  [[ -n "$MDM_URL" ]] || error "mdm_url missing in $CFG — cannot fetch update"

  apt-get update -qq
  apt-get install -y -qq curl ca-certificates python3-minimal
  META=$(curl -fsSL "${MDM_URL}/api/v1/agent/linux-bundle") \
    || error "Failed to fetch linux-bundle"
  URL=$(printf '%s' "$META" | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])")
  SHA=$(printf '%s' "$META" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha256'])")

  TMP=$(mktemp -d)
  BACKUP="/tmp/nocko-agent-pre-update.$$"
  trap 'rm -rf "$TMP"' EXIT
  curl -fSL "$URL" -o "$TMP/bundle.tar.gz"
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$SHA  $TMP/bundle.tar.gz" | sha256sum -c - || error "SHA256 mismatch — update aborted"
  else
    echo "$SHA  $TMP/bundle.tar.gz" | shasum -a 256 -c - || error "SHA256 mismatch — update aborted"
  fi

  tar xzf "$TMP/bundle.tar.gz" -C "$TMP"
  NEW_TREE="$TMP/proxy-agent"
  [[ -d "$NEW_TREE" ]] || error "Invalid bundle layout"

  info "Stopping service for in-place update..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true

  if ! mv "$INSTALL_DIR" "$BACKUP"; then
    error "Failed to backup $INSTALL_DIR"
  fi

  rollback() {
    warn "Rolling back..."
    rm -rf "$INSTALL_DIR" 2>/dev/null || true
    mv "$BACKUP" "$INSTALL_DIR" 2>/dev/null || true
    systemctl start "$SERVICE_NAME" 2>/dev/null || true
    error "Update failed — restored previous install"
  }

  if ! cp -a "$NEW_TREE" "$INSTALL_DIR"; then
    rollback
  fi

  if [[ -f "$BACKUP/config.json" ]]; then
    cp -a "$BACKUP/config.json" "$INSTALL_DIR/config.json" || rollback
  fi

  chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"
  if [[ -f "$INSTALL_DIR/.venv/bin/pip" ]]; then
    if ! sudo -u "$AGENT_USER" env HOME="$DATA_DIR" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"; then
      rollback
    fi
  else
    warn "No venv yet — running full dependency install"
    python3 -m venv "$INSTALL_DIR/.venv"
    "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
    "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" || rollback
    chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"
  fi

  PYTHON_BIN="$INSTALL_DIR/.venv/bin/python3"
  setcap 'cap_net_bind_service=+ep' "$PYTHON_BIN" 2>/dev/null \
    || warn "setcap failed — trap receiver may need extra privileges"

  systemctl daemon-reload
  if ! systemctl start "$SERVICE_NAME"; then
    rollback
  fi

  rm -rf "$BACKUP"
  info "Update OK — $SERVICE_NAME restarted (TZ §5.3)"
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Fresh install (TZ §5.2 steps)
# ═══════════════════════════════════════════════════════════════════════════════

info "Pre-flight check..."
[[ $EUID -eq 0 ]] || error "Must run as root (sudo bash install.sh)"

. /etc/os-release 2>/dev/null || true
if [[ "${ID:-}" != "ubuntu" ]] && [[ "${ID_LIKE:-}" != *"ubuntu"* ]]; then
  warn "Non-Ubuntu OS detected. Proceeding anyway (may fail)."
fi

PY=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
  info "Python $PY ✓"
else
  error "Python $PYTHON_MIN+ required. Found: $PY. Install: sudo apt install python3.11"
fi

FREE_MB=$(df /opt --output=avail 2>/dev/null | tail -1 | tr -d ' ' || echo "9999999")
FREE_MB=$((FREE_MB / 1024))
[[ $FREE_MB -ge 500 ]] || error "Insufficient disk space ($FREE_MB MB free, need 500 MB)"

info "Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3-pip python3-venv python3-dev \
  curl openssl git libsnmp-dev snmp \
  net-tools ca-certificates sqlite3

info "Creating system user $AGENT_USER..."
if ! id "$AGENT_USER" &>/dev/null; then
  useradd --system --shell /usr/sbin/nologin \
          --home-dir "$DATA_DIR" --create-home "$AGENT_USER"
fi

info "Creating directories..."
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$CERT_DIR" "$LOG_DIR"
chown -R "$AGENT_USER:$AGENT_USER" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$CERT_DIR"
chown -R "$AGENT_USER:$AGENT_USER" "$CERT_DIR"

info "Copying agent files to $INSTALL_DIR..."
if command -v rsync &>/dev/null; then
  rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"
else
  cp -a "$SCRIPT_DIR/." "$INSTALL_DIR/"
  rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/__pycache__"
  find "$INSTALL_DIR" -name '*.pyc' -delete
fi
chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"

BUNDLED_CA_SRC="$INSTALL_DIR/certs/mdm-ca.pem"
TARGET_CA="$CERT_DIR/mdm-ca.pem"
if [[ -f "$BUNDLED_CA_SRC" ]]; then
  info "Installing bundled MDM trust anchor (mdm-ca.pem)..."
  cp "$BUNDLED_CA_SRC" "$TARGET_CA"
  chown "$AGENT_USER:$AGENT_USER" "$TARGET_CA"
  chmod 644 "$TARGET_CA"
else
  warn "No certs/mdm-ca.pem in package — agent will use OS CA store for MDM/MQTT. See certs/README.md"
fi

info "Creating Python venv and installing dependencies..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"

info "Setting up config.json..."
CFG="$INSTALL_DIR/config.json"
if [[ ! -f "$CFG" ]]; then
  cp "$INSTALL_DIR/config.json.example" "$CFG"
fi

export ENROLLMENT_TOKEN
if [[ -n "${NOCKO_MDM_BASE:-}" ]]; then
  export NOCKO_DEFAULT_MDM_URL="${NOCKO_MDM_BASE}"
else
  export NOCKO_DEFAULT_MDM_URL=""
fi
export CFG DATA_DIR CERT_DIR TARGET_CA
python3 - <<'PYEOF'
import json, os, pathlib
cfg = pathlib.Path(os.environ["CFG"])
data = json.loads(cfg.read_text())
data["data_dir"] = os.environ["DATA_DIR"]
data["cert_dir"] = os.environ["CERT_DIR"]
data["db_path"] = os.environ["DATA_DIR"] + "/agent.db"
if pathlib.Path(os.environ["TARGET_CA"]).is_file():
    data["mdm_trust_ca_file"] = data.get("mdm_trust_ca_file") or "mdm-ca.pem"
token = (os.environ.get("ENROLLMENT_TOKEN") or "").strip()
if token:
    data["enrollment_token"] = token
    print("[INFO]  enrollment_token written to config.json")
base = (os.environ.get("NOCKO_DEFAULT_MDM_URL") or "").strip().rstrip("/")
if base and not (data.get("mdm_url") or "").strip():
    data["mdm_url"] = base
    print("[INFO]  mdm_url set from NOCKO_MDM_BASE")
cfg.write_text(json.dumps(data, indent=2))
PYEOF

if [[ -z "$ENROLLMENT_TOKEN" ]]; then
  warn "No enrollment token provided. Set it manually in $CFG before starting the agent."
fi
chown "$AGENT_USER:$AGENT_USER" "$CFG"
chmod 600 "$CFG"

UI_CERT="$CERT_DIR/ui.crt"
UI_KEY="$CERT_DIR/ui.key"
if [[ ! -f "$UI_CERT" ]]; then
  info "Generating self-signed TLS cert for Local UI (TZ §2.7 TLS MVP)..."
  openssl req -x509 -newkey rsa:2048 -keyout "$UI_KEY" -out "$UI_CERT" \
    -days 3650 -nodes -subj "/CN=nocko-agent-local" 2>/dev/null
  chown "$AGENT_USER:$AGENT_USER" "$UI_CERT" "$UI_KEY"
  chmod 600 "$UI_KEY"
fi

info "Granting CAP_NET_BIND_SERVICE for trap receiver..."
PYTHON_BIN="$INSTALL_DIR/.venv/bin/python3"
setcap 'cap_net_bind_service=+ep' "$PYTHON_BIN" 2>/dev/null \
  || warn "setcap failed — trap receiver may need root or authbind for UDP :162"

info "Installing systemd service..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=NOCKO Proxy Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$AGENT_USER
Group=$AGENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python3 $INSTALL_DIR/watcher.py
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/agent.log
StandardError=append:$LOG_DIR/agent.log
Environment=NOCKO_CONFIG=$CFG

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
info "Installation complete!"
echo ""
echo "  Config:   $CFG"
echo "  Logs:     $LOG_DIR/agent.log"
echo "  Local UI: https://localhost:8443 (TLS, TZ §6.2) when console_tls + certs are set"
echo ""
if [[ -z "$ENROLLMENT_TOKEN" ]]; then
  echo -e "${YELLOW}  ⚠ Set 'enrollment_token' in $CFG then start the service.${NC}"
  echo "  Start: sudo systemctl start $SERVICE_NAME"
else
  echo "  Start now: sudo systemctl start $SERVICE_NAME"
  echo "  Status:    sudo systemctl status $SERVICE_NAME"
fi
echo ""
