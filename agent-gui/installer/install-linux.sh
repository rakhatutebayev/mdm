#!/bin/bash
set -e

# Usage: curl -sSL https://mdm.nocko.com/api/v1/packages/install-linux.sh | \
#          sudo bash -s -- --url https://mdm.nocko.com --token enroll-XXX [--distro centos7]

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

SERVER_URL=""
TOKEN=""
CUSTOMER=""
DISTRO_OVERRIDE=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --url|--server-url) SERVER_URL="$2"; shift ;;
        --token)            TOKEN="$2"; shift ;;
        --customer)         CUSTOMER="$2"; shift ;;
        --distro)           DISTRO_OVERRIDE="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$SERVER_URL" ] || [ -z "$TOKEN" ]; then
    echo "Usage: $0 --url <url> --token <token> [--customer <id>] [--distro <slug>]"
    exit 1
fi

# ── Detect Linux family ────────────────────────────────────────────────────────
detect_distro_family() {
    if [ -n "$DISTRO_OVERRIDE" ]; then
        echo "$DISTRO_OVERRIDE"
        return
    fi

    # Read /etc/os-release (present on all modern distros)
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        ID_LOWER=$(echo "${ID:-}" | tr '[:upper:]' '[:lower:]')
        LIKE_LOWER=$(echo "${ID_LIKE:-}" | tr '[:upper:]' '[:lower:]')

        case "$ID_LOWER" in
            centos)
                # Distinguish CentOS 7 (glibc 2.17) from 8/9 — use rpm build for all
                echo "centos${VERSION_ID%%.*}"
                return ;;
            rhel|almalinux|rocky|fedora|ol)
                echo "rpm"; return ;;
            debian|ubuntu|linuxmint|pop|elementary|kali|raspbian)
                echo "deb"; return ;;
        esac

        # Check ID_LIKE for family hints
        case "$LIKE_LOWER" in
            *rhel*|*centos*|*fedora*)  echo "rpm"; return ;;
            *debian*|*ubuntu*)          echo "deb"; return ;;
        esac
    fi

    # Fallback: check package managers
    if command -v rpm >/dev/null 2>&1; then
        echo "rpm"
    elif command -v dpkg >/dev/null 2>&1; then
        echo "deb"
    else
        echo "generic"
    fi
}

DISTRO=$(detect_distro_family)
echo "Installing NOCKO MDM Agent for Linux (distro family: $DISTRO)..."

# ── Install dependencies ───────────────────────────────────────────────────────
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y -q 2>/dev/null || true
    for pkg in dmidecode lshw curl iproute2 jq; do
        apt-get install -y -q "$pkg" 2>/dev/null || true
    done
elif command -v yum >/dev/null 2>&1; then
    for pkg in dmidecode lshw curl iproute jq; do
        yum install -y -q "$pkg" 2>/dev/null || true
    done
fi

# ── Paths ──────────────────────────────────────────────────────────────────────
BIN_DIR="/opt/nocko-agent/bin"
CFG_DIR="/opt/nocko-agent/config"
LOG_DIR="/var/log/nocko-agent"

mkdir -p "$BIN_DIR" "$CFG_DIR" "$LOG_DIR"

# ── Download agent binary ──────────────────────────────────────────────────────
DOWNLOAD_URL="${SERVER_URL}/api/v1/packages/latest/linux-binary?distro=${DISTRO}"
TMP_BINARY="/tmp/nocko-agent-download"

echo "Downloading agent binary from $DOWNLOAD_URL..."
curl -fsSL --retry 3 "$DOWNLOAD_URL" > "$TMP_BINARY" || {
    echo "Failed to download agent binary."
    exit 1
}
[ -s "$TMP_BINARY" ] || { echo "Downloaded file is empty."; exit 1; }
mv "$TMP_BINARY" "$BIN_DIR/nocko-agent"
chmod +x "$BIN_DIR/nocko-agent"

# ── Fetch version and MQTT config ─────────────────────────────────────────────
AGENT_VERSION=$(curl -fsSL "${SERVER_URL}/api/v1/packages/latest/linux-version?distro=${DISTRO}" 2>/dev/null || true)
[ -z "$AGENT_VERSION" ] && AGENT_VERSION="unknown"

MQTT_CONFIG=$(curl -fsSL "${SERVER_URL}/api/v1/packages/mqtt-config" 2>/dev/null || true)
MQTT_USERNAME=$(echo "$MQTT_CONFIG" | grep -o '"mqtt_username":"[^"]*"' | cut -d'"' -f4 || true)
MQTT_PASSWORD=$(echo "$MQTT_CONFIG" | grep -o '"mqtt_password":"[^"]*"' | cut -d'"' -f4 || true)
SERVER_HOST=$(echo "$SERVER_URL" | sed 's|https://||;s|http://||;s|/.*||')

# ── Write config.json ──────────────────────────────────────────────────────────
cat > "$CFG_DIR/config.json" <<EOF
{
  "server_url": "$SERVER_URL",
  "enrollment_token": "$TOKEN",
  "customer_id": "$CUSTOMER",
  "agent_version": "$AGENT_VERSION",
  "linux_distro": "$DISTRO",
  "install_dir": "/opt/nocko-agent",
  "log_dir": "$LOG_DIR",
  "start_immediately": true,
  "mqtt_enabled": true,
  "mqtt_host": "$SERVER_HOST",
  "mqtt_port": 443,
  "mqtt_transport": "websockets",
  "mqtt_path": "/mqtt",
  "mqtt_tls": true,
  "mqtt_username": "$MQTT_USERNAME",
  "mqtt_password": "$MQTT_PASSWORD"
}
EOF

# ── Create systemd service ─────────────────────────────────────────────────────
cat > /etc/systemd/system/nocko-agent.service <<EOF
[Unit]
Description=NOCKO MDM Agent
After=network.target

[Service]
Type=simple
ExecStart=$BIN_DIR/nocko-agent run --config $CFG_DIR/config.json
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nocko-agent.service
systemctl restart nocko-agent.service

echo ""
echo "✅ NOCKO MDM Agent installed and started successfully!"
echo "   Version : $AGENT_VERSION"
echo "   Distro  : $DISTRO"
echo "   Server  : $SERVER_URL"
echo "   Token   : $TOKEN"
echo "   Service : systemctl status nocko-agent"
