# ТЗ: Система Хранения Данных NOCKO MDM Portal (v3.0 Final)

## Архитектура типа Zabbix — Серверная Сторона

---

## 1. Архитектурные Принципы и Бизнес-Ограничения

- **Нет таблиц под профиль/устройство/шаблон** — только универсальные `history_*`
- **`tenant_id` обязателен** во всех таблицах (прямо или через FK)
- **`device_uid`** (строка из payload) ≠ **`devices.id`** (INT PK). Сервер делает lookup
- **`UNIQUE(tenant_id, device_uid)`** — device_uid уникален только внутри tenant
- **`online`** на устройстве и агенте — **вычисляется** из `last_seen`, не хранится
- **`health_status`** — вычисляется из `alerts WHERE active=true`, не хранится
- **`history_*`** партиционируются по времени (PostgreSQL PARTITION BY RANGE)
- **`last_values`** — кэш для UI, не аналитическая таблица. Источник истины — `history_*`
- **Уникальность `key` в рамках profile:** один и тот же key не должен встречаться в двух шаблонах одного профиля (`UNIQUE(profile_id, key)` как бизнес-ограничение)
- **`device_templates`** могут содержать только шаблоны, принадлежащие `devices.profile_id`
- **SQLite** — только для локальной разработки и unit-тестов. **PostgreSQL** — production source of truth

---

## 2. Схема Базы Данных

### 2.1. `tenants`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `name` | TEXT | |
| `created_at` | DATETIME | |

---

### 2.2. `agents`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | → tenants |
| `site_id` | INT FK | → sites |
| `name` | TEXT | |
| `version` | TEXT | SemVer агента |
| `ip` | TEXT | |
| `hostname` | TEXT | |
| `admin_status` | TEXT | `active`, `revoked`, `disabled` (административное состояние) |
| `last_seen` | INT | Unix timestamp. `online` вычисляется: `now() - last_seen < threshold` |
| `cert_fingerprint` | TEXT | |
| `created_at` | DATETIME | |

> `admin_status` — административное состояние (управляется вручную).
> `online` — runtime состояние, вычисляется из `last_seen`. Не смешивать.

**Индексы:**
```sql
INDEX(tenant_id, site_id)
INDEX(tenant_id, last_seen)
```

---

### 2.3. `profiles`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | |
| `name` | TEXT | |
| `vendor` | TEXT | |
| `version` | TEXT | Покрывает всю иерархию templates+items (MVP) |
| `description` | TEXT | |
| `schema_json` | JSON | Описание структуры ключей |
| `created_at` | DATETIME | |

**Индексы:**
```sql
UNIQUE(tenant_id, vendor, name, version)
```

---

### 2.4. `templates`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | |
| `profile_id` | INT FK | → profiles |
| `name` | TEXT | |
| `description` | TEXT | |

**Индексы:**
```sql
INDEX(tenant_id, profile_id)
```

---

### 2.5. `items`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | Для упрощения фильтрации и аудита |
| `template_id` | INT FK | → templates |
| `key` | TEXT | `cpu_usage`, `temperature_inlet` |
| `name` | TEXT | |
| `value_type` | TEXT | `uint`, `float`, `string`, `text`, `log` |
| `poll_class` | TEXT | `fast`, `slow`, `inventory`, `lld` |
| `interval_sec` | INT | Переопределяется с сервера командой |
| `store_history` | BOOL | |
| `store_trends` | BOOL | |

> **Бизнес-ограничение:** `key` должен быть уникален в рамках всего `profile_id`.
> Один и тот же key в двух шаблонах одного профиля запрещён — иначе конфликт при lookup.

**Индексы:**
```sql
UNIQUE(template_id, key)
-- Бизнес-ограничение через CHECK или приложение: UNIQUE per profile
```

---

