# Linux installer: ТЗ и реализация

Источник: [`proxy-agent-tz-v5.1.md`](proxy-agent-tz-v5.1.md) §5.

## Канонический one-liner

```bash
curl -fsSL "https://<mdm>/api/v1/agent/bootstrap/install.sh" | sudo bash -s -- '<enrollment_token>'
```

Скрипт с MDM подставляет `NOCKO_MDM_BASE` из `Host` / `X-Forwarded-*`. Дальше:

1. `GET /api/v1/agent/linux-bundle` — `url`, `sha256`, опционально `signature_url`;
2. скачивание tarball, проверка **SHA-256** (обязательно; TZ §5.3 «ЭЦП» — целостность артефакта);
3. распаковка и полный install из `proxy-agent/install.sh`.

## Локально / без MDM

Из каталога репозитория:

```bash
sudo bash install.sh '<token>'
```

## Обновление и удаление (TZ §5.3–5.4)

```bash
sudo /opt/nocko-agent/install.sh --update
sudo /opt/nocko-agent/install.sh --uninstall
```

`--update`: бэкап `/opt/nocko-agent`, проверка sha256, замена дерева, сохранение `config.json`, `pip install`, рестарт systemd, откат при ошибке.

`--uninstall`: `systemctl stop/disable`, `POST /api/v1/agent/unregister` с Bearer из SQLite `agent_config`, удаление `/opt/nocko-agent`, `/etc/nocko-agent/certs`, логов; **`/var/lib/nocko-agent` сохраняется**.

## Backend

| Endpoint | Назначение |
|----------|------------|
| `GET /api/v1/agent/bootstrap/install.sh` | Отдаёт `install.sh` с инжектом `NOCKO_MDM_BASE` |
| `GET /api/v1/agent/linux-bundle` | JSON с метаданными tarball из `agent_releases.json` |
| `POST /api/v1/agent/unregister` | Bearer → `admin_status=revoked` |

Артефакт в манифесте: `format: linux-tarball`, `arch: amd64`.

## Сборка tarball и манифест

- Локально: `./scripts/package_linux_proxy_agent.sh <version>`
- CI: [`.github/workflows/proxy-agent-linux.yml`](../.github/workflows/proxy-agent-linux.yml) (после существующего GitHub Release `agent-v<version>`)
- Добавление в уже записанный релиз: `scripts/merge_linux_proxy_manifest.py`

## Порт локальной консоли (TZ §6.2)

Дефолт **`8443`** (`config.json.example`, `core/config.py`).

## Образ backend

`docker-compose` собирает backend с `context: .` и копирует `proxy-agent/install.sh` → `/app/agent_bootstrap/install-proxy-agent.sh`.
