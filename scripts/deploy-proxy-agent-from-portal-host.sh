#!/usr/bin/env bash
# Запускать НА СЕРВЕРЕ ПОРТАЛА (например /opt/nocko-mdm) после git pull — доставляет proxy-agent/
# на хост nocko-agent по SSH, как deploy-proxy-agent-prod.sh с ноутбука.
#
# Хост агента по умолчанию: 192.168.11.153 (как в docs/deployment-runbook.md). Переопределить:
#   PROXY_AGENT_TARGET_HOST=10.0.0.5
# Отключить автодеплой (например портал в облаке без SSH до агента):
#   PROXY_AGENT_TARGET_HOST=disable
#
# Нужно один раз: SSH-ключ с портала на агент, sudo на агенте (см. docs/agent-prod-ssh-and-sudo.md).
#
set -euo pipefail

DEFAULT_AGENT_HOST="${NOCKO_DEFAULT_AGENT_HOST:-192.168.11.153}"
_raw="${PROXY_AGENT_TARGET_HOST:-$DEFAULT_AGENT_HOST}"
_lc=$(printf '%s' "$_raw" | tr '[:upper:]' '[:lower:]')
if [[ "$_lc" == "disable" || "$_lc" == "off" || "$_lc" == "no" || "$_lc" == "false" || "$_lc" == "skip" || "$_lc" == "0" ]]; then
  echo "deploy-proxy-agent-from-portal-host: автодеплой proxy-agent отключён (PROXY_AGENT_TARGET_HOST=$_raw) — пропуск."
  exit 0
fi
HOST="$_raw"
RUSER="${PROXY_AGENT_TARGET_USER:-stsadmin}"
REPO_ROOT="${PROXY_AGENT_REPO_ROOT:-/opt/nocko-mdm}"
STAGING="tmp-nocko-agent-rsync-deploy"
REMOTE_HELPER="/usr/local/sbin/nocko-agent-deploy-sync.sh"

if [[ ! -d "$REPO_ROOT/proxy-agent" ]]; then
  echo "deploy-proxy-agent-from-portal-host: нет каталога $REPO_ROOT/proxy-agent — пропуск." >&2
  exit 0
fi

SSH_OPTS=( -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 )

echo "==> [portal→agent] pack proxy-agent → tarball"
TMP_TAR="$(mktemp /tmp/nocko-pa-portal.XXXXXX.tar.gz)"
trap 'rm -f "$TMP_TAR"' EXIT
(
  cd "$REPO_ROOT"
  COPYFILE_DISABLE=1 tar czf "$TMP_TAR" \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.pytest_cache' --exclude '.venv' \
    proxy-agent
)

echo "==> [portal→agent] upload to $RUSER@$HOST"
ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" "rm -rf $STAGING && mkdir -p $STAGING"
scp "${SSH_OPTS[@]}" "$TMP_TAR" "$RUSER@$HOST:/tmp/nocko-proxy-agent-bundle.tar.gz"
ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" \
  "tar xzf /tmp/nocko-proxy-agent-bundle.tar.gz -C ~ && rm -f /tmp/nocko-proxy-agent-bundle.tar.gz && rm -rf $STAGING && mv ~/proxy-agent $STAGING"

STAGING_ABS="/home/$RUSER/$STAGING"

if ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" "test -f $REMOTE_HELPER"; then
  echo "==> [portal→agent] $REMOTE_HELPER"
  ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" "sudo env NOCKO_STAGING_USER=$RUSER $REMOTE_HELPER"
else
  echo "==> [portal→agent] sudo copy → /opt/nocko-agent + pip + restart"
  ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" \
    "sudo bash -ce 'cp -a $STAGING_ABS/. /opt/nocko-agent/ && chown -R nocko-agent:nocko-agent /opt/nocko-agent && sudo -u nocko-agent env HOME=/var/lib/nocko-agent /opt/nocko-agent/.venv/bin/pip install -q -r /opt/nocko-agent/requirements.txt && systemctl restart nocko-agent'"
  ssh "${SSH_OPTS[@]}" "$RUSER@$HOST" "rm -rf $STAGING" || true
fi

echo "==> [portal→agent] OK: https://${HOST}:8443/devices (SNMP debug после обновления страницы)"
exit 0