### 2.6. `devices`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | Внутренний ключ для `history_*`, `events` |
| `device_uid` | TEXT | Строка из payload (serial/uuid/MAC) |
| `tenant_id` | INT FK | |
| `name` | TEXT | hostname |
| `profile_id` | INT FK | → profiles |
| `device_owner_agent_id` | INT FK | → agents (Ownership/Lease) |
| `ip` | TEXT | |
| `mac` | TEXT | |
| `serial` | TEXT | |
| `model` | TEXT | |
| `vendor` | TEXT | |
| `device_class` | TEXT | `server`, `switch`, `printer`... |
| `location` | TEXT | |
| `last_seen` | INT | Unix timestamp |
| `created_at` | DATETIME | |

> `online` = `now() - last_seen < threshold` (вычисляется, не хранится)
> `health_status` = из `alerts WHERE device_id=X AND active=true` (вычисляется)

**Индексы:**
```sql
UNIQUE(tenant_id, device_uid)
INDEX(tenant_id, profile_id)
INDEX(tenant_id, device_owner_agent_id)
INDEX(tenant_id, serial)
INDEX(tenant_id, mac)
INDEX(tenant_id, ip)
```

---

### 2.7. `device_templates`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | |
| `device_id` | INT FK | → devices |
| `template_id` | INT FK | → templates |
| `enabled` | BOOL | |

> Все назначаемые `template_id` обязаны принадлежать тому же `profile_id`, что и `devices.profile_id`.

**Индексы:**
```sql
UNIQUE(tenant_id, device_id, template_id)
```

---

### 2.8. `history_*` — Универсальные Таблицы Значений

> Партиционирование обязательно: `PARTITION BY RANGE (clock)` по месяцу.
> Пример: `history_uint_2024_03`, `history_uint_2024_04`

**`history_uint` / `history_float` / `history_str` / `history_text` / `history_log`**

| Поле | Тип | Описание |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | INT FK | |
| `device_id` | INT FK | → devices.id (INT, не device_uid) |
| `item_id` | INT FK | → items |
| `agent_id` | INT FK | → agents |
| `clock` | INT | Unix timestamp сбора |
| `enqueue_ts` | INT | Timestamp попадания в очередь агента |
| `value` | (тип таблицы) | |

**Маппинг payload → history:**
1. `device_uid` → `SELECT id FROM devices WHERE tenant_id=X AND device_uid=Y`
2. `key` → `SELECT id FROM items WHERE template_id IN (device_templates) AND key=Z`
3. Определить `value_type` → записать в `history_{value_type}`

**Индексы (на каждой партиции):**
```sql
INDEX(tenant_id, device_id, item_id, clock)
INDEX(tenant_id, item_id, clock)
INDEX(agent_id, clock)
```

---

### 2.9. `last_values`

| Поле | Тип | Описание |
|---|---|---|
| `device_id` | INT FK | Composite PK |
| `item_id` | INT FK | Composite PK |
| `tenant_id` | INT FK | |
| `agent_id` | INT FK | Опционально |
| `value` | TEXT | Кэш (строка любого типа) |
| `clock` | INT | |

> **Назначение:** только кэш для UI. Не использовать для аналитики.
> Источник истины для типов и числовой аналитики — `history_*` + `items.value_type`.

**Индексы:**
```sql
PRIMARY KEY (device_id, item_id)
```

---

### 2.10. `trends_*`

**`trends_uint` / `trends_float`**

| Поле | Тип | Описание |
|---|---|---|
| `tenant_id` | INT FK | |
| `device_id` | INT FK | |
| `item_id` | INT FK | |
| `hour` | INT | Unix timestamp начала часа |
| `min` | value | |
| `max` | value | |
| `avg` | value | |
| `count` | INT | |

**Индексы:**
```sql
UNIQUE(tenant_id, device_id, item_id, hour)
```

---

### 2.11. `inventory`

> **Хранит только актуальный снимок.** Одна строка на устройство (upsert).
> Для истории изменений — отдельная таблица `inventory_history` (опционально, за рамками MVP).

