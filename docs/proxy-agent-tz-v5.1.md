# Техническое Задание: Разработка NOCKO Proxy Agent (v5.1)

## 1. Цель проекта
Создать локальный автономный сетевой прокси-агент корпоративного уровня для multi-tenant сред. Агент собирает данные с локального оборудования через исходящие соединения: основной транспорт — **MQTT over TLS** (данные, события, heartbeat), HTTPS(начальная регистрация и служебные операции).

**Архитектурное позиционирование:** Отказоустойчивый автономный collector с self-healing, offline buffering, reconnect и возможностью расширения до site-level failover в будущем. MVP Phase 1: сбор SNMP. Архитектура готова к подключению дополнительных коллекторов (Redfish/REST, IPMI, SSH) в будущих фазах. Отличительная черта — встроенная **Web-консоль управления** (Admin UI).

---

## 2. Архитектура Агента и Отказоустойчивость

### 2.1. Управление доступом и Безопасность SNMP
* **Предпочтение SNMPv3:** Использование криптографии (authPriv). SNMP v1/v2c только как Fallback.
* **Изоляция и Least Privilege:** Агент работает в режиме Read-Only.
* **ACL & Защита:** Агент слушает и работает только с разрешенными IP в целевых VLAN. 

### 2.2. Polling Engine и Watcher-процессы
* **Self-Healing:** Поллер обернут в независимый `Watcher-демон` для авто-рестарта при зависаниях.
* **Site-Level Resilience:** MVP — single active agent per site + optional standby. Standby агент активируется только после истечения lease активного. Active-active кластер — за рамками MVP.

### 2.3. Trap Receiver (Ресивер Алертов)
* Служба `UDP:162`.
* **Локальное Журналирование (Archive):** Защита сырых UDP трапов через запись в write-ahead лог до выгрузки на сервер.
* **Anti-Storm Policy:** Лимитирование traps/sec и адаптивное агрегирование флуда в дайджесты.

### 2.4. Template Engine & Device Profiles
* **Zabbix Converter:** Импорт внешних Zabbix Templates (XML/JSON/YAML) с пропуском UI-элементов.
* **Обязательные поля Device Profile:**
  * `profile_id` — уникальный ключ (например, `dell-idrac7-001`).
  * `profile_name` — человекочитаемое название. Задаётся администратором вручную в Web UI.
  * `profile_vendor` — вендор.
  * `profile_version` — версия профиля.
  * `output_mapping` — маппинг OID → `key` (например: OID `.1.3.6.1.4.1.674.10892.5.1.20.1.10` → ключ `temperature_inlet`). Агент собирает значение и отправляет под этим ключом. Сервер сам определяет `value_type` и пишет в `history_*`.

### 2.5. Local Queue Store & Downsampling
* Транзакционная **SQLite** с зашифрованными конфигами.
* **Downsampling Policy:** При долгой потере связи (переполнении `max_queue_size`) старые метрики не удаляются, а агрегируются (Min/Max/Avg за час), спасая историю трендов. Events сохраняются всегда.

### 2.6. Local Web Console (Админ-панель Агента)
Агент содержит встроенный Web-интерфейс (HTTPS, только внутри локальной сети), доступный администратору без CLI.

**Стек и запуск:**
* **FastAPI + Uvicorn** (Python, уже в стеке агента) — никакого отдельного Node.js / PHP / Nginx.
* Web UI запускается как часть того же `systemd`-сервиса агента:
  ```
  nocko-agent.service
    ├── Polling Engine  (asyncio)
    ├── Trap Receiver   (UDP:162)
    └── Web UI Server   (uvicorn, порт 8443, TLS)
  ```
* **TLS:** Self-signed сертификат генерируется автоматически во время `install.sh` через `openssl`. Nginx не нужен для MVP.

**Язык интерфейса (обязательно):** все тексты **Local Web Console** (страницы, кнопки, подписи полей, сообщения об ошибках, логи UI-уровня, отображаемые пользователю) — **на английском языке** (en-US). Локализация на другие языки — опционально в post-MVP; MVP и production по умолчанию только English.

