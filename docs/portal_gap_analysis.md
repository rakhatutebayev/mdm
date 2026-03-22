# Gap Analysis: portal_backend_tz.md vs Current Portal Codebase

## 1. Что сейчас есть в портале (models.py)

Портал **сейчас** — это Windows MDM система с агентами на рабочих компьютерах.
Схема ориентирована на endpoint-устройства (PC, macOS), а не на сетевое оборудование.

| Модель | Назначение |
|---|---|
| `Customer` | = tenant (используется как `customer_id`) |
| `Device` | Windows/macOS endpoint, не сетевое устройство |
| `HardwareInventory` | Железо PC (CPU, RAM, GPU) |
| `PhysicalDisk / LogicalDisk` | Диски PC |
| `NetworkInfo` | Сеть PC |
| `MonitorInfo` | Мониторы |
| `PrinterInfo` | Принтеры |
| `DeviceMetrics` | CPU%, RAM, disk — snapshot per checkin |
| `LogicalDiskMetric` | Диски в метриках |
| `ProxyAgent` | Агент (UUID pk, auth_token, status как строка) |
| `DiscoveredAsset` | Сетевые устройства от агента (сервер, свитч...) |
| `AssetInventory` | Инвентарь DiscoveredAsset |
| `AssetComponent` | Компоненты (диски, память, NIC) |
| `AssetHealth` | Здоровье — хранится явно (не вычисляется!) |
| `AssetAlert` | Алерты (status=active/cleared, не BOOL) |
| `ProxyAgentCommand` | Команды агенту |
| `DeviceCommand` | Команды PC-устройству |
| `EnrollmentToken` | Токен регистрации |
| `SystemSettings` | Глобальные настройки key-value |

---

## 2. Соответствие TZ ↔ Кодовая база

### ✅ Уже есть (частично совпадает)

| TZ требование | Что есть в коде | Статус |
|---|---|---|
| `tenants` | `Customer` (customer_id) | ⚠️ Другое название |
| `agents` | `ProxyAgent` | ⚠️ Неполное (см. ниже) |
| `devices` | `DiscoveredAsset` | ⚠️ Другая структура |
| `inventory` | `AssetInventory` | ⚠️ Нет key/value, только фиксированные поля |
| `alerts` | `AssetAlert` | ⚠️ status=TEXT, не BOOL active |
| `commands` | `ProxyAgentCommand` | ⚠️ Нет command_id как UUID, нет command_results |
| Enrollment token | `EnrollmentToken` | ✅ Есть |

---

## 3. Критические Расхождения

### ❌ Нет универсальных `history_*` таблиц
TZ требует `history_uint`, `history_float`, `history_str`, `history_text`, `history_log`.
В коде: `DeviceMetrics` — фиксированная схема с колонками `cpu_pct`, `ram_used_gb` и т.д.
Это **не масштабируется** на SNMP-метрики с динамическими ключами.

### ❌ Нет `items`, `templates`, `profiles`
TZ требует систему профилей → шаблонов → items (ключей метрик).
В коде этого **нет вообще**. Метрики захардкожены в `DeviceMetrics`.

### ❌ Нет `last_values`
TZ требует кэш последних значений для UI.
В коде нет.

### ❌ Нет `trends_*`
TZ требует агрегации по часу (min/max/avg).
В коде нет.

### ❌ `AssetHealth.overall_status` — хранится явно
TZ: `health_status` вычисляется из `alerts WHERE active=true`.
В коде: `AssetHealth` хранит статус явно + `alert_count` INT.
**Противоречие с правилом K-7.**

### ❌ `AssetAlert.status = TEXT` вместо `active BOOL`
TZ: `alerts.active = BOOL` + `opened_at` / `closed_at`.
В коде: `AssetAlert.status = "active"/"cleared"` + `cleared_at`.
Разная модель lifecycle.

### ❌ `ProxyAgent.status = TEXT` хранится явно
TZ: `admin_status` + online вычисляется из `last_seen`.
В коде: `status = "offline"/"online"` хранится явно.
**Противоречие с правилом K-6.**

### ❌ Нет `device_uid` / `device_owner_agent_id`
TZ: `devices.device_uid TEXT UNIQUE` (external ID от агента) + `UNIQUE(tenant_id, device_uid)`.
В коде: `DiscoveredAsset.id = UUID PK`, `serial_number` есть, но без политики уникальности.

### ❌ Нет `dedup_key` в events/alerts
TZ: `events.dedup_key` для идемпотентности replay.
В коде: нет механизма дедупликации.

### ❌ Нет `command_results` (отдельная таблица)
TZ: `command_results` — отдельная таблица с `agent_id`, `tenant_id`.
В коде: `ProxyAgentCommand.result = Text nullable` — результат хранится прямо в команде.

### ❌ Нет партиционирования
TZ: `history_*` — `PARTITION BY RANGE (clock)`.
В коде: SQLite, без партиционирования.

---

## 4. Важные Уточнения

| Тема | Код | TZ |
|---|---|---|
| ID агентов | UUID строка | INT PK (TZ), но UUID тоже поддерживается |
| Tenant naming | `Customer` / `customer_id` | `Tenant` / `tenant_id` |
| Inventory структура | Фиксированные поля | Структурированные поля + `data_json` |
| MQTT transport | `mqtt_publisher.py` есть | TZ MQTT описан детально |
| Payload format | Не стандартизован | TZ Section 7 описывает строгий envelope |

---

## 5. Что нужно создать (Gap Summary)

| Таблица TZ | Что нужно сделать |
|---|---|
| `profiles` | Создать новую |
| `templates` | Создать новую |
| `items` | Создать новую |
| `history_uint/float/str/text/log` | Создать новые (5 таблиц) |
| `last_values` | Создать новую |
| `trends_uint/float` | Создать новые (2 таблицы) |
| `device_templates` | Создать новую |
| `audit_log` | Создать новую |
| `command_results` | Создать новую |
| `devices` (TZ-style) | Переработать `DiscoveredAsset` |
| `alerts` (TZ-style) | Переработать `AssetAlert` (BOOL active) |
| `agents` (TZ-style) | Переработать `ProxyAgent` (admin_status, cert) |
| `inventory` (TZ-style) | Переработать `AssetInventory` (+ `data_json`) |

---

## 6. Что оставить без изменений

| Модель | Причина |
|---|---|
| `Customer` | Работает как tenant, переименование не критично |
| `Device` (PC endpoint) | Другая подсистема (Windows MDM), параллельна proxy-agent |
| `HardwareInventory`, `PhysicalDisk`, `LogicalDisk` | Windows MDM, не конфликтует |
| `DeviceMetrics` | Windows MDM метрики, отдельная система |
| `EnrollmentToken` | Механизм правильный, используется |
| `ProxyAgentCommand` | Переработать, не выбросить |
| `SystemSettings` | Оставить |

---

## 7. Вывод

Текущий портал — **Windows MDM система**.
`portal_backend_tz.md` описывает **Zabbix-style систему для сетевого оборудования** через прокси-агент.

Это **две параллельные подсистемы** в одном портале:
- `Customer → Device → DeviceMetrics` — Windows MDM (остаётся)
- `Customer → DiscoveredAsset → history_*` — Proxy Agent (нужно построить с нуля)

Прямого конфликта нет, но **Zabbix-слой нужно строить как новый модуль** поверх существующей базы.
