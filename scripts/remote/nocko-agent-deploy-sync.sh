#!/bin/bash
# Install on agent host as root (one-time):
#   sudo install -m 700 scripts/remote/nocko-agent-deploy-sync.sh /usr/local/sbin/nocko-agent-deploy-sync.sh
# sudoers (visudo):
#   stsadmin ALL=(root) NOPASSWD: /usr/local/sbin/nocko-agent-deploy-sync.sh
#
# Copies staged tree from deploy script into /opt/nocko-agent, restarts service.

set -euo pipefail
STAGING_USER="${NOCKO_STAGING_USER:-stsadmin}"
ST="/home/${STAGING_USER}/tmp-nocko-agent-rsync-deploy"

if [[ ! -d "$ST" ]]; then
  echo "nocko-agent-deploy-sync: staging not found: $ST" >&2
  exit 1
fi

cp -a "$ST"/. /opt/nocko-agent/
chown -R nocko-agent:nocko-agent /opt/nocko-agent
sudo -u nocko-agent env HOME=/var/lib/nocko-agent /opt/nocko-agent/.venv/bin/pip install -q -r /opt/nocko-agent/requirements.txt
systemctl restart nocko-agent
rm -rf "$ST"
echo "nocko-agent-deploy-sync: OK"
