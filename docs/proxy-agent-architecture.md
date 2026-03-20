# Proxy Agent Architecture

`Proxy Agent` is the collection plane for devices that are visible on the local network but are not managed by the Windows MDM agent.

## Design Goals

- Keep `enrollment` reserved for onboarding managed endpoints.
- Keep `devices` reserved for actively managed MDM devices and commands.
- Store network-discovered equipment separately so iDRAC, Avaya, switches, printers, and other SNMP/Redfish targets do not pretend to be enrolled workstations.

## New Backend Entities

### `ProxyAgent`

Represents the collector itself.

- `customer_id`
- `name`
- `site_name`
- `hostname`
- `ip_address`
- `version`
- `status`
- `capabilities`
- `auth_token`
- `last_checkin`

### `DiscoveredAsset`

Represents an observed device on the network.

- `customer_id`
- `proxy_agent_id`
- `asset_class`
- `source_type`
- `display_name`
- `vendor`
- `model`
- `serial_number`
- `firmware_version`
- `ip_address`
- `management_ip`
- `mac_address`
- `status`
- `raw_facts`
- `first_seen_at`
- `last_seen_at`

## API Flow

### Register a collector

`POST /api/v1/discovery/agents`

Use this to create a `Proxy Agent` and issue its `auth_token`.

### Collector heartbeat and batch upload

`POST /api/v1/discovery/ingest`

The collector authenticates with `agent_token`, updates its own heartbeat metadata, and uploads a batch of assets. Assets are upserted by the best available identity in this order:

1. `serial_number`
2. `management_ip`
3. `ip_address`
4. `mac_address`

### Read discovery inventory

- `GET /api/v1/discovery/agents`
- `GET /api/v1/discovery/assets`
- `GET /api/v1/discovery/assets/{asset_id}`

## Example Ingest Payload

```json
{
  "agent_token": "proxy-REPLACE_ME",
  "agent": {
    "hostname": "proxy-branch-01",
    "ip_address": "192.168.11.153",
    "version": "0.1.0",
    "site_name": "HQ",
    "capabilities": ["snmp", "redfish", "lldp"]
  },
  "assets": [
    {
      "asset_class": "idrac",
      "display_name": "R710 iDRAC",
      "vendor": "Dell",
      "model": "iDRAC6",
      "serial_number": "",
      "firmware_version": "2.92",
      "management_ip": "192.168.11.219",
      "ip_address": "192.168.11.219",
      "mac_address": "",
      "status": "Discovered",
      "raw_facts": {
        "protocol": "redfish",
        "power_state": "On"
      }
    },
    {
      "asset_class": "voip",
      "display_name": "Avaya 1608",
      "vendor": "Avaya",
      "model": "1608",
      "serial_number": "",
      "firmware_version": "",
      "management_ip": "192.168.11.25",
      "ip_address": "192.168.11.25",
      "mac_address": "",
      "status": "Discovered",
      "raw_facts": {
        "protocol": "snmp",
        "community": "nocko1608ro"
      }
    }
  ]
}
```

## Recommended Next Layer

- Split protocol collectors from device templates:
  - collectors: `snmp`, `redfish`, `lldp`, `ssh`
  - templates: `avaya_1608`, `dell_idrac`, `dell_idrac_redfish`, `switch_generic`, `generic_snmp`
- Add typed source-specific parsers for `snmp`, `redfish`, `lldp`, and `ssh`.
- Add asset linking so a discovered asset can later be mapped to a managed `Device`.
- Add history tables if you want change tracking for firmware, port, or topology snapshots.
