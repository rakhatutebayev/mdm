#!/usr/bin/env bash
# macOS: сброс «залипшего» хостового маршрута REJECT и ARP для IP агента.
# Симптом: ping/curl к https://192.168.11.153:8443/ → Host is down / timeout,
# при этом `route -n get 192.168.11.153` показывает flags: ... REJECT ...
#
# Запуск (на Mac, с паролем sudo):
#   cd "/path/to/NOCKO MDM"
#   sudo bash scripts/fix-macos-agent-host-route.sh
#   sudo bash scripts/fix-macos-agent-host-route.sh 192.168.11.153
#
set -euo pipefail
HOST="${1:-192.168.11.153}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите с sudo, например:"
  echo "  sudo bash $0 $HOST"
  exit 1
fi

echo "==> До:"
route -n get "$HOST" 2>/dev/null || true

# Старые версии macOS: `route delete HOST`; новые: `route delete -host HOST`
route delete -host "$HOST" 2>/dev/null || route delete "$HOST" 2>/dev/null || true
arp -d "$HOST" 2>/dev/null || true

echo "==> После:"
route -n get "$HOST" 2>/dev/null || true
echo "==> Проверка (с этой же машины):"
if command -v curl >/dev/null; then
  curl -k -sS -o /dev/null -w "HTTPS / : %{http_code} (%{time_total}s)\n" --connect-timeout 8 "https://${HOST}:8443/" || true
fi