**MVP (Минимальная версия UI):**
1. **Zabbix Import:** Drag&Drop загрузка `.xml`/`.yaml`. После загрузки администратор заполняет форму сохранения профиля:
   * **Название** (`profile_name`) — задаётся вручную (например, `"Dell iDRAC7+ PowerEdge"`).
   * Вендор (`profile_vendor`), версия профиля (`profile_version`).
   * `profile_id` — генерируется автоматически (slug от `profile_name`).
   * После сохранения показывается вьювер созданного `output_mapping` для проверки.
2. **Backend Config:** URL MDM-портала, Auth Token / mTLS-сертификат, `tenant_id`, `site_id`.
3. **Devices & Polling:** Список IP, SNMP-сообщества, интервалы опроса.
4. **Health Dashboard:** Аптайм, размер SQLite-очереди, статус соединения с MDM, последние ошибки.

**Post-MVP:**
* Визуальный редактор `output_mapping` и Regex-трансформаций.
* OID-тестер (аналог snmpwalk прямо в браузере).
* Role-Based Access Control (RBAC).

### 2.7. Transport: MQTT over TLS (Primary) + HTTPS (Bootstrap)

| Транспорт | Назначение |
|---|---|
| **MQTT over TLS** (`paho-mqtt`, порт 8883) | Основной: данные, события, heartbeat, команды. QoS1, reconnect, offline buffer |
| **HTTPS/httpx** | Bootstrap only: регистрация, `GET /config`, `GET /items` |

### 2.7.1. Единая Модель Аутентификации

| Этап | Механизм |
|---|---|
| **1. install** | `install.sh` разворачивает агент, вводится enrollment token (одноразовый) |
| **2. register** | `POST /api/v1/agent/register` с enrollment token. Сервер выдаёт `agent_id`, `tenant_id`, `site_id`, `broker_url`, **client certificate** |
| **3. normal ops** | MQTT over TLS с client certificate. `GET /config` тоже по client cert |
| **4. cert rotation** | Срок жизни cert = 1 год. Агент обновляет за 30 дней до истечения. При просрочке — re-enrollment |
| **5. revocation** | CRL. При TLS-отказе — alert в local log + попытка re-register |

### 2.7.2. Источник Истины для Конфигурации

* **Authoritative source:** `HTTPS GET /api/v1/agent/config` — единственный полный источник конфигурации.
* **MQTT `config` топик:** только **signal** ("конфиг изменился → сделай re-fetch через HTTPS"). Не хранит конфигурацию.
* Запрещено: хранить часть конфигурации только в MQTT без подтверждения через HTTPS.

### 2.7.3. MQTT-Топики (единый справочник)

**DATA PLANE** (агент → брокер):

| Топик | Контент | QoS |
|---|---|---|
| `nocko/{tenant_id}/{agent_id}/inventory` | Инвентарь (раз в сутки) | 1 |
| `nocko/{tenant_id}/{agent_id}/metrics.fast` | Health-метрики (1–10 мин) | 1 |
| `nocko/{tenant_id}/{agent_id}/metrics.slow` | Среднединамичные метрики (10–30 мин) | 1 |
| `nocko/{tenant_id}/{agent_id}/events` | Traps + derived (мгновенно) | 1 |
| `nocko/{tenant_id}/{agent_id}/lld` | LLD-обновление (раз в час) | 1 |
| `nocko/{tenant_id}/{agent_id}/agent_presence` | `agent_presence_heartbeat` (60 сек) | 0 |

**CONTROL PLANE** (управление):

| Топик | Назначение |
|---|---|
| `nocko/{tenant_id}/{agent_id}/config` | Signal: сервер → агент ("re-fetch config") |
| `nocko/{tenant_id}/{agent_id}/commands` | Команды от портала → агент |
| `nocko/{tenant_id}/{agent_id}/command_results` | Ответы агента на команды |

