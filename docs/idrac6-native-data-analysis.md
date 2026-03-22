# iDRAC6 Native Data Analysis

## Purpose

This document records the verified capabilities and limits of the live Dell `iDRAC6` device at `192.168.11.219` for the server dashboard based on `docs/ux/server_dashboard_idrac6_advanced.html`.

The goal of this analysis is strict:

- use only data exposed by `iDRAC6`
- do not mix data from `ESXi`
- do not invent values that are not returned by the device

## Scope

This analysis was performed against the live target using three iDRAC-native access paths:

- `SNMP`
- `racadm` over SSH
- `WS-Man` over HTTPS

The result is a field-by-field conclusion about what can be populated honestly in the dashboard.

## Final Conclusion

For this specific device and firmware combination, `iDRAC6-only` data is sufficient for:

- global system identity
- controller and BIOS versions
- management IP and network state
- power and PSU information
- managed OS label reported by iDRAC
- historical alerts from `SEL`

For this specific device and firmware combination, `iDRAC6-only` data is not sufficient for full live inventory of:

- `CPU` table
- `RAM` table
- `Storage / RAID / physical disks` table
- numeric live temperature sensor table

This is not a template problem and not a frontend problem. It is a source limitation of the live `iDRAC6`.

## Verified Evidence

### 1. SNMP

#### Confirmed working branch

Walking the Dell enterprise subtree shows that the device exposes only a small set of values under:

- `1.3.6.1.4.1.674.10892.2.*`

Observed values include:

- controller name
- product name
- description
- vendor
- firmware version
- management URL
- service tag
- global status

Example confirmed values:

- `Integrated Dell Remote Access Controller 6`
- `iDRAC6`
- firmware `2.92 (Build "05")`
- URL `https://192.168.11.219:443`
- service tag `C2P3S4J`

#### Missing Dell inventory branches

The following Dell subtree was tested and is not exposed by the live device:

- `1.3.6.1.4.1.674.10893`

Observed result:

- `No Such Object available on this agent at this OID`

This matters because many inventory OIDs from documentation and MIB exports are only useful if the agent actually publishes those branches. This device does not.

#### Missing standard MIB inventory tables

The following standard tables were also tested and are not exposed:

- `ENTITY-MIB` at `1.3.6.1.2.1.47.1.1.1.1`
- `ENTITY-SENSOR-MIB` at `1.3.6.1.2.1.99.1.1.1`
- `HOST-RESOURCES-MIB` device table at `1.3.6.1.2.1.25.3.2.1`
- `HOST-RESOURCES-MIB` storage table at `1.3.6.1.2.1.25.2.3.1`

Observed result for all of them:

- `No Such Object available on this agent at this OID`

#### SNMP conclusion

`SNMP` on this device is usable for controller-level metadata and basic status, but it does not expose enough inventory structure to build complete live `CPU`, `RAM`, `Storage`, or sensor tables.

### 2. racadm over SSH

#### Confirmed working commands

The following commands were verified as working and returning useful data:

- `racadm getsysinfo`
- `racadm getversion`
- `racadm getniccfg`
- `racadm getconfig -g cfgServerPower`
- `racadm getconfig -g cfgServerPowerSupply -i 1`
- `racadm getconfig -g cfgServerPowerSupply -i 2`
- `racadm getconfig -g ifcRacManagedNodeOs`
- `racadm getsel -o`

#### Confirmed fields returned by racadm

`racadm getsysinfo` returns:

- model: `PowerEdge R710`
- BIOS version: `2.0.13`
- service tag: `C2P3S4J`
- host name: `localhost`
- managed OS name: `VMware ESXi`
- power status: `ON`
- embedded NIC MAC addresses
- iDRAC IP configuration

`racadm getversion` returns:

- BIOS version: `2.0.13`
- iDRAC version: `2.92`
- USC version: `1.3.0.350`

`racadm getniccfg` returns:

- IP address: `192.168.11.219`
- subnet mask
- gateway
- LOM status
- link detected
- link speed
- duplex mode
- active LOM

`racadm getconfig -g cfgServerPower` returns:

- server power status
- actual power consumption
- min and max power capacity
- peak power consumption and timestamp
- hourly and daily min and max power windows
- amperage
- cumulative power consumption

`racadm getconfig -g cfgServerPowerSupply -i 1/2` returns for each PSU:

- presence status
- max input power
- max output power
- firmware version
- current draw
- power supply type

`racadm getconfig -g ifcRacManagedNodeOs` returns:

- managed node hostname
- managed OS name

`racadm getsel -o` returns:

- historical event log with timestamps where available
- severity-like text in message body
- component-related history for power, fans, temperature, chassis, drives, and memory events

#### Confirmed limits of racadm on this iDRAC6

The built-in command help is very limited. The live device exposes configuration groups such as:

- `cfgLanNetworking`
- `cfgOobSnmp`
- `cfgServerPower`
- `cfgServerPowerSupply`
- `cfgServerInfo`
- `cfgSensorRedundancy`
- `ifcRacManagedNodeOs`

The live device does not expose richer inventory groups that would normally be required for full dashboard hardware population, such as:

- `cfgServerMemory`
- `cfgServerProc`
- `cfgStorageController`
- `cfgServerVirtualDisk`
- `cfgServerPhysicalDisk`
- detailed thermal or sensor inventory groups

`cfgSensorRedundancy` was also checked and does not provide a useful per-sensor inventory table.

#### racadm conclusion

`racadm` is the strongest native source available on this device, but even it stops at system identity, management network, power, PSU, managed OS label, and alert history. It does not expose the full live hardware inventory required for exact `CPU`, `RAM`, and `Storage` tables.

### 3. WS-Man over HTTPS

#### Transport result

The endpoint URL is reachable:

- `https://192.168.11.219/wsman`

The device requires legacy TLS handling. A simple HTTPS probe can return `200 OK`.

#### Functional result

When tested with SOAP `POST` requests for `Identify` and Dell `DCIM_*` resource access, the device returned:

- `HTTP/1.1 404 Not Found`

This means that, in the current state of this device, `WS-Man` could not be confirmed as a working inventory channel.

#### WS-Man conclusion

`WS-Man` was the last realistic iDRAC-only path that might have exposed `DCIM_CPUView`, `DCIM_MemoryView`, or disk inventory. It did not produce working inventory results on this live device.

## Template Mapping

The dashboard template at `docs/ux/server_dashboard_idrac6_advanced.html` contains these key sections:

- `Global Information`
- `Environmental`
- `Processors (CPU)`
- `Memory (RAM)`
- `Storage Subsystem (RAID & Disks)`
- `Active System Alerts`

### Global Information

Status: `confirmed`

Can be populated from `iDRAC6` using:

- `racadm getsysinfo`
- `racadm getversion`
- Dell SNMP scalars under `1.3.6.1.4.1.674.10892.2.*`

Confirmed fields:

- system health
- model name
- service tag
- management IP

Additional safe fields if needed:

- BIOS version
- iDRAC version
- USC version
- power status

### Environmental

Status: `partial`

Confirmed live data:

- PSU 1 status
- PSU 2 status
- power metrics

Only event-level evidence:

- ambient temperature warning/ok transitions in `SEL`
- fan redundancy and fan threshold events in `SEL`

Not confirmed as live numeric inventory:

- current inlet temperature value
- per-fan RPM table
- per-temperature-probe list

### Processors (CPU)

Status: `not exposed`

Not confirmed from live `SNMP`, `racadm`, or `WS-Man`:

- socket list
- processor model per socket
- live processor status per socket

Possible event-only references may exist in logs, but that is not enough to build the template table honestly.

### Memory (RAM)

Status: `event-only`

Confirmed from logs:

- memory-related alerts can appear in `SEL`
- example: correctable memory error references a DIMM location

Not confirmed as live inventory:

- DIMM slot list
- module capacity
- memory type
- memory speed
- total memory derived from module inventory

### Storage Subsystem (RAID & Disks)

Status: `event-only`

Confirmed from logs:

- drive removal and install events appear in `SEL`

Not confirmed as live inventory:

- virtual disk list
- RAID level
- virtual disk health
- physical disk list
- bay-to-model live mapping
- hot spare inventory

### Active System Alerts

Status: `confirmed`

Can be populated from:

- `racadm getsel -o`

This is the strongest section after global info because the device exposes real historical events, including timestamps when available.

Examples confirmed in `SEL`:

- PSU redundancy lost/restored
- PSU input lost/restored
- chassis open/closed
- ambient temperature threshold exceeded/restored
- drive removed/installed
- memory ECC or correctable memory issues
- fan threshold and redundancy events

## Implications for Implementation

If the requirement remains strict `iDRAC6-only`, the implementation should follow these rules:

- populate only confirmed values
- do not synthesize `CPU`, `RAM`, or `Storage` inventory from unrelated sources
- keep the template structure unchanged
- render unavailable sections honestly as unavailable from the current iDRAC6 payload
- continue using `SEL` as the source for alert history and event timestamps

## Recommended Policy

For this server class and this live device, the safest policy is:

1. Treat `Global Information` and `Active System Alerts` as primary supported sections.
2. Treat `Environmental` as partially supported.
3. Treat `CPU`, `RAM`, and `Storage` inventory as unsupported unless a new iDRAC-native source is proven with live data first.
4. Never backfill these unsupported sections from `ESXi` when strict source separation is required.

## Short Answer

For `192.168.11.219`, the missing dashboard values are missing because the source does not expose them, not because the template mapping is incomplete.