| Поле | Тип | Описание |
|---|---|---|
| `device_id` | INT FK PK | |
| `tenant_id` | INT FK | |
| `last_agent_id` | INT FK | → agents |
| `vendor` | TEXT | Индексируемое поле |
| `model` | TEXT | |
| `serial` | TEXT | |
| `cpu_model` | TEXT | |
| `ram_gb` | INT | |
| `disk_count` | INT | |
| `firmware_version` | TEXT | |
| `data_json` | JSON | Полный raw payload |
| `updated_at` | DATETIME | |

---

### 2.12. `events`

| Поле | Тип | Описание |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `tenant_id` | INT FK | |
| `device_id` | INT FK | |
| `item_id` | INT FK | (опционально, NULL allowed) |
| `agent_id` | INT FK | |
| `event_type` | TEXT | `trap`, `derived`, `threshold`, `agent`, `system` |
| `source` | TEXT | OID / agent / system |
| `severity` | TEXT | `info`, `warning`, `critical` |
| `code` | TEXT | (опционально) |
| `message` | TEXT | |
| `dedup_key` | TEXT | Для идемпотентности при replay |
| `clock` | INT | |

> `dedup_key` = hash(device_id + event_type + source + code + clock_bucket)
> При replay агент может прислать событие повторно — дубли отсекаются по `dedup_key`.

**Индексы:**
```sql
UNIQUE(tenant_id, dedup_key)
INDEX(tenant_id, device_id, clock)
INDEX(tenant_id, severity, clock)
INDEX(tenant_id, event_type, clock)
```

---

### 2.13. `alerts`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | |
| `device_id` | INT FK | |
| `item_id` | INT FK | **NULL allowed** (system/agent alerts без item) |
| `severity` | TEXT | |
| `active` | BOOL | `true` = открытый |
| `opened_at` | INT | |
| `closed_at` | INT | NULL пока открытый |

> `devices.health_status` = max severity из `alerts WHERE device_id=X AND active=true`
> `active_alerts` count = `COUNT(*) WHERE device_id=X AND active=true`

**Индексы:**
```sql
INDEX(tenant_id, device_id, active)
INDEX(tenant_id, active, severity)
```

---

### 2.14. `audit_log`

| Поле | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `tenant_id` | INT FK | |
| `action` | TEXT | `add_device`, `load_template`, `change_config`... |
| `actor` | TEXT | user / agent_id |
| `entity_type` | TEXT | `device`, `profile`, `template`... |
| `entity_id` | TEXT | |
| `details` | JSON | |
| `created_at` | DATETIME | |

---

### 2.15. `commands` и `command_results`

**`commands`**

| Поле | Тип |
|---|---|
| `id` | INT PK |
| `tenant_id` | INT FK |
| `agent_id` | INT FK |
| `command_id` | TEXT UNIQUE | **UUID v4** (генерируется порталом) |
| `command_type` | TEXT |
| `issued_at` | INT |
| `issued_by` | TEXT |
| `payload` | JSON |
| `status` | TEXT |

**`command_results`**

| Поле | Тип |
|---|---|
| `id` | INT PK |
| `command_id` | TEXT FK |
| `tenant_id` | INT FK |
| `agent_id` | INT FK |
| `status` | TEXT |
| `result` | TEXT |
| `error_message` | TEXT |
| `finished_at` | INT |

**Индексы:**
```sql
UNIQUE(command_id)               -- commands
INDEX(tenant_id, agent_id, issued_at)
INDEX(command_id)                -- command_results
INDEX(agent_id, finished_at)
```

---

## 3. FK Цепочка (Финальная)