> **Терминология:**
> - `agent_presence_heartbeat` — пульс агента каждые 60 сек. Topic: `agent_presence`. QoS 0.
> - `metric_keepalive` — повторная отправка метрики без изменения значения раз в 5 мин.

### 2.8. Local Admin UI vs Remote Portal Control

> Агент за NAT. Портал **не видит** Local UI напрямую. Два отдельных контура.

| | Local Admin UI | Remote Portal Control |
|---|---|---|
| **Доступ** | Только внутри локальной сети | Только outbound MQTT/HTTPS |
| **Назначение** | Первичная настройка, отладка, загрузка профилей, проверка статуса | Управление из портала |
| **Портал** | Не может открыть | Все команды — через command channel |

**TLS Local UI:**
* MVP: self-signed cert (RSA 4096), допустимо.
* Production: поддержка замены сертификата через Web UI или файл конфига. TLS UI и transport certificates — логически разделены.

### 2.9. Remote Command Model

Агент подписан на `nocko/{tenant_id}/{agent_id}/commands`. Выполняет команду → публикует ответ.

```json
// Команда (портал → агент):
{ "command_id": "cmd-abc123", "command_type": "reload_config", "issued_at": 1716300000, "issued_by": "admin@nocko", "payload": {} }

// Ответ (агент → портал):
{ "command_id": "cmd-abc123", "status": "ok", "result": "config reloaded", "error_message": null, "finished_at": 1716300005 }
```

**Допустимые команды:** `reload_config`, `refresh_profiles`, `start_inventory_now`, `start_metrics_now`, `pause_polling`, `resume_polling`, `update_agent`, `request_diag_bundle`, `restart_agent_service`

### 2.10. Ownership / Lease Model (многоагентная среда)

* Каждое устройство закреплено за одним **active agent** (ownership хранится на MDM Backend).
* Агент периодически продлевает **lease**. Если lease истёк → устройство передаётся standby агенту.
* Только агент-владелец выполняет polling и публикует authoritative inventory/metrics.
* Traps могут приниматься несколькими агентами, но авторитетным считается агент с ownership.

### 2.11. Классификация Интервалов Опроса

| Класс | Интервал | MQTT топик | Состав |
|---|---|---|---|
| **Inventory** | 1 раз в сутки | `inventory` | Serial/Tag, модель, BIOS/FW, DIMM, диски (WWN), NIC (MAC), RAID-конфиг |
| **Metrics Fast** | 1–10 мин | `metrics.fast` | Global health, температуры, вентиляторы, PSU, Watt, статус дисков/RAID |
| **Metrics Slow** | 10–30 мин | `metrics.slow` | Нагрузка CPU, память/swap, NIC-трафик, SNMP availability |
| **Events/Traps** | Мгновенно | `events` | Отказ диска, перегрев, потеря питания, derived |
| **LLD (Discovery)** | 1 раз в час | `lld` | Обнаружение новых дисков, вент, портов |

**Оптимизации:**
* **Discard unchanged + metric_keepalive:** Метрика отправляется только если значение изменилось. Если нет — `metric_keepalive` раз в 5 мин.
* **Aggregation:** все температуры в одном JSON-пакете.
* **Интервалы через command channel:** портал меняет интервалы командой `reload_config` — агент делает re-fetch.

---

## 3. Модель Данных и Идентификация Устройств

### 3.1. Advanced Device Identity Model
Уникальный `device_id` формируется каскадом:
1. `Serial / ServiceTag / AssetTag`
2. `UUID / ChassisID / SystemID`
3. `sysObjectID + model`
4. `MAC address`
5. `IP address` (Опасный Fallback)

**Unsupported Flow:** Если `sysObjectID` не найден ни в одном профиле агента, отправляется статус `unsupported/generic SNMP device` на сервер для привлечения внимания администратора.

### 3.1.1. Device Header (Обязательные поля для списка устройств)

