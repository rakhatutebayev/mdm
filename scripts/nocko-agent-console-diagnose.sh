#!/usr/bin/env bash
# Запускать НА ХОСТЕ с proxy-agent (root или sudo), когда консоль не открывается с других ПК.
#   curl -fsSL ... | sudo bash   ИЛИ   sudo bash scripts/nocko-agent-console-diagnose.sh
#
set -euo pipefail

CFG="${NOCKO_CONFIG:-/opt/nocko-agent/config.json}"
INSTALL_DIR="/opt/nocko-agent"
LOG="${LOG:-/var/log/nocko-agent/agent.log}"

echo "========== NOCKO agent — диагностика веб-консоли =========="
echo "Время: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

echo "== 1) Сервис =="
systemctl is-active nocko-agent 2>/dev/null || true
systemctl status nocko-agent --no-pager -n 15 2>/dev/null || true
echo

echo "== 2) Слушает ли порт (ожидается 0.0.0.0:8443 или *:8443) =="
if command -v ss >/dev/null 2>&1; then
  ss -tlnp 2>/dev/null | grep -E ':8443|:8765' || echo "(нет слушателя на 8443/8765)"
else
  netstat -tlnp 2>/dev/null | grep -E ':8443|:8765' || echo "(ss/netstat: нет совпадений)"
fi
echo

echo "== 3) listen_host / listen_port из config.json =="
if [[ -f "$CFG" ]]; then
  python3 - <<PY
import json, pathlib
p = pathlib.Path("$CFG")
d = json.loads(p.read_text())
print("  listen_host:", repr(d.get("listen_host")))
print("  listen_port:", d.get("listen_port"))
print("  console_tls:", d.get("console_tls"))
PY
  if grep -q '"listen_host"[[:space:]]*:[[:space:]]*"127.0.0.1"' "$CFG" 2>/dev/null; then
    echo "  >>> ПРОБЛЕМА: listen_host=127.0.0.1 — с других машин консоль НЕ откроется."
    echo "      Исправьте на \"0.0.0.0\" и: sudo systemctl restart nocko-agent"
  fi
else
  echo "  Файл не найден: $CFG"
fi
echo

echo "== 4) IP-адреса этого хоста (откройте UI по одному из них) =="
hostname -I 2>/dev/null || true
ip -4 addr show scope global 2>/dev/null | sed -n 's/.*inet \([0-9.]*\).*/  \1/p' || true
echo

echo "== 5) Firewall =="
if command -v ufw >/dev/null 2>&1; then
  ufw status verbose 2>/dev/null || true
  if ufw status 2>/dev/null | grep -qi "Status: active"; then
    echo "  Если 8443 не в списке ALLOW: sudo ufw allow 8443/tcp comment 'NOCKO agent UI'"
  fi
fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state 2>/dev/null | grep -q running; then
  firewall-cmd --list-ports 2>/dev/null || true
fi
echo

echo "== 6) Последние строки лога (консоль / ошибки) =="
if [[ -r "$LOG" ]]; then
  tail -n 40 "$LOG" | grep -E "Local console|uvicorn|ERROR|Traceback|8443|Address already" || tail -n 20 "$LOG"
else
  echo "  Нет чтения: $LOG (sudo?)"
fi
echo
echo "========== Конец отчёта =========="