```
tenants
  └── agents          (tenant_id)
  └── profiles        (tenant_id)
        └── templates (tenant_id, profile_id)
              └── items (tenant_id, template_id)
                         UNIQUE(template_id, key)
                         Бизнес-правило: key уникален в рамках profile
  └── devices         (tenant_id, profile_id, device_owner_agent_id)
        UNIQUE(tenant_id, device_uid)
        └── device_templates (tenant_id, device_id, template_id)
                              templates ∈ devices.profile_id
        └── inventory        (device_id, tenant_id, last_agent_id)
        └── last_values      (device_id, item_id, tenant_id)
        └── alerts           (device_id, item_id nullable, tenant_id)
        └── history_*        (device_id, item_id, agent_id, tenant_id) [partitioned]
        └── trends_*         (device_id, item_id, tenant_id)
        └── events           (device_id, item_id nullable, agent_id, tenant_id, dedup_key)
```

---

## 4. Логика Приёма Данных

```sql
-- Шаг 1: Resolve device_uid → id
SELECT id FROM devices WHERE tenant_id = :tid AND device_uid = :uid;

-- Шаг 2: Resolve key → item (только включённые шаблоны)
SELECT i.id, i.value_type
FROM items i
JOIN device_templates dt ON dt.template_id = i.template_id
WHERE dt.device_id = :device_id
  AND dt.enabled = true
  AND dt.tenant_id = :tid
  AND i.key = :key;
-- Если 0 результатов → ключ игнорируется + warning лог
-- Если >1 результатов → ошибка конфигурации, ключ игнорируется + error лог
-- Рекомендуется: кэшировать lookup (device_id, key) → item_id в памяти агента/сервера
--   с инвалидацией при reload_config или изменении device_templates

-- Шаг 3: Insert into history_{value_type} partition
INSERT INTO history_float (tenant_id, device_id, item_id, agent_id, clock, enqueue_ts, value)
VALUES (...);

-- Шаг 4: Upsert last_values
INSERT INTO last_values (...) ON CONFLICT (device_id, item_id) DO UPDATE SET value=..., clock=...;

-- Шаг 5: Update devices.last_seen
UPDATE devices SET last_seen = :clock WHERE id = :device_id;
```

---

## 5. Масштаб

| Параметр | Значение |
|---|---|
| Устройств | 10 000+ |
| Агентов | 1 000+ |
| Профилей | 100+ |
| Items | 1 000+ |
| Записей/день | Миллионы |
| History хранение | Партиционировано по месяцу |
| БД dev | SQLite (unit-тесты, локальная разработка) |
| БД production | **PostgreSQL** (эталонная схема, партиционирование, JSONB) |

---

## 6. Правила Целостности (Контрактный Раздел)

> Этот раздел — обязательное чтение перед началом реализации.
> Классифицирован по приоритету: **Критично → Важно → Рекомендуется**.

---

### 🔴 КРИТИЧЕСКИЕ ОГРАНИЧЕНИЯ
*(Нарушение приводит к ошибкам данных или безопасности)*

**K-1. Уникальность device_uid — только внутри tenant**
```
UNIQUE(tenant_id, device_uid)
```
Один и тот же serial/MAC может существовать у разных tenant. Глобальный UNIQUE запрещён.

**K-2. Ключ item уникален в рамках profile, не только template**
Если устройству назначено несколько template одного profile, и два template содержат одинаковый `key` — при lookup будет конфликт. Правило: `key` уникален внутри всего `profile_id`.

> **MVP enforcement — на уровне приложения:** при сохранении нового item приложение делает `SELECT` по `(profile_id, key)` и отклоняет дубликат с ошибкой. DB constraint через `UNIQUE(profile_id, key)` требует `profile_id` в `items` напрямую — для MVP это необязательно, можно вывести через `template → profile`. Для PostMVP рекомендуется добавить `profile_id` в `items` и поставить DB constraint.

**K-3. device_templates содержит только template своего profile**
```
device_templates.template_id → templates.profile_id == devices.profile_id
```
Нельзя назначить устройству шаблон чужого профиля. Проверяется на уровне API до INSERT.

**K-4. alerts.item_id — nullable**
Алерты типа `agent_offline`, `unsupported_device`, `config_error` не привязаны к item. `item_id = NULL` допустимо и нормально.