Каждый payload (любого типа: inventory, metrics, events) **всегда** содержит обязательный блок **Device Header** — независимо от профиля. Эти поля формируют строку в списке устройств для любого типа железа на портале.

| Поле | Соответствует колонке | Описание |
|---|---|---|
| `device_id` | — | Уникальный fingerprint |
| `name` | **Name** | hostname / sysName устройства |
| `serial` | **Serial Number** | Серийный номер / ServiceTag |
| `mac` | **MAC Address** | Первичный MAC устройства |
| `device_class` | **Class** | `server`, `switch`, `firewall`, `printer` и т.д. |
| `vendor` | **Vendor** | `Dell`, `HP`, `Cisco` и т.д. |
| `model` | **Model** | Например: `PowerEdge R730` |
| `ip` | **IP Address** | IP-адрес устройства |
| `health_status` | **Health** | `ok`, `warning`, `critical`, `unknown` |
| `active_alerts` | **Alerts** | Число активных алертов |
| `last_seen` | **Last Seen** | Unix timestamp последнего успешного опроса |
| `online` | **Status** | `true` (online) / `false` (offline) |

```json
{
  "device_id": "JXD38Y2",
  "name": "srv-kz-prod-01",
  "serial": "JXD38Y2",
  "mac": "A4:BF:01:12:34:56",
  "device_class": "server",
  "vendor": "Dell",
  "model": "PowerEdge R730",
  "ip": "192.168.11.153",
  "health_status": "warning",
  "active_alerts": 2,
  "last_seen": 1716301200,
  "online": true
}
```

> **Двухуровневая модель:**
> - **Device Header** — отправляется всегда с каждым пакетом. Портал использует эти поля для обновления списка устройств.
> - **Данные профиля** — зависят от шаблона устройства. Портал использует их для отрисовки страницы каждого устройства (детальная информация по температурам, дискам, памяти и т.д.).

### 3.2. Payload — Формат данных от Агента

Агент отправляет плоский `key: value` формат (архитектура как Zabbix). Сервер сам находит `item` по ключу, определяет `value_type` и записывает в `history_*` таблицу.

**Metrics (metrics.fast / metrics.slow):**
```json
{
  "event_type": "metrics",
  "schema_version": "1.0",
  "agent_id": "site-kz-01",
  "agent_version": "1.2.3",
  "profile_id": "dell-idrac7-001",
  "profile_version": "1.0.0",
  "device_id": "JXD38Y2",
  "timestamp": 1716300300,
  "data": {
    "cpu_temp": 52,
    "temperature_inlet": 23,
    "fan_speed_1": 4800,
    "power_consumption_w": 185,
    "health_status": "ok",
    "raid_status": "optimal"
  }
}
```

**Inventory (1 раз в сутки):**
```json
{
  "event_type": "inventory",
  "schema_version": "1.0",
  "agent_id": "site-kz-01",
  "device_id": "JXD38Y2",
  "timestamp": 1716300000,
  "data": {
    "cpu_model": "Intel Xeon E5-2680 v4",
    "ram_size_gb": 64,
    "serial": "JXD38Y2",
    "bios_version": "2.15.0",
    "idrac_version": "2.82.82.82",
    "disk_0_model": "TOSHIBA MG04SCA",
    "disk_0_size_gb": 600,
    "disk_0_wwn": "5000C500A1B2C3D4",
    "nic_0_mac": "A4:BF:01:12:34:56"
  }
}
```

**Events (trap / derived, мгновенно):**
```json
{
  "event_type": "event",
  "schema_version": "1.0",
  "agent_id": "site-kz-01",
  "device_id": "JXD38Y2",
  "timestamp": 1716301200,
  "event_subtype": "raw_trap",
  "severity": "critical",
  "message": "Physical Disk 0:1:4 failed",
  "oid": ".1.3.6.1.4.1.674.10892.5.3.1.1"
}
```

> Для `derived` events — `event_subtype: "derived"`, поле `oid` отсутствует.

---

## 3.3. API-контракт с MDM Backend

