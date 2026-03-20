# Avaya 1608 SNMP Utility

Standalone subnet scanner for collecting Avaya phone data over SNMP v2c.

## Script

- `utils/avaya_1608_snmp_probe.py`

## Install dependency

```bash
python3 -m pip install pysnmp
```

## Usage examples

Scan full subnet:

```bash
python3 utils/avaya_1608_snmp_probe.py \
  --subnet 192.168.1.0/24 \
  --community public \
  --only-avaya
```

Scan specific hosts and export results:

```bash
python3 utils/avaya_1608_snmp_probe.py \
  --hosts 192.168.1.10,192.168.1.11 \
  --community public \
  --json-out /tmp/avaya.json \
  --csv-out /tmp/avaya.csv
```

## Returned fields

- `ip`
- `reachable`
- `vendor` (best-effort detection)
- `model`
- `serial`
- `mac`
- `firmware`
- `sys_name`
- `sys_descr`
- `uptime`

## Notes

- Utility is intentionally separate from backend/frontend runtime.
- SNMP access must be allowed from your host to phone subnet (UDP/161).
- For production, prefer SNMPv3 credentials and network ACLs.