**K-5. events — идемпотентность через dedup_key**
```
dedup_key = hash(device_id + event_type + source + code + clock_bucket)
UNIQUE(tenant_id, dedup_key)
```
При reconnect и replay агент может прислать то же событие повторно. Дубли отсекаются на INSERT (`ON CONFLICT DO NOTHING`).

**K-5b. Жизненный цикл alerts (lifecycle)**
- Alert **открывается**: при поступлении event с `severity >= warning` и отсутствии активного alert для `(device_id, item_id, source)`
- Alert **остаётся открытым**: пока устройство не вернулось в норму
- Alert **закрывается**: при поступлении `recovery event` от агента (`severity = ok`) или вручную оператором
- Закрытие: `UPDATE alerts SET active=false, closed_at=:now WHERE device_id=X AND item_id=Y AND active=true`
- **Никогда не удалять alert**: история закрытых алертов сохраняется для аудита

**K-6. Разделение admin_status и online для agents**
- `admin_status` = `active` / `revoked` / `disabled` — управляется вручную, хранится в БД
- `online` — **вычисляется**: `now() - agents.last_seen < threshold`. Не хранить.

**K-7. inventory — текущий снимок, не история**
`inventory.device_id = PK` → одна строка на устройство, всегда upsert.
Если нужна история инвентаря — отдельная таблица `inventory_history` (за рамками MVP).

**K-8. PostgreSQL — production source of truth**
SQLite используется только для локальной разработки и unit-тестов. Партиционирование, JSONB-операторы, partial indexes — только PostgreSQL. Эталонные миграции ведутся под PostgreSQL.

---

### 🟡 ВАЖНЫЕ УТОЧНЕНИЯ
*(Не следовать — риск путаницы при разработке)*

**U-1. last_values — UI-кэш, не аналитика**
`last_values.value` хранится как `TEXT` (любой тип). Это компромисс для скорости чтения в UI.
Для числовой аналитики, трендов и агрегаций — использовать `history_*` + `items.value_type`.

**U-2. profile.version покрывает всю иерархию**
В MVP: `profile.version` считается версией всего дерева `templates + items`.
Отдельного версионирования template или item нет. Если изменился template — обновляется `profile.version`.

**U-3. history_* — BIGSERIAL PK + партиционирование**
Каждая `history_*` таблица: `id BIGSERIAL PK`, `PARTITION BY RANGE (clock)` по месяцу.
`trends_*`: `UNIQUE(tenant_id, device_id, item_id, hour)`.

**U-4. online и health_status никогда не хранятся как источник истины**
- `devices.online` = `now() - devices.last_seen < X`
- `devices.health_status` = MAX severity из `alerts WHERE device_id=X AND active=true`
Хранение этих полей допустимо только как денормализованный кэш с явной пометкой "может быть устаревшим".

**U-5. Lookup key при приёме данных**
Сервер ищет `item` по `key` только среди шаблонов, назначенных устройству:
```sql
SELECT i.id, i.value_type FROM items i
JOIN device_templates dt ON dt.template_id = i.template_id
WHERE dt.device_id = :device_id AND dt.enabled = true AND i.key = :key
```
Если найдено 0 или >1 записей — payload для этого ключа игнорируется с логированием.

---

### 🟢 РЕКОМЕНДУЕМЫЕ УЛУЧШЕНИЯ
*(Полезно, но не блокирует MVP)*

**R-1. tenant_id в items и device_templates**
Выводится через FK-цепочку, но прямое поле упрощает индексацию и аудит.

**R-2. agent_id в inventory**
`last_agent_id` полезен для диагностики: кто последний обновил инвентарь этого устройства.

**R-3. agent_id в command_results**
Можно вывести через JOIN с `commands`, но прямое поле удобнее для аудита.

**R-4. inventory_history**
Хранение истории изменений инвентаря. Полезно для compliance и forensics. PostMVP.

Ускоряет вычисление `health_status` и `active_alerts` count.

---

## 7. Payload Contract — Формат Передачи Данных от Агента

