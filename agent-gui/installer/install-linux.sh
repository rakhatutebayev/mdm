#!/bin/bash
set -e

# Usage: curl -sSL https://mdm.nocko.com/.../install-linux.sh | bash -s -- --url https://mdm.nocko.com --token ... --customer ...
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

SERVER_URL=""
TOKEN=""
CUSTOMER=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --url|--server-url) SERVER_URL="$2"; shift ;;
        --token) TOKEN="$2"; shift ;;
        --customer) CUSTOMER="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$SERVER_URL" ] || [ -z "$TOKEN" ]; then
    echo "Usage: $0 --url <url> --token <token> [--customer <customer_id>]"
    exit 1
fi

echo "Installing NOCKO MDM Agent for Linux..."

# Install dependencies if missing (best-effort, non-fatal)
if command -v apt-get >/dev/null; then
    apt-get update -y -q 2>/dev/null || true
    for pkg in dmidecode lshw curl iproute2 jq hwinfo; do
        apt-get install -y -q "$pkg" 2>/dev/null || true
    done
elif command -v yum >/dev/null; then
    for pkg in dmidecode lshw curl iproute jq; do
        yum install -y -q "$pkg" 2>/dev/null || true
    done
fi

# Download agent binary
BIN_DIR="/opt/nocko-agent/bin"
CFG_DIR="/opt/nocko-agent/config"
LOG_DIR="/var/log/nocko-agent"

mkdir -p "$BIN_DIR" "$CFG_DIR" "$LOG_DIR"

DOWNLOAD_URL="${SERVER_URL}/api/v1/packages/latest/linux-binary"

echo "Downloading agent binary from $DOWNLOAD_URL..."
curl -sSL "$DOWNLOAD_URL" -o "$BIN_DIR/nocko-agent" || { echo "Failed to download agent."; exit 1; }
chmod +x "$BIN_DIR/nocko-agent"

# Generate config.json
cat > "$CFG_DIR/config.json" <<EOF
{
  "server_url": "$SERVER_URL",
  "enrollment_token": "$TOKEN",
  "customer_id": "$CUSTOMER",
  "install_dir": "/opt/nocko-agent",
  "log_dir": "$LOG_DIR",
  "start_immediately": true
}
EOF

# Create systemd service
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

echo "NOCKO MDM Agent installed and started successfully!"
