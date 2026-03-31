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

### 2.6.1. Список профилей, реквизиты и статус готовности (Local UI)

См. актуальную редакцию в **`proxy-agent-tz-v5.1.md` §2.6.1** (список профилей, реквизиты vendor/version, статусы готовности, ручной Verify SNMP, превью `output_mapping`).

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

## 8. Архитектура SNMP-сбора: Polling vs Traps, Профили и Zabbix-шаблоны

> Этот раздел обязателен к прочтению перед настройкой профиля SNMP и объясняет, почему данные могут не собираться.

---

### 8.1. Два режима получения данных по SNMP

| Режим | Механизм | Агент → Устройство? | Когда использовать |
|---|---|---|---|
| **SNMP Polling** (активный) | GET / BULKWALK по расписанию | **Да** (агент опрашивает IP) | Периодические метрики, инвентарь |
| **SNMP Trap** (пассивный) | Устройство само отправляет UDP:162 на агент | Нет (устройство → агент) | Аварийные события: диск упал, перегрев, включение питания |

NOCKO Proxy Agent реализует **оба режима одновременно**:
- `collectors/snmp_poller.py` — активный polling по таймеру
- `collectors/trap_receiver.py` — пассивный listener UDP:162

---

### 8.2. Как агент выполняет SNMP Polling

Текущий poller (MVP) работает строго через **SNMP GET** по индивидуальным скалярным OID:

```
Для каждого устройства (Device.status == "active"):
  Загрузить DeviceProfile.output_mapping (JSON)
  Для каждой строки mapping с нужным poll_class:
    Выполнить SNMP GET(device.ip, row["source_oid"])
    Если OK → применить scale_multiplier → отправить по MQTT
    Если ошибка → записать в error_samples
```

**Что работает сейчас:**
- `SNMP GET` по конкретному скалярному OID (например, `1.3.6.1.2.1.1.1.0`)
- SNMPv2c (community string) и SNMPv3 (auth/priv)
- `scale_multiplier`, `valid_range`, dedup/keepalive

**Что НЕ работает в MVP (причины, почему данные не собираются):**
- `SNMP WALK` / `BULKWALK` — не реализован в polling (только в диагностическом `_snmp_walk`)
- OID с LLD-макросами `{#SNMPINDEX}` — **пропускается** (`oid_has_lld_macro` → `continue`)
- `DEPENDENT` items Zabbix — зависят от walk-мастера, у них нет прямого OID
- Многозначные OID типа `walk[1.3.6.1.4.1.674.10892.5.5.1.20.130.1.1.38, ...]` — не парсятся

---

### 8.3. Анализ Zabbix-шаблона Dell iDRAC: Почему данные не собираются

Шаблон **Dell iDRAC by SNMP** использует **двухуровневую архитектуру Zabbix**:

#### Уровень 1 — Мастер-items (SNMP_AGENT, тип `walk[]`):
```yaml
key: dell.server.fan.walk
snmp_oid: 'walk[1.3.6.1.4.1.674.10892.5.4.700.12.1.5, ...]'
```
Zabbix выполняет BULKWALK по нескольким OID сразу → получает таблицу всех вентиляторов.
**NOCKO agent: MVP не умеет делать такой walk в polling** → эти items пустые.

#### Уровень 2 — Scalar/DEPENDENT items, извлекаемые из мастера:
```yaml
key: dell.server.sensor.fan.status[{#FAN_DESCR}]
type: DEPENDENT       # ← зависит от dell.server.fan.walk
master_item: dell.server.fan.walk
preprocessing:
  - type: SNMP_WALK_VALUE
    parameters: ['1.3.6.1.4.1.674.10892.5.4.700.12.1.5.{#SNMPINDEX}', '0']
```
У таких items **нет собственного OID** — они берут данные из мастера через preprocessing.
**NOCKO agent: MVP не обрабатывает DEPENDENT items** → нет ни OID, ни данных.

#### LLD Discovery rules:
```yaml
discovery_rules:
  - key: fan.discovery
    type: DEPENDENT
    item_prototypes:
      - key: 'dell.server.sensor.fan.status[{#FAN_DESCR}]'
```
Zabbix сначала выполняет discovery walk → создаёт динамические items по прототипам.
**NOCKO agent: OID с `{#SNMPINDEX}` пропускаются (`macro_skip`)** → 0 данных.

#### Скалярные items, которые работают прямо сейчас:
Из всего Dell iDRAC шаблона только несколько items имеют прямой скалярный OID и работают в MVP:

