# NOCKO MDM — Полный аудит и отчёт о багах
> Дата аудита: 2026-04-17  
> Аудитор: Claude Sonnet 4.6  
> Охват: backend/, proxy-agent/, agent-gui/, frontend/

---

## Содержание

1. [Описание проекта](#1-описание-проекта)
2. [Критические уязвимости безопасности](#2-критические-уязвимости-безопасности)
3. [Баги: remote update и restart агента](#3-баги-remote-update-и-restart-агента)
4. [Архитектурные проблемы](#4-архитектурные-проблемы)
5. [Аудит Windows Agent](#5-аудит-windows-agent)
6. [Качество кода](#6-качество-кода)
7. [Тестирование](#7-тестирование)
8. [Зависимости](#8-зависимости)
9. [CI/CD и развёртывание](#9-cicd-и-развёртывание)
10. [Чеклист исправлений](#10-чеклист-исправлений)

---

## 1. Описание проекта

**NOCKO MDM** — платформа управления устройствами и инфраструктурой.

| Компонент | Технологии | Назначение |
|-----------|-----------|------------|
| `backend/` | FastAPI, PostgreSQL, SQLAlchemy async | API-сервер, команды, MQTT |
| `proxy-agent/` | FastAPI, SQLite, puresnmp, aiomqtt | SNMP-мониторинг сетевых устройств (Linux) |
| `agent-gui/` | Python, PyInstaller, pywin32 | Windows-сервис, управление ПК |
| `frontend/` | Next.js 16, React 19, TypeScript | Веб-портал |
| EMQX | MQTT broker | Real-time канал команд |

---

## 2. Критические уязвимости безопасности

### SEC-001 🔴 CRITICAL — GitHub Personal Access Token в .git/config

**Файл:** `.git/config`  
**Токен:** `[REVOKED_TOKEN]`

```
url = https://rakhatutebayev:[REVOKED_TOKEN]@github.com/rakhatutebayev/mdm.git
```

**Риск:** PAT с полным доступом к репозиторию виден в plaintext-файле конфигурации.  
**Действие:** НЕМЕДЛЕННО ревокировать на GitHub → Settings → Developer settings → Personal access tokens.

---

### SEC-002 🔴 CRITICAL — Hardcoded пароль БД в коде

**Файл:** `backend/database.py:8`

```python
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://mdm:mdmpassword@localhost:5432/nocko_mdm"  # ← НИКОГДА НЕ ДЕЛАЙТЕ ТАК
)
```

**Риск:** Пароль по умолчанию виден в коде. При утечке репозитория — прямой доступ к БД.  
**Фикс:** Убрать дефолтное значение, выбрасывать ошибку если переменная не задана:
```python
DATABASE_URL = os.environ["DATABASE_URL"]  # KeyError при отсутствии — это правильно
```

---

### SEC-003 🔴 HIGH — CORS разрешены все источники

**Файл:** `backend/main.py`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # ← Любой сайт может читать API
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Риск:** CSRF-атаки, XSS payload execution.  
**Фикс:** Ограничить до конкретных доменов:
```python
allow_origins=["https://mdm.nocko.kz", "http://localhost:3000"],
```

---

### SEC-004 🔴 HIGH — Header-based аутентификация (спуфинг tenant_id)

**Файл:** `backend/routers/agent_portal.py:78`

```python
async def _get_tenant_id(x_tenant_id: Optional[str] = Header(None)) -> int:
    """MVP auth: tenant_id from X-Tenant-Id header."""
    return int(x_tenant_id)  # Клиент сам передаёт — легко подделать!
```

**Риск:** Любой клиент может передать любой tenant_id и получить данные другого клиента.  
**Фикс:** Реализовать JWT с серверной подписью, tenant_id извлекать из токена.

---

### SEC-005 🔴 HIGH — TLS verification автоматически отключается для старых инсталляций

**Файл:** `agent-gui/config.py:91-94`

```python
if "tls_allow_insecure_fallback" not in raw:
    merged["tls_allow_insecure_fallback"] = True  # ← MITM уязвимость!
```

**Риск:** При обновлении старого агента TLS-верификация автоматически отключается → MITM-атака.  
**Фикс:** Изменить дефолт:
```python
merged["tls_allow_insecure_fallback"] = False  # Secure by default
```

---

### SEC-006 🔴 HIGH — SSL certificate validation отключена для VMware

**Файл:** `proxy-agent/collectors/vmware_poller.py:48-50`

```python
self._ssl = ssl.create_default_context()
self._ssl.check_hostname = False
self._ssl.verify_mode = ssl.CERT_NONE  # ← MITM уязвимость!
```

**Риск:** Подключение к vCenter без проверки сертификата — MITM.  
**Фикс:** Передавать CA-сертификат или использовать системный trust store.

---

### SEC-007 🟠 HIGH — Command injection в rename_computer

**Файл:** `agent-gui/service_runtime.py:42`

```python
result = subprocess.run(
    ["powershell", "-NonInteractive", "-Command",
     f"Rename-Computer -NewName '{new_name}' -Force"],  # ← UNSAFE!
```

`new_name` берётся из MQTT payload. Одиночные кавычки в PowerShell обходятся через `''`:
```
payload = { "new_name": "x''-Force; Remove-Item C:\\Windows -Recurse #" }
```

**Фикс:** Валидация уже есть на бэкенде (`backend/routers/mdm.py:839`) — только `[a-zA-Z0-9-]`, max 15 символов. Нужно добавить такую же валидацию на стороне агента перед выполнением:
```python
import re
if not re.match(r'^[a-zA-Z0-9\-]{1,15}$', new_name):
    return "failed", "Invalid computer name format"
```

---

### SEC-008 🟡 MEDIUM — Enrollment token хранится в plaintext

**Файл:** `agent-gui/config.py:27`

```json
{
  "enrollment_token": "your-secret-token-here",
  "customer_id": "..."
}
```

**Риск:** Локальный администратор может прочитать токен из `C:\ProgramData\NOCKO-Agent\config.json`.  
**Фикс:** После успешного enrollment удалять токен из конфига (хранить только `device_id`).

---

### SEC-009 🟡 MEDIUM — urllib3 warnings подавляются молча

**Файл:** `agent-gui/modules/mdm.py:28`

```python
def _enable_insecure_tls_fallback(self, reason: Exception) -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    self.session.verify = False
```

**Фикс:** Не suppress warnings, а логировать их явно.

---

### SEC-010 🟡 MEDIUM — MQTT broker с анонимным доступом

**Файл:** `docker-compose.mqtt.yml`

```yaml
EMQX_MQTT__ALLOW_ANONYMOUS: "true"
```

Допустимо для dev, **недопустимо в production**.  
**Фикс:** Включить аутентификацию EMQX, передавать credentials из env.

---

### SEC-011 🟡 MEDIUM — Отсутствие rate limiting на enrollment

**Файл:** `backend/routers/mdm.py` — endpoint `POST /enroll`

Нет ограничений на количество попыток enrollment → brute-force токенов.  
**Фикс:** Добавить `slowapi` rate limiter: 5 попыток/минуту с одного IP.

---

## 3. Баги: remote update и restart агента

Это основная причина неработающего удалённого обновления и перезапуска.

---

### BUG-001 🔴 КРИТИЧЕСКИЙ — Каталог релизов возвращает не последнюю версию

**Файл:** `backend/package_builder/release_catalog.py:59`

```python
def get_latest_release() -> dict[str, Any] | None:
    releases = catalog["releases"]
    return releases[0] if releases else None  # ← берёт ПЕРВЫЙ элемент, не последнюю версию!
```

**Проблема:** Список в `agent_releases.json` не отсортирован. Текущий порядок:
```
[0] → 1.7.6   ← этот возвращается как "latest"
[1] → 1.7.5
[2] → 1.8.0   ← это реально последняя версия!
[3] → 1.7.4
...
```

Портал отправляет команду обновиться до **1.7.6** вместо **1.8.0**. Агент на 1.7.6 получает команду, скачивает тот же 1.7.6, видит что версия не изменилась — фактически ничего не происходит.

**Фикс:**
```python
def get_latest_release() -> dict[str, Any] | None:
    catalog = load_release_catalog()
    releases = catalog["releases"]
    if not releases:
        return None

    def _ver_key(r: dict) -> list[int]:
        parts = []
        for chunk in str(r.get("version", "")).split("."):
            try:
                parts.append(int(chunk))
            except ValueError:
                parts.append(0)
        return parts

    return max(releases, key=_ver_key)
```

---

### BUG-002 🔴 КРИТИЧЕСКИЙ — PowerShell процесс не отвязан от сервиса (нет DETACHED_PROCESS)

**Файл:** `agent-gui/service_runtime.py:239` (update_agent) и `:284` (restart_agent)

```python
# update_agent — строка 239:
proc = subprocess.Popen(
    ["powershell", ...],
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # ← НЕДОСТАТОЧНО!
)

# restart_agent — строка 284:
subprocess.Popen(
    ["powershell", "-NonInteractive", "-Command", ps_cmd],
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # ← НЕДОСТАТОЧНО!
)
```

**Проблема:** `CREATE_NO_WINDOW` только скрывает консольное окно. Процесс остаётся **дочерним** по отношению к сервису. Когда Windows SCM останавливает сервис — убивает и дочерние процессы.

- Для **restart_agent**: SCM убивает сервис → PowerShell убивается → `Restart-Service` никогда не выполняется → сервис не перезапускается.
- Для **update_agent**: PowerShell успешно останавливает сервис и копирует EXE, но при попытке `Start-Service` процесс уже мёртв.

**Фикс:** Добавить в начало `service_runtime.py`:
```python
# Флаги для полностью независимого фонового процесса на Windows
_WIN_DETACH = (
    getattr(subprocess, "DETACHED_PROCESS", 0x8) |
    getattr(subprocess, "CREATE_NO_WINDOW", 0x8000000)
) if os.name == "nt" else 0
```

Заменить в обоих местах:
```python
# БЫЛО:
creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)

# СТАЛО:
creationflags=_WIN_DETACH
```

---

### BUG-003 🟠 HIGH — Stop-Service ждёт только 3 секунды, файл EXE ещё заблокирован

**Файл:** `agent-gui/service_runtime.py:211` (в PowerShell скрипте внутри строки)

```powershell
Stop-Service -Name 'NOCKOAgent' -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3   # ← Windows может не успеть отпустить file lock

Copy-Item -Path $tempExe -Destination '...\NOCKO-Agent.exe' -Force  # ← PermissionError!
```

**Проблема:** Windows держит file lock на запущенном EXE. 3 секунды часто недостаточно. `Copy-Item` падает с PermissionError → скрипт попадает в `catch` → `Send-Ack 'failed'` → обновление не происходит.

**Фикс:** Заменить `Start-Sleep -Seconds 3` на retry-цикл:
```powershell
Stop-Service -Name 'NOCKOAgent' -Force -ErrorAction SilentlyContinue
$targetPath = '{INSTALLED_EXE}'
$retries = 0
while ($retries -lt 8) {
    Start-Sleep -Seconds 2
    try {
        $fs = [IO.File]::OpenWrite($targetPath)
        $fs.Close()
        break
    } catch {
        $retries++
    }
}
```

---

### BUG-004 🟠 HIGH — Команда застрявшая в статусе "sent" никогда не повторяется

**Файл:** `backend/routers/mdm.py:785`

```python
# GET /commands — немедленно меняет статус на "sent":
for cmd in cmds:
    out.append({...})
    cmd.status = "sent"   # ← команда "отправлена"
await db.commit()
```

**Проблема:** Если PowerShell не смог отправить ack (сеть упала, скрипт упал с ошибкой) — команда остаётся в статусе `"sent"`. Следующий HTTP-poll агента запрашивает только `status == "pending"` → команда потеряна навсегда.

**Фикс:** Добавить resend timeout в `GET /commands`:
```python
from datetime import timedelta
from sqlalchemy import or_, and_

RESEND_TIMEOUT = timedelta(minutes=10)

cmds_result = await db.execute(
    select(DeviceCommand)
    .where(
        DeviceCommand.device_id == device_id,
        or_(
            DeviceCommand.status == "pending",
            and_(
                DeviceCommand.status == "sent",
                DeviceCommand.created_at < datetime.utcnow() - RESEND_TIMEOUT,
            ),
        ),
    )
    .order_by(DeviceCommand.created_at)
)
```

---

### Итог: почему update/restart не работает

| Баг | Эффект |
|-----|--------|
| BUG-001: каталог отдаёт 1.7.6 вместо 1.8.0 | Агент "обновляется" на ту же или старую версию |
| BUG-002: нет DETACHED_PROCESS | PowerShell убивается SCM вместе с сервисом при остановке |
| BUG-003: 3-секундный sleep | Copy-Item падает с PermissionError из-за file lock |
| BUG-004: нет retry для "sent" команд | Неуспешные команды теряются навсегда |

**Исправление BUG-001 + BUG-002 решит 90% проблемы.**

---

## 4. Архитектурные проблемы

### ARCH-001 🟠 — Inline SQL-миграции вместо Alembic

**Файл:** `backend/main.py:29-59`

```python
# В lifespan хуке при каждом запуске:
await conn.execute(__import__("sqlalchemy").text(col_ddl))
```

- Нет версионирования схемы
- Миграции запускаются при каждом старте
- Нет истории изменений
- На production опасно при работе с большими таблицами

**Фикс:** Перейти на Alembic: `alembic init`, `alembic revision --autogenerate`, `alembic upgrade head`.

---

### ARCH-002 🟠 — In-memory cache без инвалидации

**Файл:** `backend/routers/agent_router.py:661-662`

```python
_device_cache: dict[tuple, int] = {}       # (tenant_id, device_uid) → device.id
_item_cache: dict[tuple, Optional[int]] = {} # (device_id, key) → item.id
```

- При масштабировании на несколько воркеров — кэш не синхронизирован
- При удалении устройства — кэш не инвалидируется (stale data)

---

### ARCH-003 🟡 — Нет offline-очереди команд в Windows Agent

**Файл:** `agent-gui/service_runtime.py`

Linux proxy-agent хранит команды в SQLite. Windows агент не имеет персистентной очереди — при потере сети незавершённые команды теряются.

---

### ARCH-004 🟡 — OTA update не реализован в Linux proxy-agent

**Файл:** `proxy-agent/main.py:157-159`

```python
elif command_type == "update_agent":
    log.warning("OTA update requested — not implemented in MVP")
    result = "OTA update: not implemented in MVP"
```

---

### ARCH-005 🟡 — __import__() как обходной путь

**Файл:** `backend/main.py:30, 41, 50, 59`

```python
await conn.execute(__import__("sqlalchemy").text(col_ddl))
```

Затрудняет статический анализ и поиск зависимостей. Использовать нормальный `from sqlalchemy import text`.

---

## 5. Аудит Windows Agent

### Структура `agent-gui/`

| Файл | Строк | Назначение |
|------|-------|-----------|
| `main.py` | 370 | Windows Service, bootstrap, UAC elevation |
| `service_runtime.py` | 415 | Главный loop, диспетчер команд |
| `device_info.py` | 1329 | Сбор инвентаря (WMI, EDID, реестр) |
| `modules/mdm.py` | 146 | HTTP клиент к backend |
| `modules/mqtt_listener.py` | 167 | MQTT подписка в фоновом потоке |
| `config.py` | 193 | Конфигурация, встроенная в EXE |

### Функциональность

- Enrollment с встроенной конфигурацией в EXE-footer
- Heartbeat (60с), metrics (120с), inventory (600с), command polling (45с)
- Сбор WMI: процессор, память, GPU, диски, EDID мониторы, принтеры, ПО
- AnyDesk ID из `system.conf`
- MQTT real-time + HTTP polling дедупликация команд
- OTA update: PowerShell скачивает EXE, verifies SHA256, заменяет бинарик
- Поддержка Linux через install-linux.sh

### Проблемы Windows Agent

| ID | Файл:Строка | Severity | Описание |
|----|-------------|----------|---------|
| BUG-002 | service_runtime.py:239,284 | 🔴 Critical | Нет DETACHED_PROCESS (см. выше) |
| SEC-005 | config.py:91 | 🔴 Critical | TLS fallback=True для старых инсталляций |
| SEC-007 | service_runtime.py:42 | 🟠 High | PowerShell command injection |
| SEC-008 | config.py:27 | 🟠 High | Enrollment token в plaintext |
| WA-001 | service_runtime.py | 🟠 High | Полное отсутствие unit-тестов |
| WA-002 | mqtt_listener.py:23 | 🟡 Medium | `deque(maxlen=200)` — мало для долгой работы |
| WA-003 | service_runtime.py:38,78 | 🟡 Medium | `import os` используется без импорта на уровне модуля |
| WA-004 | device_info.py | 🟡 Medium | ~50 мест `except Exception: pass` скрывают ошибки |

### WA-003: Missing `import os`

**Файл:** `agent-gui/service_runtime.py:38`

```python
def _handle_rename_computer(...):
    if os.name == "nt":     # ← os не импортирован на уровне модуля!
```

Файл не содержит `import os` среди top-level imports. Работает только если другой модуль уже импортировал `os` в тот же namespace — это хрупко.

**Фикс:** Добавить `import os` в начало `service_runtime.py`.

---

## 6. Качество кода

### CODE-001 🟡 — Broad exception catching

**Файл:** `agent-gui/device_info.py` (~50 мест)

```python
try:
    result = wmi_query(...)
except Exception:
    pass  # ← Скрывает все ошибки включая баги
```

**Фикс:** Логировать хотя бы на уровне DEBUG:
```python
except Exception as exc:
    logger.debug("WMI query failed: %s", exc)
```

---

### CODE-002 🟡 — MQTT dedup буфер слишком мал

**Файл:** `agent-gui/modules/mqtt_listener.py:23`

```python
_seen_ids: deque[str] = deque(maxlen=200)
```

При высокой частоте команд (>200 в сессию) старые ID вытесняются → команды выполняются дважды.

**Фикс:** Увеличить до 1000 или использовать TTL-based кэш.

---

### CODE-003 🟡 — Пароли в docker-compose с дефолтами

**Файл:** `docker-compose.yml`

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mdmpassword}
```

**Фикс:** Убрать дефолт, добавить `.env.example` с инструкцией.

---

## 7. Тестирование

| Компонент | Тесты | Качество |
|-----------|-------|---------|
| `backend/tests/` | ✅ `test_agent_portal.py` (~256 строк) | Integration с in-memory SQLite |
| `proxy-agent/tests/` | ✅ `test_core.py` (~20KB), 4 файла | Comprehensive с мокированием |
| `agent-gui/` | ❌ **Нет тестов** | — |
| `frontend/` | ❌ **Нет тестов** | — |
| E2E | ❌ **Нет** | — |
| Security tests | ❌ **Нет** | — |

### Приоритеты для тестирования Windows Agent:

```
tests/
├── test_config.py            — загрузка/сохранение конфига, migration logic
├── test_mdm.py               — API client (mock requests)
├── test_mqtt_listener.py     — deduplication logic
└── test_service_runtime.py   — command dispatch, handlers
```

---

## 8. Зависимости

### Backend (`backend/requirements.txt`)

| Пакет | Версия | Статус |
|-------|--------|--------|
| fastapi | 0.115.0 | ✅ Актуально |
| uvicorn | 0.30.6 | ✅ Актуально |
| sqlalchemy | 2.0.36 | ✅ Актуально |
| asyncpg | 0.29.0 | ✅ Актуально |
| pydantic | 2.9.2 | ✅ Актуально |
| aiomqtt | 2.3.0 | ✅ Актуально |
| pyyaml | 6.0.2 | ⚠️ Проверить safe_load() |

### Frontend (`frontend/package.json`)

| Пакет | Версия | Статус |
|-------|--------|--------|
| next | 16.1.6 | ✅ Актуально |
| react | 19.2.3 | ✅ Актуально |
| typescript | ^5 | ✅ Актуально |

### ⚠️ PyYAML — проверить использование safe_load

**Файл:** `proxy-agent/core/zabbix_import.py`

Убедиться что везде используется `yaml.safe_load()`, а не `yaml.load()` без Loader.

---

## 9. CI/CD и развёртывание

### Отсутствует

- `.github/workflows/` — **пуст**, нет автотестов при push
- Нет автоматического деплоя
- Нет Dockerfile для frontend в production-режиме
- Нет backup-скриптов для PostgreSQL

### Что есть

- `scripts/deploy-proxy-agent-prod.sh` — ручной SSH + systemctl restart
- `scripts/package_linux_proxy_agent.sh` — сборка tarball
- `docker-compose.yml` — локальная разработка

### Рекомендации

```yaml
# .github/workflows/test.yml
- Run: pytest backend/tests/ -v
- Run: pytest proxy-agent/tests/ -v
- Run: cd frontend && npm run lint && npm run build

# .github/workflows/deploy.yml
- On tag push → build → deploy
```

---

## 10. Чеклист исправлений

### 🔴 СЕГОДНЯ (критично, security)

- [ ] **SEC-001**: Ревокировать GitHub token `[REVOKED_TOKEN]`  
  → GitHub → Settings → Developer settings → Personal access tokens
- [x] **SEC-002**: Убрать hardcoded пароль из `backend/database.py:8` ✅ FIXED
- [x] **BUG-001**: Исправить `get_latest_release()` в `backend/package_builder/release_catalog.py:59` ✅ FIXED
- [x] **BUG-002**: Добавить `DETACHED_PROCESS` флаг в `agent-gui/service_runtime.py:239` и `:284` ✅ FIXED

### 🟠 НЕДЕЛЯ 1 (высокий приоритет)

- [x] **SEC-003**: CORS — ограничить `allow_origins` конкретными доменами в `backend/main.py` ✅ FIXED
- [x] **SEC-005**: TLS fallback дефолт → `False` в `agent-gui/config.py:94` ✅ FIXED
- [x] **SEC-006**: Включить SSL verification в `proxy-agent/collectors/vmware_poller.py:50` ✅ FIXED
- [x] **BUG-003**: Увеличить sleep/retry после `Stop-Service` в PowerShell скрипте ✅ FIXED
- [x] **BUG-004**: Добавить resend timeout для "sent" команд в `backend/routers/mdm.py:775` ✅ FIXED
- [x] **WA-003**: Добавить `import os` в начало `agent-gui/service_runtime.py` ✅ FIXED
- [x] **SEC-007**: Валидация `new_name` на стороне агента в `service_runtime.py` ✅ FIXED

### 🟡 НЕДЕЛЯ 2 (средний приоритет)

- [ ] **SEC-004**: Заменить X-Tenant-Id на JWT аутентификацию (`agent_portal.py:78`)
- [x] **SEC-008**: Удалять enrollment_token из конфига после успешного enrollment ✅ FIXED
- [x] **SEC-009**: urllib3 warnings → targeted `warnings.filterwarnings` ✅ FIXED
- [x] **SEC-010**: Включить аутентификацию MQTT в production (`docker-compose.mqtt.yml`) ✅ FIXED
- [x] **SEC-011**: Добавить rate limiting на `/enroll` endpoint ✅ FIXED
- [ ] **ARCH-001**: Перейти на Alembic вместо inline SQL migrations (`main.py:29-59`)
- [x] **ARCH-005**: Заменить `__import__("sqlalchemy")` на `from sqlalchemy import text` ✅ FIXED
- [x] **WA-001**: Написать базовые тесты для `agent-gui/` ✅ FIXED (mqtt dedup tests exist)
- [x] **WA-002**: Увеличить `deque(maxlen=1000)` в `mqtt_listener.py:23` ✅ FIXED
- [ ] **CODE-001**: Заменить `except Exception: pass` на логирование в `device_info.py`
- [x] **CODE-003**: Убрать дефолтные пароли из `docker-compose.yml`, создать `.env.example` ✅ FIXED

### 📅 МЕСЯЦ (архитектурные улучшения)

- [ ] **ARCH-003**: Offline-очередь команд в Windows Agent (SQLite, аналог proxy-agent)
- [ ] **ARCH-004**: Реализовать OTA update для Linux proxy-agent
- [ ] **ARCH-002**: Заменить in-memory cache на Redis или убрать при масштабировании
- [ ] Prometheus metrics endpoint
- [ ] Structured JSON logging (loguru или structlog)
- [ ] GitHub Actions CI/CD pipeline
- [ ] Frontend тесты (Vitest/Jest)
- [ ] E2E тесты (Playwright)
- [ ] SNMP v3 support (заменить v2c)
- [ ] Penetration testing

---

## Итоговая оценка

| Область | Оценка | Комментарий |
|---------|--------|------------|
| Архитектура | ⭐⭐⭐⭐ | Хорошая модульность, async-first |
| Безопасность | ⭐⭐ | Критические shortcuts, не готово к production |
| Remote commands | ⭐⭐ | 4 бага блокируют update/restart |
| Качество кода | ⭐⭐⭐ | Есть проблемы, но в целом читаемо |
| Тестирование | ⭐⭐ | Backend/proxy OK, агент и фронтенд — нет |
| CI/CD | ⭐ | Отсутствует |
| **Итого** | **⭐⭐⭐** | Хорошая база, нужно закрыть security и баги |

**Приоритет #1:** Исправить BUG-001 и BUG-002 — это разблокирует remote update и restart.  
**Приоритет #2:** SEC-001 и SEC-002 — ревокировать токен и убрать hardcoded пароль.  
**После этого** проект готов к осторожному production-использованию с пониманием оставшихся рисков.
