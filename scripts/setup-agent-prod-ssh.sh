#!/usr/bin/env bash
# One-time: copy your SSH public key to stsadmin@192.168.11.153 (password last time).
#
#   ./scripts/setup-agent-prod-ssh.sh
#   SSHPASS='...' ./scripts/setup-agent-prod-ssh.sh   # если нет sshpass — установите: brew install sshpass
#
# Env: PROD_AGENT_HOST, PROD_AGENT_USER, SSH_KEY (default ~/.ssh/id_ed25519 or id_rsa)

set -euo pipefail

HOST="${PROD_AGENT_HOST:-192.168.11.153}"
USER="${PROD_AGENT_USER:-stsadmin}"

pick_key() {
  if [[ -n "${SSH_KEY:-}" ]]; then
    echo "$SSH_KEY"
    return
  fi
  for c in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa"; do
    if [[ -f "${c}.pub" ]]; then
      echo "$c"
      return
    fi
  done
  echo ""
}

KEY="$(pick_key)"
if [[ -z "$KEY" ]]; then
  NEW="$HOME/.ssh/id_ed25519_nocko_agent"
  echo "==> создаю ключ $NEW"
  ssh-keygen -t ed25519 -f "$NEW" -N "" -C "nocko-mdm-deploy-$(hostname -s 2>/dev/null || echo dev)"
  KEY="$NEW"
fi

echo "==> ключ: $KEY.pub → $USER@$HOST"
if command -v sshpass &>/dev/null && [[ -n "${SSHPASS:-}" ]]; then
  sshpass -e ssh-copy-id -i "$KEY.pub" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$USER@$HOST"
else
  ssh-copy-id -i "$KEY.pub" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$USER@$HOST"
fi

echo "==> проверка: ssh -i $KEY $USER@$HOST 'hostname'"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$USER@$HOST" 'hostname'

echo "==> добавьте в ~/.ssh/config (по желанию):"
echo "Host nocko-agent-prod"
echo "  HostName $HOST"
echo "  User $USER"
echo "  IdentityFile $KEY"
