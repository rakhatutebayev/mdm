# Avaya SNMP Scan Report

- Generated at (UTC): `2026-03-19T17:57:33Z`
- Scanner: `utils/avaya_1608_snmp_probe.py`
- Filter: `--only-avaya`
- SNMP settings: community `public`, port `161`, timeout `0.6s`, retries `0`, workers `64`

## Subnets Scanned

| Subnet | Hosts Scanned | Avaya Matches |
|---|---:|---:|
| `192.168.11.0/24` | 254 | 0 |
| `10.37.129.0/24` | 254 | 0 |
| `10.211.55.0/24` | 254 | 0 |

## Result

No Avaya devices were detected using SNMP v2c (`community=public`) in scanned subnets.

## Raw JSON Outputs

- `utils/avaya_scan_192.168.11.0_24.json`
- `utils/avaya_scan_10.37.129.0_24.json`
- `utils/avaya_scan_10.211.55.0_24.json`

## Notes

- If Avaya 1608 phones are present but not detected, likely causes:
  - SNMP disabled on phones
  - different community string (not `public`)
  - ACL/firewall blocks UDP/161 from this host
  - phones are in a different VLAN/subnet
