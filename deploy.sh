#!/usr/bin/env bash
# =============================================================================
# deploy.sh — полный деплой NOCKO MDM на чистый Ubuntu 24.04
# Запускать на СЕРВЕРЕ: bash deploy.sh
# =============================================================================
set -euo pipefail

DOMAIN="mdm.it-uae.com"
APP_DIR="/opt/nocko-mdm"
REPO_URL=""   # оставь пустым если клонируешь вручную

echo "╔══════════════════════════════════════════════════════════╗"
echo "║       NOCKO MDM — Production Deploy (Ubuntu 24.04)      ║"
echo "╚══════════════════════════════════════════════════════════╝"

# 1. Update system
echo "[1/8] Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# 2. Install Docker
echo "[2/8] Installing Docker..."
apt-get install -y -qq ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
echo "  Docker $(docker --version) ✓"

# 3. Install Nginx + Certbot
echo "[3/8] Installing Nginx + Certbot..."
apt-get install -y -qq nginx certbot python3-certbot-nginx
systemctl enable nginx

# 4. Configure Nginx (HTTP only first, HTTPS after certbot)
echo "[4/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/nocko-mdm <<'NGINX'
server {
    listen 80;
    server_name mdm.it-uae.com;

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 100M;         # for EXE uploads
        proxy_read_timeout 300s;           # for long builds
    }

    # Windows MDM (OMA-DM)
    location /EnrollmentServer/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/nocko-mdm /etc/nginx/sites-enabled/nocko-mdm
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
echo "  Nginx configured ✓"

# 5. Create app directory
echo "[5/8] Creating application directory..."
mkdir -p "$APP_DIR"
echo "  Directory: $APP_DIR ✓"

# 6. Create agent-binaries directory
mkdir -p /var/nocko/agent-binaries

# 7. Create .env file
echo "[6/8] Creating .env file..."
cat > "$APP_DIR/.env" <<ENV
# NOCKO MDM — Production Environment
APP_NAME=NOCKO MDM
APP_VERSION=1.0.0
SECRET_KEY=$(openssl rand -hex 32)

# Database
POSTGRES_USER=mdm
POSTGRES_PASSWORD=$(openssl rand -hex 16)
POSTGRES_DB=nocko_mdm
DATABASE_URL=postgresql+asyncpg://mdm:\${POSTGRES_PASSWORD}@postgres:5432/nocko_mdm

# Redis
REDIS_URL=redis://redis:6379/0

# Server
MDM_SERVER_URL=https://$DOMAIN
ENROLLMENT_URL=https://$DOMAIN/api/v1/enrollment
NEXT_PUBLIC_API_URL=https://$DOMAIN
API_URL=http://backend:8000

# Apple MDM (fill in when needed)
# APPLE_PUSH_CERT_PATH=
# APPLE_PUSH_KEY_PATH=
# APPLE_MDM_TOPIC=

# Entra ID (fill in when needed)
# ENTRA_CLIENT_ID=
# ENTRA_CLIENT_SECRET=
# ENTRA_TENANT_ID=
ENV
echo "  .env created ✓"
echo "  ⚠️  Edit $APP_DIR/.env to set final passwords!"

echo ""
echo "[7/8] Next steps:"
echo "  1. Copy project files to $APP_DIR/"
echo "     scp -r ./* root@$DOMAIN:$APP_DIR/"
echo ""
echo "  2. Start services:"
echo "     cd $APP_DIR && docker compose up -d"
echo ""
echo "  3. Enable HTTPS:"
echo "     certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m admin@$DOMAIN"
echo ""
echo "  4. Build Windows agent EXE:"
echo "     docker compose run --rm agent-builder"
echo ""
echo "Done with server preparation ✓"
echo ""
echo "Server IP: $(curl -s ifconfig.me)"
