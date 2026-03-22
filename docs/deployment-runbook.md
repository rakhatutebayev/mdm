# NOCKO MDM — deployment runbook

Operational steps for portal (Docker Compose) and Linux **proxy-agent**. Keep secrets in `.env` on the server and SSH keys — not in git or chat.

**Типовые ошибки и как их избежать:** см. **[`operations-lessons.md`](operations-lessons.md)** (обновляй при новых инцидентах).

### Политика: правки → сразу прод

Не оставлять исправления только в Git без выката на боевые системы:

| Что меняли | Сразу после `git push` |
|------------|-------------------------|
| **`proxy-agent/`** | С рабочей машины: **`./scripts/deploy-proxy-agent-prod.sh`** → хост **`192.168.11.153`**, `/opt/nocko-agent`. |
| **`backend/`**, **`frontend/`**, `docker-compose*.yml` | На сервере портала: `git pull`, `docker compose build …`, `docker compose up -d …` (или дождаться успешного [`deploy.yml`](../.github/workflows/deploy.yml)). |

Исключение — только если пользователь явно запретил деплой.

## 1. Portal (`mdm.nocko.com` or similar)

Prerequisites: Docker + Compose plugin, repo at `/opt/nocko-mdm` (or your path).

```bash
ssh root@<portal-host>
cd /opt/nocko-mdm
git pull origin main   # or deploy via CI (.github/workflows/deploy.yml)
# Edit .env: POSTGRES_PASSWORD, MDM_SERVER_URL, MQTT_* (see below)
docker compose build backend frontend
docker compose up -d --remove-orphans backend frontend postgres
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:3002/ >/dev/null && echo frontend_ok
```

### Proxy Agent API on production

The backend must expose routes under `/api/v1/agent/*` (see `backend/routers/agent_router.py`). If `git pull` only updates GitHub and your working tree had unpushed agent API files, sync `backend/` from a trusted dev machine:

```bash
rsync -avz --exclude '.venv' --exclude '__pycache__' ./backend/ root@<portal-host>:/opt/nocko-mdm/backend/
```

Then `docker compose build backend && docker compose up -d backend`.

### MQTT URL for agents (LAN / internet)

Agents receive `broker_url` from `POST /api/v1/agent/register` and `GET /api/v1/agent/config`.

- Prefer **`MQTT_BROKER_URL`** in the backend environment. Examples:
  - TCP: `mqtt://mdm.example.com:1883`
  - **WSS (same TLS as HTTPS, port 443):** `wss://mdm.example.com/mqtt`  
    Nginx terminates TLS and proxies WebSocket to EMQX (see [`nginx/mdm-mqtt.conf`](nginx/mdm-mqtt.conf)).
- If **`MQTT_BROKER_URL`** is unset:
  - Set **`MQTT_TRANSPORT=websockets`** (or **`MQTT_PUBLIC_TRANSPORT=websockets`**) and optionally **`MQTT_PATH=/mqtt`** — the API will return `wss://<MDM_SERVER_URL host>/mqtt` (port **443**).
  - Otherwise host comes from **`MDM_SERVER_URL`**, port from **`MQTT_PUBLIC_PORT`** (default `1883`) → `mqtt://…`.

Do **not** rely on internal Docker names like `emqx` in URLs returned to agents.

Start EMQX + nginx path `/mqtt` when using WSS (`docker-compose.mqtt.yml` + TLS vhost).

## 2. Linux proxy-agent (on-prem host)

### Production host (NOCKO)

| Role | Value |
|------|--------|
| **Боевой proxy-agent** | **`192.168.11.153`** |
| SSH (пример) | `ssh <user>@192.168.11.153` |
| Локальная веб-консоль агента | **`https://192.168.11.153:8443`** (TZ §6.2; самоподписанный `ui.crt`) |
| Конфиг после install | `/opt/nocko-agent/config.json` |
| Сервис | `sudo systemctl restart nocko-agent` |

**Правки коду агента для боя** вносят на этой машине (или доставляют сюда с рабочей станции), затем перезапуск сервиса. Пример обновления только файлов из репозитория:

```bash
# с машины разработчика, из корня репозитория NOCKO MDM:
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  ./proxy-agent/core/ <user>@192.168.11.153:/tmp/nocko-agent-core/
ssh <user>@192.168.11.153 'sudo cp -a /tmp/nocko-agent-core/. /opt/nocko-agent/core/ && sudo chown -R nocko-agent:nocko-agent /opt/nocko-agent/core && sudo systemctl restart nocko-agent'
```

Полная переустановка — как в блоке ниже (`install.sh`).

**Быстрый деплой кода из репозитория** после правок в `proxy-agent/`:

```bash
# из корня репозитория; при необходимости: export SSHPASS=… PROD_AGENT_SUDO_PASS=…
./scripts/deploy-proxy-agent-prod.sh
```

Скрипт [`scripts/deploy-proxy-agent-prod.sh`](../scripts/deploy-proxy-agent-prod.sh): архив по SSH → `/opt/nocko-agent`, `pip install -r requirements.txt`, `systemctl restart nocko-agent` (на сервере **не нужен** `rsync`).

**SSH без пароля и sudo без пароля для деплоя:** см. **[`docs/agent-prod-ssh-and-sudo.md`](agent-prod-ssh-and-sudo.md)** и [`scripts/setup-agent-prod-ssh.sh`](../scripts/setup-agent-prod-ssh.sh).

---

From a machine with the repo:

```bash
COPYFILE_DISABLE=1 tar czf proxy-agent.tgz proxy-agent
scp proxy-agent.tgz user@<agent-host>:/tmp/
```

On the agent host (root for `install.sh`):

```bash
sudo rm -rf /tmp/proxy-agent && cd /tmp && tar xzf proxy-agent.tgz
# Optional: place corporate MDM CA as proxy-agent/certs/mdm-ca.pem before packaging
cd proxy-agent
sudo bash install.sh '<enrollment_token>'
sudo systemctl enable --now nocko-agent
sudo journalctl -u nocko-agent -f
# Logs also: /var/log/nocko-agent/agent.log
```

Enrollment token: active row in `enrollment_tokens` (portal admin) or seed data.

## 3. Verification

- Portal: `/health`, UI on mapped frontend port (e.g. 3002).
- Agent: row in `agents` table; logs show registration and “Server config applied”.
- MQTT: agent log shows connection to the **public** broker host (not `localhost` unless broker is co-located on that host).

## 4. Git remote hygiene

Do not store GitHub personal access tokens in `git remote` URLs on servers. Use `https://github.com/org/repo.git` + credential helper or SSH `git@github.com:org/repo.git`, and revoke any token that was ever embedded in a URL.