| Zabbix key | OID | Описание |
|---|---|---|
| `dell.server.bios.version` | `get[1.3.6.1.4.1.674.10892.5.4.300.50.1.8.1.1]` | Версия BIOS |
| `dell.server.descr[sysDescr]` | `get[1.3.6.1.2.1.1.1.0]` | System description |
| `dell.server.hw.firmware[racFirmwareVersion]` | `get[1.3.6.1.4.1.674.10892.5.1.1.8.0]` | Версия iDRAC firmware |
| `dell.server.hw.model[systemModelName]` | `get[1.3.6.1.4.1.674.10892.5.1.3.12.0]` | Модель сервера |
| `dell.server.hw.serialnumber[systemServiceTag]` | `get[1.3.6.1.4.1.674.10892.5.1.3.2.0]` | Серийный номер |
| `dell.server.location[sysLocation]` | `get[1.3.6.1.2.1.1.6.0]` | Местоположение |
| `dell.server.name[sysName]` | `get[1.3.6.1.2.1.1.5.0]` | Имя устройства |
| `dell.server.sw.os[systemOSName]` | `get[1.3.6.1.4.1.674.10892.5.1.3.6.0]` | Операционная система |
| `dell.server.status[globalSystemStatus]` | `get[1.3.6.1.4.1.674.10892.5.2.1.0]` | Общий статус системы |
| `dell.server.hw.uptime[systemPowerUpTime]` | `get[1.3.6.1.4.1.674.10892.5.2.5.0]` | Uptime железа |
| `dell.server.contact[sysContact]` | `get[1.3.6.1.2.1.1.4.0]` | Контакт |
| `dell.server.objectid[sysObjectID]` | `get[1.3.6.1.2.1.1.2.0]` | System Object ID |
| `dell.server.net.uptime[snmpEngineTime]` | `get[1.3.6.1.6.3.10.2.1.3.0]` | SNMP Engine uptime |

> Эти OID импортируются при загрузке шаблона и работают без доработок агента.

---

### 8.4. Как должен быть настроен профиль (`output_mapping`) для работающего SNMP-опроса

Профиль работает если **каждая строка `output_mapping` содержит конкретный скалярный OID** (не `walk[]`, не `{#MACRO}`).

**Рабочий пример `output_mapping`** для Dell iDRAC:

```json
[
  {
    "source_oid": "1.3.6.1.2.1.1.1.0",
    "target_key": "sys_descr",
    "data_type": "string",
    "poll_class": "inventory",
    "interval_sec": 86400
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.2.1.0",
    "target_key": "dell.server.status.globalSystemStatus",
    "data_type": "uint",
    "poll_class": "fast",
    "interval_sec": 60
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.1.3.12.0",
    "target_key": "dell.server.hw.model",
    "data_type": "string",
    "poll_class": "inventory",
    "interval_sec": 86400
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.1.3.2.0",
    "target_key": "dell.server.hw.serial",
    "data_type": "string",
    "poll_class": "inventory",
    "interval_sec": 86400
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.1.1.8.0",
    "target_key": "dell.server.hw.firmware",
    "data_type": "string",
    "poll_class": "slow",
    "interval_sec": 3600
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.4.300.50.1.8.1.1",
    "target_key": "dell.server.bios.version",
    "data_type": "string",
    "poll_class": "inventory",
    "interval_sec": 86400
  },
  {
    "source_oid": "1.3.6.1.2.1.1.5.0",
    "target_key": "sys_name",
    "data_type": "string",
    "poll_class": "inventory",
    "interval_sec": 86400
  },
  {
    "source_oid": "1.3.6.1.6.3.10.2.1.3.0",
    "target_key": "dell.server.net.uptime",
    "data_type": "uint",
    "unit": "uptime",
    "poll_class": "slow",
    "interval_sec": 300
  },
  {
    "source_oid": "1.3.6.1.4.1.674.10892.5.2.5.0",
    "target_key": "dell.server.hw.uptime",
    "data_type": "uint",
    "unit": "uptime",
    "poll_class": "slow",
    "interval_sec": 300
  }
]
```

---

### 8.5. Правила настройки профиля — Чеклист