**Bootstrap (HTTPS / httpx)** — исходящие запросы от агента:

| Метод | URL | Назначение |
|---|---|---|
| `POST` | `/api/v1/agent/register` | Регистрация. Возвращает `agent_id`, `site_id`, `auth_token`, MQTT broker URL |
| `GET` | `/api/v1/agent/config` | Получение конфигурации (интервалы, лимиты, профили). Агент сам запрашивает |
| `GET` | `/api/v1/agent/items?profile_id=X` | Список `items` для профиля: ключи, `value_type`, интервалы. Агент знает что собирать |
| `POST` | `/api/v1/agent/unregister` | Дерегистрация при удалении |

**Данные (MQTT over TLS / paho-mqtt)** — агент публикует в топики:

| MQTT Топик | Контент | QoS |
|---|---|---|
| `nocko/{tenant_id}/{agent_id}/inventory` | Inventory батч | 1 |
| `nocko/{tenant_id}/{agent_id}/metrics.fast` | Health-метрики (1–10 мин) | 1 |
| `nocko/{tenant_id}/{agent_id}/metrics.slow` | Среднединамичные метрики (10–30 мин) | 1 |
| `nocko/{tenant_id}/{agent_id}/events` | Events (трапы и derived) | 1 |
| `nocko/{tenant_id}/{agent_id}/agent_presence` | `agent_presence_heartbeat` | 0 |

---

## 4. Корпоративные Требования (NFR)

### 4.1. Версионирование и Жизненный Цикл агента

**Схема версий (SemVer `MAJOR.MINOR.PATCH`):**

| Изменение | MAJOR | MINOR | PATCH |
|---|---|---|---|
| Несовместимые изменения в протоколе | ✔ | — | — |
| Новые модули, новые профили | — | ✔ | — |
| Багфиксы, патчи | — | — | ✔ |

**Жизненный цикл:**
```
install → register → run → [reload config] → [update] → stop → uninstall
```

**Каналы обновления:**
* **OTA (авто) —** портал публикует новую версию в MQTT-топик `nocko/{agent_id}/config`. Агент сам скачивает и применяет (PATCH / MINOR).
* **Web UI —** админ вручную запускает обновление через панель управления.
* **install.sh --update —** ручное обновление через терминал.

### 4.2. Схемы версионирования (Все версии в каждом payload)

Каждый payload обязан содержать: `schema_version`, `agent_version`, `profile_version`, `agent_id`, `timestamp`.

### 4.3. Ресурсы и Классификация Ошибок
* Предохранители: `max_workers`, `max_snmp_requests_per_second`, `max_traps_per_second`.
* Жёсткая классификация ошибок.

### 4.4. output_mapping JSON Schema

Каждый маппинг OID → key задаётся строго в JSON-формате:

```json
{
  "source_oid": ".1.3.6.1.4.1.674.10892.5.1.20.1.10",
  "source_key": "TempValue.[{#SNMPINDEX}]",
  "target_key": "temperature_inlet",
  "data_type": "float",
  "unit": "celsius",
  "scale_multiplier": 0.1,
  "valid_range": { "min": -20, "max": 120 },
  "aggregation": "last",
  "send_policy": "on_change_with_keepalive"
}
```

### 4.5. Replay Semantics / Offline Buffer TTL

| Тип данных | Политика replay |
|---|---|
| **Events** | Всегда FIFO, порядок сохраняется |
| **Inventory** | Допускается замена старого snapshot новым |
| **Metrics** | TTL = 24ч. Старые метрики — downsampling (min/max/avg). Backlog помечается `enqueue_timestamp` |

Каждый replay-пакет содержит original `timestamp` и `enqueue_timestamp` (когда пакет попал в очередь).

### 4.6. Local вс. Server-Managed Конфигурация

**LOCAL ONLY** (не передаётся с сервера):
`UI listen address`, `UI cert paths`, `local admin credentials`, `emergency recovery`, `local filesystem paths`, `broker bootstrap trust anchor`

