# Операционные уроки — чтобы не повторять ошибки

Краткий справочник по решениям, которые уже выяснялись в проекте. Дополняй при новых инцидентах.

## Git и секреты

| Проблема | Решение |
|----------|---------|
| В коммит попали ключи / пароли | Каталог **`arc/`** в `.gitignore` — не коммитить. Перед `git add -A` делать `git restore arc/` или `git reset` для `arc/`. Токены в `git remote` на сервере — убрать, токен отозвать в GitHub. |
| «Забыли» запушить, прод без Agent API | После правок всегда **`git push origin main`**; на сервере `git pull` и пересборка backend. |
| Правки в `proxy-agent/` только в репо, бой со старым кодом | **Сразу после пуша** гонять **`./scripts/deploy-proxy-agent-prod.sh`** на **`192.168.11.153`** — см. [`deployment-runbook.md`](deployment-runbook.md) §«Политика: правки → сразу прод». |

## Docker / портал

| Проблема | Решение |
|----------|---------|
| `docker compose build backend` падает: нет `proxy-agent/` | Backend собирается с **`build.context: .`** (корень репо). На сервере должен быть **полный** клон, не только `backend/`. |
| Контейнер без `/api/v1/agent/*` | Обновить образ: `docker compose build backend && docker compose up -d backend` после `git pull`. |
| Агентам отдаётся внутренний `emqx:1883` | Задать **`MQTT_BROKER_URL`** или **`MQTT_TRANSPORT=websockets`** + nginx `/mqtt` — см. [`deployment-runbook.md`](deployment-runbook.md). |

## Linux proxy-agent на хосте

| Проблема | Решение |
|----------|---------|
| На хосте нет `rsync` | Деплой через **`scripts/deploy-proxy-agent-prod.sh`** (tar + scp), не rsync по SSH. |
| `sudo cp` в `~/staging` ушло в `/root/...` | Стейджинг под домашним пользователем: **`/home/<user>/tmp-nocko-agent-rsync-deploy`**, не `~` от root. |
| Helper `nocko-agent-deploy-sync.sh` с `chmod 700`, деплой не вызывает sudo NOPASSWD | Скрипт деплоя проверяет **`test -f`**, не `test -x` (у обычного пользователя нет +x на root-only 0700). |
| `curl bootstrap/install.sh` → 404 на скачивание tarball | В GitHub Release для `agent-v*` должен быть **`nocko-proxy-agent-*-linux-amd64.tar.gz`**, в манифесте — `linux-tarball` + sha256. Запустить workflow **`proxy-agent-linux.yml`** после Windows-релиза или залить файл вручную. |
| Консоль «не открывается» после ТЗ | Дефолтный порт консоли **8443**; старые установки могли быть на **8765** — поправить `listen_port` в `/opt/nocko-agent/config.json` и перезапустить сервис. |

## Порядок релизов

1. Собрать/опубликовать **Windows** (`agent-release.yml`) → тег `agent-vX.Y.Z`.
2. Запустить **Linux tarball** (`proxy-agent-linux.yml`) с той же версией **или** вручную залить `.tar.gz` и обновить манифест (`merge_linux_proxy_manifest.py`).

## Локальная консоль proxy-agent

| Проблема | Решение |
|----------|---------|
| `Import failed: name '_convert_zabbix_xml' is not defined` | В `console/app.py` импорт профилей должен вызывать **`parse_zabbix_template_bytes(content, filename)`** из `core/zabbix_import` (XML/JSON/YAML). Не оставлять устаревшие хелперы без определения. |
| Обновление профиля не срабатывает | `DeviceProfile` имеет PK **`id`**, slug в **`profile_id`** — искать через `select(...).where(DeviceProfile.profile_id == ...)`, не `session.get(DeviceProfile, profile_id)`. |
| После импорта YAML «ничего не происходит» | Zabbix YAML часто даёт **`templates:` как один объект**, не список — парсер нормализует в список. SNMP может быть только в **`discovery_rules[].item_prototypes[]`** — тоже парсится. После успеха редирект на **`/profiles?import_ok=1&...`**; **0 mappings** → страница ошибки. При обновлении существующего профиля — **`session.add(existing)`**. |
| Статус «профиль готов к данным» | Список и карточка: **`/profiles`**, **`/profiles/{id}`** — реквизиты TZ (`vendor`, `version`), счётчики items/devices, **Verify SNMP** (результат в KV `profile_verify:*`). См. **TZ §2.6.1**. |

## Поведение ИИ в Cursor

Правило **`.cursor/rules/nocko-autonomous-agent.mdc`**: не тормозить уточнениями — действовать по коду и ТЗ, новые выводы заносить сюда или в [`deployment-runbook.md`](deployment-runbook.md).