| # | Проверка | Как проверить |
|---|---|---|
| 1 | `source_oid` — только скалярный OID, без `walk[...]`, без `{#MACRO}` | Открыть `output_mapping` в UI → "Preview" |
| 2 | `poll_class` = `fast` / `slow` / `inventory` | Поллер читает именно это поле |
| 3 | `Device.status == "active"` | Страница устройства в UI |
| 4 | `Device.profile_id` ссылается на существующий реальный профиль | Проверить в Profiles → найти по `profile_id` |
| 5 | Устройство доступно по `Device.ip` и порту UDP/161 | Verify SNMP в UI → должен вернуть `OK` |
| 6 | SNMP credentials корректны (`community` для v2c, `user/auth/priv` для v3) | Verify SNMP → сообщение об ошибке auth |
| 7 | Файрвол: порт UDP/161 открыт от хоста агента к IP устройства | `snmpwalk -v2c -c public <ip> 1.3.6.1.2.1.1.1.0` с хоста агента |
| 8 | Trap receiver: устройство направляет трапы на IP агента UDP/162 | `/diagnostics` → trap_count растёт |

---

### 8.6. Диагностика: Почему SNMP не собирается (Алгоритм)

```
1. Открыть Local Web UI → /diagnostics (или /devices/{id}/snmp-debug.json)
   ├── mib2_sysDescr OK?
   │   ├── NO → проблема с сетью/сред(а/firewall/IP/community. Stop здесь.
   │   └── YES → базовый SNMP работает
   │
   ├── profile_probe_oid OK?
   │   ├── NO → OID из профиля недоступен (не та прошивка MIB, ограничение View)
   │   └── YES → OID доступен
   │
   └── /poll_diag в UI:
       ├── tier_total == 0    → в profile нет items для этого poll_class
       ├── macro_skipped > 0  → OID содержат {#MACRO} — нужны скалярные OID
       ├── snmp_failed > 0    → смотреть snmp_error_samples → конкретная ошибка
       ├── dedup_skipped > 0  → данные собираются, но не изменились (норма)
       └── values_published>0 → данные отправляются, проверяй MQTT и backend
```

**Частые ошибки:**

| Симптом | Причина | Решение |
|---|---|---|
| `macro_skip == tier_total` | Все OID в профиле — LLD-прототипы с `{#SNMPINDEX}` | Добавить скалярные OID в профиль вручную |
| `snmp_fail == tier_total` | Community/SNMPv3 creds неверны | Проверить Verify SNMP в UI |
| `tier_total == 0` | Не тот `poll_class` или профиль пустой | Убедиться что mapping имеет строки с `poll_class: fast/slow` |
| Device не опрашивается | `Device.status != "active"` | Активировать устройство в UI |
| Данные есть, на портале нет | MQTT не подключён | Проверить `/diagnostics` → mqtt_status |

---

### 8.7. SNMP Trap — Настройка на стороне устройства (Dell iDRAC)

Чтобы устройство отправляло трапы на агент, нужно настроить на iDRAC:

1. **iDRAC Web UI** → Alerts → SNMP Trap Destination:
   - IP: `<IP хоста агента>`
   - Community: любое (для trap-receiver не проверяется в MVP)
   - SNMP Version: v1 / v2c / v3 (агент принимает все)

2. Убедиться что агентский хост слушает UDP:162. Проверка:
   ```bash
   sudo ss -ulnp | grep 162
   # должна быть строка: 0.0.0.0:162 nocko-agent
   ```

3. Агент требует `CAP_NET_BIND_SERVICE` или запуск от root для UDP:162. В `install.sh` этот capability устанавливается автоматически.

4. Если трапы приходят — они видны в **Local UI → Events** и в `/diagnostics` → `trap_count`.

---

### 8.8. Требования к реализации SNMP Walk в будущих версиях (Post-MVP)

Для сбора данных из полного Dell iDRAC шаблона (температуры, вентиляторы, диски, RAID) агент должен поддерживать:

| Функция | Zabbix механизм | Агент MVP | Планируется |
|---|---|---|---|
| Скалярный GET | `get[OID]`, `SNMP_AGENT` | ✅ Работает | — |
| SNMP BULKWALK | `walk[OID1, OID2, ...]` | ❌ Нет | v5.2 |
| SNMP_WALK_VALUE | `preprocessing: SNMP_WALK_VALUE` | ❌ Нет | v5.2 |
| SNMP_WALK_TO_JSON | `preprocessing: SNMP_WALK_TO_JSON` | ❌ Нет | v5.2 |
| LLD Discovery | `discovery_rules`, `{#SNMPINDEX}` | ❌ Нет | v6.0 |
| DEPENDENT items | `master_item`, no-OID | ❌ Нет | v5.2 |
| SNMP Trap receive | `SNMP_TRAP`, `snmptrap.fallback` | ✅ Работает | — |

**Вывод для текущей версии:** профиль Dell iDRAC должен содержать только скалярные OID из раздела 8.3 таблицы. Полная поддержка walk + LLD — в roadmap v5.2.

