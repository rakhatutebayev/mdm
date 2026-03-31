# Проверка цепочки данных только на proxy-agent (без портала)

Цель: убедиться, что агент **принимает** ответы SNMP, **собирает** словарь метрик/инвентаря и **отдаёт** готовый JSON в MQTT или в офлайн-очередь.

## Цепочка в коде

1. **Устройство + профиль** — SQLite: `Device` (`status=active`, `profile_id`, SNMP creds, IP), `DeviceProfile.output_mapping` (список `source_oid`, `target_key`, `poll_class`).
2. **Опрос** — `collectors/snmp_poller.py`: для каждого item тира выполняется SNMP GET по **литеральному** OID (строки с `{#…}` пропускаются).
3. **Подготовка данных** — словарь `data[target_key] = value` (после scale/range/dedup для метрик).
4. **Конверт** — `_build_envelope(...)`: `schema_version`, `tenant_id`, `agent_id`, `payload_type`, `records[].data = data`.
5. **Отправка** — `core/mqtt_client.py` → `publish(topic_suffix, envelope)`:
   - если MQTT **подключён** — `publish` на топик вида `nocko/{tenant}/{agent}/metrics.fast` (и т.д.);
   - если **нет** — запись в SQLite через `core/queue.py` (`enqueue`), позже `flush_queue`.

Портал/MDM здесь не участвует: достаточно брокера и корректных `tenant_id` / `agent_id` после bootstrap.

## Устройства в базе

1. **Автоматически (ТЗ §4.6):** после **`GET /api/v1/agent/config`** агент читает **`device_assignments`** и делает upsert в локальную таблицу `devices`. На стороне MDM в выдачу попадают записи **`agent_devices`**, у которых **`device_owner_agent_id`** = этот агент (и заданы **`device_uid`**, желательно **IP** и **profile** на устройстве). **`profile_slug`** в конфиге строится из **имени профиля** на сервере тем же правилом, что slug шаблона при импорте Zabbix в агент — имя профиля в портале и имя шаблона в файле должны совпадать, иначе на агенте заранее импортируйте шаблон с нужным `profile_id`. SNMP по умолчанию: переменные окружения бэкенда **`AGENT_DEVICE_DEFAULT_SNMP_COMMUNITY`**, **`AGENT_DEVICE_DEFAULT_SNMP_VERSION`**.
2. **Вручную:** веб-консоль **`/devices`** → форма «Добавить устройство».

## Где смотреть на хосте

| Шаг | Где проверить |
|-----|----------------|
| Консоль | `https://<host>:8443/diagnostics` (или HTTP, если TLS отключён) |
| Список целей | **`/devices`** — зарегистрированные для опроса устройства |
| Снимок опроса | Поля **fast / slow / inventory**: `pub` = число ключей в подготовленном payload; **keys=** — пример имён `target_key`; **mqtt=ok** — ушло в paho-publish (не в офлайн-очередь на этот шаг) |
| Очередь | **Queue pending** на той же странице; рост при **MQTT connected: no** |
| Логи | Сообщения `Published N metrics ... → MQTT` / `queued/offline` |

## Интерпретация (только агент)

- **`pub=0`, все в `macro`** — данные SNMP не собираются: в шаблоне только LLD-OID; нужны скалярные items.
- **`pub=0`, `snmp_fail` высокий** — до «подготовки payload» дело не доходит: сеть/community/v3.
- **`pub>0`, `keys=...`, `mqtt=no`** — payload **собран**, но брокер недоступен → смотреть `broker_url`, файрвол, TLS/серты; записи в очереди.
- **`pub>0`, `mqtt=ok`** — агент выполнил свою часть до брокера; дальше — брокер и подписчики (не тема этой заметки).

## Ручная проверка SNMP по профилю

В консоли: **Profiles → Verify SNMP** — один GET по первому **не-LLD** OID из маппинга на устройстве с этим профилем. Подтверждает доступность SNMP, но не заменяет полный опрос по всем ключам.
