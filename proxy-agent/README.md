# NOCKO Proxy Agent (Linux)

SNMP polling, traps, local web console, MQTT/HTTPS к MDM.

## Боевой сервер

Основной установленный агент: **`192.168.11.153`** (см. [docs/deployment-runbook.md](../docs/deployment-runbook.md)).

- **Веб-консоль:** `https://192.168.11.153:8443` (TZ §6.2)
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

## Импорт шаблонов Zabbix

В **локальной веб-консоли** (`/`, форма загрузки) поддерживаются экспорты Zabbix:

- **XML** — классический экспорт;
- **JSON / YAML** — формат `zabbix_export` (Zabbix 4.x–6.x+).

В каждом SNMP-item должен быть **`snmp_oid`**; по нему строится `output_mapping` для `snmp_poller`. Логика разбора: [`core/zabbix_import.py`](core/zabbix_import.py) (зависимость **`pyyaml`**).
