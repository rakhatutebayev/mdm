# NOCKO Proxy Agent (Linux)

SNMP polling, traps, local web console, MQTT/HTTPS к MDM.

## Боевой сервер

Основной установленный агент: **`192.168.11.153`** (см. [docs/deployment-runbook.md](../docs/deployment-runbook.md)).

- **Веб-консоль:** `https://192.168.11.153:8443` (TZ §6.2)
- **Самодиагностика JSON:** `https://192.168.11.153:8443/api/v1/diagnostics.json` (MQTT, очередь, приём SNMP по устройствам)
- **Лог:** раз в 5 мин строка `HEALTH_SUMMARY mqtt=… queue=… dev=… recv=…` — смотреть `grep HEALTH_SUMMARY /var/log/nocko-agent/agent.log`. Отключить: `NOCKO_HEALTH_LOG_SEC=0` в окружении сервиса; интервал: `NOCKO_HEALTH_LOG_SEC=600` (не меньше 60).
- **Конфиг:** `/opt/nocko-agent/config.json`
- **Логи:** `/var/log/nocko-agent/agent.log`
- **Сервис:** `sudo systemctl status nocko-agent`

Изменения для прода вносят **на этом хосте** или копируют туда (`rsync`/`scp`) и делают `systemctl restart nocko-agent`.

## Установка по ТЗ (§5)

**С MDM (one-liner):**

```bash
curl -fsSL "https://<ваш-mdm>/api/v1/agent/bootstrap/install.sh" | sudo bash -s -- '<enrollment_token>'
```

**Из клона репозитория:**

```bash
cd proxy-agent && sudo bash install.sh '<enrollment_token>'
```

**Обновление / удаление:**

```bash
sudo /opt/nocko-agent/install.sh --update
sudo /opt/nocko-agent/install.sh --uninstall
```

Подробности: [docs/linux-installer-tz-vs-impl.md](../docs/linux-installer-tz-vs-impl.md).

## Локальная разработка

См. `install.sh` и `config.json.example`. Доверенный CA для MDM/MQTT: `certs/mdm-ca.pem` (см. `certs/README.md`).

## Утилита проверки SNMP (`tools/snmp_check`)

Проверяет, **отвечает ли устройство на SNMP GET/WALK** тем же стеком, что и поллер (**puresnmp**). По умолчанию делает GET для `sysDescr`, `sysUpTime`, `sysName`.

```bash
cd proxy-agent

# По IP (v2c)
python3 -m tools.snmp_check --ip 192.168.1.10 -c public

# SNMP WALK по базовому OID
python3 -m tools.snmp_check --ip 192.168.1.10 -c public --walk 1.3.6.1.2.1.1

# Только WALK, без стандартных GET
python3 -m tools.snmp_check --ip 192.168.1.10 -c public --walk 1.3.6.1.2.1.2 --no-default-get

# Устройство из локальной БД агента
python3 -m tools.snmp_check --device my-server-id --config /etc/nocko-agent/config.json

# Все устройства из БД
python3 -m tools.snmp_check --all --config /etc/nocko-agent/config.json

# Список устройств в БД
python3 -m tools.snmp_check --list-devices --config /etc/nocko-agent/config.json

# Дополнительный OID и JSON
python3 -m tools.snmp_check --ip 10.0.0.1 -c public --oid 1.3.6.1.2.1.1.2.0 --json

# GET + WALK одновременно
python3 -m tools.snmp_check --device my-server-id --config /etc/nocko-agent/config.json --oid 1.3.6.1.2.1.1.2.0 --walk 1.3.6.1.2.1.1 -v
```

Код выхода: **0** — все операции успешны, **1** — нет ответа/ошибка SNMP, **2** — аргументы или нет записи в БД.

На установленном агенте: `cd /opt/nocko-agent && sudo python3 -m tools.snmp_check ...` (нужны права чтения `config.json` и БД).

## Импорт шаблонов Zabbix

В **локальной веб-консоли** (`/`, форма загрузки) поддерживаются экспорты Zabbix:

- **XML** — классический экспорт;
- **JSON / YAML** — формат `zabbix_export` (Zabbix 4.x–6.x+).

В каждом SNMP-item должен быть **`snmp_oid`**; по нему строится `output_mapping` для `snmp_poller`. Логика разбора: [`core/zabbix_import.py`](core/zabbix_import.py) (зависимость **`pyyaml`**).
