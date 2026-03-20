# NOCKO Proxy Agent

`Proxy Agent` collects inventory from devices on the local network and uploads it to the portal through the discovery API.

## Current MVP

- local config bootstrap
- periodic ingest to `/api/v1/discovery/ingest`
- MQTT over TLS/WebSocket control channel for NAT-friendly agent/portal interaction
- template-driven normalization for:
  - `avaya_1608`
  - `dell_idrac`
  - `dell_idrac_redfish`
  - `switch_generic`
  - `generic_snmp`
- protocol collectors:
  - `snmp`
  - `redfish`

### iDRAC и хранилище по SNMP

Для целей с `template_key: "dell_idrac"` агент дополнительно обходит **Dell Storage / PERC MIB**
(физические диски, виртуальные тома, RAID-контроллеры). Это работает на **iDRAC 8/9** и новых прошивках.

- Для медленных BMC задайте **`storage_timeout_s`** (секунды на SNMP-запрос при walk) и **`retries: 1`**.
- Отключить обход таблиц: **`idrac_storage_enabled`: false**.
- На **iDRAC6** таблицы Dell Storage часто пустые — тогда добавляются **подсказки из Host Resources** (`hrDevice`: LUN, PERC в тексте). Полные слоты/serial всё равно надёжнее с **PERCCLI на ESXi** (`vmware_esxi` + SSH).

## Install

```bash
python3 -m pip install -r proxy_agent/requirements.txt
```

## Register local config

Use the token issued on the portal `Discovery` page.

```bash
python3 -m proxy_agent.main register \
  --server "https://portal.example.com" \
  --agent-id "proxy-agent-id-from-portal" \
  --token "proxy-REPLACE_ME" \
  --name "HQ Proxy Agent" \
  --site "HQ"
```

This writes config to:

```bash
~/.config/nocko-proxy-agent/config.json
```

## Configure collectors

Edit the generated config and add collectors under:
- `collectors.snmp_targets`
- `collectors.redfish_targets`

Each target should point to a `template_key` so the collector stays generic and the device-specific logic lives in templates.

Example:

```json
{
  "collectors": {
    "snmp_targets": [
      {
        "name": "Avaya phones",
        "subnet": "192.168.11.0/24",
        "community": "nocko1608ro",
        "template_key": "avaya_1608",
        "only_match": "avaya"
      },
      {
        "name": "iDRAC",
        "hosts": ["192.168.11.219"],
        "community": "public",
        "template_key": "dell_idrac"
      }
    ],
    "redfish_targets": [
      {
        "name": "iDRAC Redfish",
        "base_url": "https://192.168.11.219",
        "username": "root",
        "password": "CHANGE_ME",
        "verify_tls": false,
        "template_key": "dell_idrac_redfish"
      }
    ]
  }
}
```

## Run one cycle

```bash
python3 -m proxy_agent.main run --once --verbose
```

## Run continuously

```bash
python3 -m proxy_agent.main run
```

When `agent_id` and `agent_token` are configured, the agent also keeps an
outbound MQTT connection to the portal and can receive realtime commands like:

- `ping`
- `sync_now`

## Start local web console

```bash
python3 -m proxy_agent.main serve --bind 127.0.0.1 --port 8771
```

The console provides:

- local bootstrap and config editing
- SNMP and Redfish target management
- payload preview
- manual sync to portal
- last success/error diagnostics

## systemd example

```ini
[Unit]
Description=NOCKO Proxy Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/nocko-mdm
ExecStart=/usr/bin/python3 -m proxy_agent.main run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Notes

- The collector layer is protocol-oriented and the template layer is device-oriented.
- `redfish` is implemented for systems that expose a usable `/redfish/v1` API.
- Older iDRAC generations may not support Redfish at all, so SNMP can remain the fallback for them.
- `lldp` is still modeled as a capability but is not implemented yet.
- Realtime control uses outbound MQTT over WebSocket/TLS, which works behind NAT without inbound port forwarding.
- The local web console should stay bound to `127.0.0.1` unless you intentionally protect and expose it on the LAN.
- For production, use restricted ACLs and non-default SNMP communities.