**SERVER-MANAGED** (управляется из портала):
`device assignments`, `polling intervals`, `runtime limits`, `enabled profiles`, `topic policy`, `command policy`, `lease policy`, `backpressure policy`

---

## 5. Развертывание: One-Command Deploy

### 5.1. Требование (Идемпотентность)
Агент должен разворачиваться на **любом чистом или существующем** сервере Ubuntu 22.04/24.04 одной командой:

```bash
curl -sSL https://nocko-mdm.io/install.sh | sudo bash
```

### 5.2. Этапы Bootstrap-скрипта

**Шаг 1: Проверка системных требований (Pre-flight Check)**
**Шаг 2: Установка системных зависимостей**
**Шаг 3: Создание директорий и пользователя**
**Шаг 4: Применение конфигурации по умолчанию**
**Шаг 5: Настройка сетевых разрешений (Trap Receiver)**
**Шаг 6: Регистрация и запуск службы (systemd)**
**Шаг 7: Финальный отчет**

### 5.3. Обновление (Update)
Повторный запуск `install.sh --update` скачивает новый бинарник, проверяет ЭЦП и перезапускает. При ошибке - rollback.

### 5.4. Удаление (Uninstall)
Запуск `install.sh --uninstall` останавливает службу, отправляет unregister запрос на сервер, удаляет директории и сохраняет `/var/lib/nocko-agent/` (SQLite очередь) для backup.

---

## 6. Технические Решения: Стек и Структура Данных

### 6.1. Язык и Среда Выполнения
**Python 3.11** — единственный выбор для агента (нативный asyncio).

### 6.2. Web-панель
**FastAPI + Uvicorn + Jinja2 + AlpineJS**. Сервер UI запускается внутри одного `nocko-agent` процесса (port 8443 TLS).

### 6.3. SNMP-библиотека
Нативные асинхронные `puresnmp` / `asyncpuresnmp` без Net-SNMP.

### 6.4. HTTP-транспорт
`httpx` (mTLS с MDM-сервером, retry-логика).

### 6.5. ORM и Локальное Хранилище
`SQLModel` + SQLite (`/var/lib/nocko-agent/agent.db`).

### 6.6. Форма Импорта Профиля и UX
При загрузке Zabbix шаблона данные извлекаются автоматически (vendor, name) с возможностью редктирования.

### 6.7. Конвертер Zabbix (Правила Извлечения)
Извлекаются `items`, `discovery_rules`, `preprocessing`; Игнорируются графики, мапы, триггеры.

---

## 7. Payload Contract — Формат Отправляемых Данных

### 7.1. Общие правила
- Формат: JSON, UTF-8. Время: Unix timestamp. Batches (`records[]`).

### 7.2. Envelope (обёртка всех типов)
```json
{
  "schema_version": "1.0",
  "tenant_id": 101,
  "agent_id": 5001,
  "sent_at": 1716300300,
  "payload_type": "metrics",
  "records": [...]
}
```

### 7.3. Метрики (`payload_type = "metrics"`)
```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300290,
  "enqueue_ts": 1716300292,
  "data": { "cpu_usage": 45.2, "ram_usage": 32768, "temperature_inlet": 23.5 }
}
```

### 7.4. Инвентарь (`payload_type = "inventory"`)
```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300390,
  "data": { "vendor": "Dell", "model": "PowerEdge R730", "serial": "JXD38Y2" }
}
```

### 7.5. События (`payload_type = "events"`)
```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300498,
  "event_type": "trap",
  "severity": "critical",
  "message": "Physical Disk 0:1:4 failed"
}
```

### 7.6. Heartbeat (`payload_type = "heartbeat"`)
```json
{
  "clock": 1716300600,
  "status": "ok",
  "queue_size": 125,
  "agent_version": "1.2.3"
}
```

---

*Документ сохранён в репозитории как каноническая версия ТЗ v5.1 для согласования с кодом `proxy-agent/`.*
