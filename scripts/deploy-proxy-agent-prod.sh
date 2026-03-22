#!/usr/bin/env bash
# Deploy proxy-agent/ → 192.168.11.153:/opt/nocko-agent (tar + scp).
#
# Если на сервере установлен /usr/local/sbin/nocko-agent-deploy-sync.sh + sudoers NOPASSWD,
# пароль sudo не нужен (см. docs/agent-prod-ssh-and-sudo.md).
#
# Env: PROD_AGENT_HOST, PROD_AGENT_USER, SSHPASS, PROD_AGENT_SUDO_PASS

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${PROD_AGENT_HOST:-192.168.11.153}"
USER="${PROD_AGENT_USER:-stsadmin}"
STAGING="tmp-nocko-agent-rsync-deploy"
REMOTE_HELPER="/usr/local/sbin/nocko-agent-deploy-sync.sh"

_ssh() {
  if command -v sshpass &>/dev/null && [[ -n "${SSHPASS:-}" ]]; then
    sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$USER@$HOST" "$@"
  else
    ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$USER@$HOST" "$@"
  fi
}

_scp() {
  if command -v sshpass &>/dev/null && [[ -n "${SSHPASS:-}" ]]; then
    sshpass -e scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"
  else
    scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"
  fi
}

echo "==> pack proxy-agent → tarball"
TMP_TAR="$(mktemp -t nocko-pa.XXXXXX.tar.gz)"
trap 'rm -f "$TMP_TAR"' EXIT
(
  cd "$ROOT"
  COPYFILE_DISABLE=1 tar czf "$TMP_TAR" \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.pytest_cache' --exclude '.venv' \
    proxy-agent
)

echo "==> upload + extract on $HOST"
_ssh "rm -rf $STAGING && mkdir -p $STAGING"
_scp "$TMP_TAR" "$USER@$HOST:/tmp/nocko-proxy-agent-bundle.tar.gz"
_ssh "tar xzf /tmp/nocko-proxy-agent-bundle.tar.gz -C ~ && rm -f /tmp/nocko-proxy-agent-bundle.tar.gz && rm -rf $STAGING && mv ~/proxy-agent $STAGING"

RUSER="${PROD_AGENT_USER:-stsadmin}"
STAGING_ABS="/home/$RUSER/$STAGING"

# Note: helper is often installed as root mode 0700 — stsadmin cannot pass `test -x`,
# but `test -f` is enough to detect it (NOPASSWD sudo still runs the full path).
USE_HELPER=false
if _ssh "test -f $REMOTE_HELPER"; then
  USE_HELPER=true
fi

if [[ "$USE_HELPER" == true ]]; then
  echo "==> $REMOTE_HELPER (NOPASSWD sudo)"
  if [[ -n "${PROD_AGENT_SUDO_PASS:-}" ]]; then
    _ssh "echo $(printf %q "$PROD_AGENT_SUDO_PASS") | sudo -S env NOCKO_STAGING_USER=$RUSER $REMOTE_HELPER"
  else
    _ssh "sudo env NOCKO_STAGING_USER=$RUSER $REMOTE_HELPER"
  fi
else
  echo "==> sudo → /opt/nocko-agent + pip + restart (from $STAGING_ABS)"
  if [[ -n "${PROD_AGENT_SUDO_PASS:-}" ]]; then
    _ssh "echo $(printf %q "$PROD_AGENT_SUDO_PASS") | sudo -S bash -ce 'cp -a $STAGING_ABS/. /opt/nocko-agent/ && chown -R nocko-agent:nocko-agent /opt/nocko-agent && sudo -u nocko-agent env HOME=/var/lib/nocko-agent /opt/nocko-agent/.venv/bin/pip install -q -r /opt/nocko-agent/requirements.txt && systemctl restart nocko-agent'"
  else
    _ssh "sudo bash -ce 'cp -a $STAGING_ABS/. /opt/nocko-agent/ && chown -R nocko-agent:nocko-agent /opt/nocko-agent && sudo -u nocko-agent env HOME=/var/lib/nocko-agent /opt/nocko-agent/.venv/bin/pip install -q -r /opt/nocko-agent/requirements.txt && systemctl restart nocko-agent'"
  fi
  _ssh "rm -rf $STAGING" || true
fi

echo "==> OK: https://${HOST}:8443/"