> Единый формат для всех агентов. Должен соблюдаться всеми версиями в рамках одного MAJOR.

### 7.1. Общие правила

- Формат: JSON, UTF-8
- Время: Unix timestamp (UTC, секунды)
- Один payload = один tenant + один agent
- Все сообщения содержат `schema_version`
- Рекомендуется батч-отправка через `records[]`

### 7.2. Envelope (обёртка)

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

| Поле | Описание |
|---|---|
| `schema_version` | Версия схемы payload |
| `tenant_id` | Tenant агента |
| `agent_id` | Идентификатор агента |
| `sent_at` | Unix timestamp отправки пакета |
| `payload_type` | `metrics` / `inventory` / `events` / `heartbeat` |
| `records` | Массив записей |

---

### 7.3. `payload_type = "metrics"`

```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300290,
  "enqueue_ts": 1716300292,
  "data": {
    "cpu_usage": 45.2,
    "ram_usage": 32768,
    "temperature_inlet": 23.5,
    "fan_speed_1": 4800,
    "disk_status": "online"
  }
}
```

`data.key` → `items.key`. `data.value` типизируется по `items.value_type`.

---

### 7.4. `payload_type = "inventory"`

```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300390,
  "data": {
    "vendor": "Dell",
    "model": "PowerEdge R730",
    "serial": "JXD38Y2",
    "cpu_model": "Intel Xeon E5-2680 v4",
    "ram_gb": 64,
    "disk_count": 4,
    "firmware_version": "2.15.0",
    "components": {
      "memory": [{"slot": "DIMM_A1", "size_gb": 16}],
      "disks": [{"slot": "Disk.Bay.0", "model": "TOSHIBA MG04", "size_gb": 600}]
    }
  }
}
```

> Сервер делает **upsert** в `inventory`. Не записывается в `history_*`.

---

### 7.5. `payload_type = "events"`

```json
{
  "device_uid": "JXD38Y2",
  "clock": 1716300498,
  "event_type": "trap",
  "source": "1.3.6.1.4.1.674.10892.5.3.1.1",
  "severity": "critical",
  "code": "disk_failed",
  "message": "Physical Disk 0:1:4 failed",
  "item_key": "disk_status"
}
```

`item_key` — опционально. Сервер: резолвит `device_uid` → `devices.id`, формирует `dedup_key`, вставляет в `events`, открывает/закрывает `alerts`.

---

### 7.6. `payload_type = "heartbeat"`

```json
{
  "clock": 1716300600,
  "status": "ok",
  "queue_size": 125,
  "agent_version": "1.2.3"
}
```

> Обновляет `agents.last_seen`. Не записывается в `history_*`.

---

### 7.7. Правила типизации

| `value_type` | Ожидаемый тип в JSON |
|---|---|
| `uint` | Целое число |
| `float` | Число с плавающей точкой |
| `string` | Строка ≤ 255 символов |
| `text` | Длинная строка |
| `log` | Строка лога |

При несовпадении типа → значение **не записывается** в `history_*`, создаётся лог `ingest/type_mismatch`.

---

### 7.8. Правила обработки ключей

| Ситуация | Действие |
|---|---|
| key не найден в активных шаблонах устройства | Значение игнорируется + `warning` лог |
| key найден > 1 раза (конфликт шаблонов) | Значение игнорируется + `error` лог `configuration_conflict` |
| Весь payload при наличии ошибок | **Не отклоняется целиком** — обрабатываются остальные ключи |

---

### 7.9. Рекомендуемая модель отправки

| Тип | Способ |
|---|---|
| `inventory` | Отдельный payload, раз в сутки |
| `metrics` | Батч, по расписанию (fast/slow) |
| `events` | Батч или немедленно |
| `heartbeat` | Отдельный lightweight payload, каждые 60 сек |

---

*Документ сохранён в репозитории: `docs/nocko-data-storage-tz-v3.0.md` — эталон серверной схемы хранения (Portal) для согласования с proxy-agent ТЗ и backend.*
