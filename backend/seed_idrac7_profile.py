"""
seed_idrac7_profile.py
──────────────────────
Seeds the Dell iDRAC7/8/9 SNMP monitoring profile into the NOCKO portal DB.

Creates:
  Profile:   "Dell iDRAC7/8/9"
  Templates:
    1. Information / Identity     (slow, inventory)
    2. Global Status              (fast)
    3. Power & PSU                (fast)
    4. Thermal - Temperatures     (fast)
    5. Thermal - Fans             (fast)
    6. CPU / Memory               (slow)
    7. Physical Disk / RAID       (slow)

All OIDs are from IDRAC-MIB (outOfBandGroup: 1.3.6.1.4.1.674.10892.5)

Usage:
  cd backend
  python seed_idrac7_profile.py [--tenant-id 1] [--api-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import sys
import httpx

# ─── Tenant-ID header (MVP) ───────────────────────────────────────────────────
DEFAULT_TENANT = "1"
DEFAULT_URL = "http://localhost:8000"

# ─── Profile definition ───────────────────────────────────────────────────────
PROFILE = {
    "name": "Dell iDRAC7/8/9",
    "vendor": "Dell",
    "version": "1.0.0",
    "description": "Dell PowerEdge iDRAC7, iDRAC8 and iDRAC9 out-of-band SNMP monitoring. "
                   "OIDs from IDRAC-MIB (enterprise 1.3.6.1.4.1.674.10892.5).",
}

# ─── Templates and items ──────────────────────────────────────────────────────
# Each item:  (key, name, oid_suffix, value_type, poll_class, interval_sec)
# OID base: 1.3.6.1.4.1.674.10892.5

TEMPLATES = [
    {
        "name": "Identity & Info",
        "description": "Static RAC and system identity scalars. Poll infrequently.",
        "items": [
            # rac info group (5.1.1.*)
            ("idrac.rac.name",         "RAC Product Name",       "1.3.6.1.4.1.674.10892.5.1.1.1.0",  "string",   "inventory", 3600),
            ("idrac.rac.short_name",   "RAC Short Name",         "1.3.6.1.4.1.674.10892.5.1.1.2.0",  "string",   "inventory", 3600),
            ("idrac.rac.version",      "RAC Version",            "1.3.6.1.4.1.674.10892.5.1.1.5.0",  "string",   "inventory", 3600),
            ("idrac.rac.fw_version",   "RAC Firmware Version",   "1.3.6.1.4.1.674.10892.5.1.1.8.0",  "string",   "inventory", 3600),
            ("idrac.rac.url",          "RAC Management URL",     "1.3.6.1.4.1.674.10892.5.1.1.6.0",  "string",   "inventory", 3600),
            # system info group (5.1.3.*)
            ("idrac.sys.fqdn",         "System FQDN",            "1.3.6.1.4.1.674.10892.5.1.3.1.0",  "string",   "inventory", 3600),
            ("idrac.sys.service_tag",  "System Service Tag",     "1.3.6.1.4.1.674.10892.5.1.3.2.0",  "string",   "inventory", 3600),
            ("idrac.sys.asset_tag",    "Asset Tag",              "1.3.6.1.4.1.674.10892.5.1.3.4.0",  "string",   "inventory", 3600),
            ("idrac.sys.model",        "System Model",           "1.3.6.1.4.1.674.10892.5.1.3.12.0", "string",   "inventory", 3600),
            ("idrac.sys.os_name",      "OS Name",                "1.3.6.1.4.1.674.10892.5.1.3.6.0",  "string",   "inventory", 3600),
            ("idrac.sys.os_version",   "OS Version",             "1.3.6.1.4.1.674.10892.5.1.3.14.0", "string",   "inventory", 3600),
            ("idrac.sys.rack_name",    "Rack Name",              "1.3.6.1.4.1.674.10892.5.1.3.10.0", "string",   "inventory", 3600),
            ("idrac.sys.rack_slot",    "Rack Slot",              "1.3.6.1.4.1.674.10892.5.1.3.11.0", "string",   "inventory", 3600),
            ("idrac.sys.datacenter",   "Data Center",            "1.3.6.1.4.1.674.10892.5.1.3.8.0",  "string",   "inventory", 3600),
            ("idrac.sys.node_id",      "Node ID",                "1.3.6.1.4.1.674.10892.5.1.3.18.0", "string",   "inventory", 3600),
        ],
    },
    {
        "name": "Global Status",
        "description": "Top-level health rollup status scalars. Fast poll for alerting.",
        "items": [
            # status group (5.2.*)
            ("idrac.status.global",      "Global System Status",  "1.3.6.1.4.1.674.10892.5.2.1.0",   "uint",  "fast",  60),
            ("idrac.status.lcd",         "LCD Status",            "1.3.6.1.4.1.674.10892.5.2.2.0",   "uint",  "fast",  60),
            ("idrac.status.storage",     "Global Storage Status", "1.3.6.1.4.1.674.10892.5.2.3.0",   "uint",  "fast",  60),
            ("idrac.status.power_state", "System Power State",    "1.3.6.1.4.1.674.10892.5.2.4.0",   "uint",  "fast",  30),
            ("idrac.status.power_uptime","System Uptime (sec)",   "1.3.6.1.4.1.674.10892.5.2.5.0",   "uint",  "slow",  300),
        ],
    },
    {
        "name": "Power & PSU",
        "description": "Power supply and power consumption metrics.",
        "items": [
            # powerSupplyTable (5.4.600.12.1.*) — index .1 = chassis 1
            ("idrac.psu.1.status",       "PSU 1 Status",           "1.3.6.1.4.1.674.10892.5.4.600.12.1.5.1.1",  "uint",   "fast",   60),
            ("idrac.psu.1.output_watts", "PSU 1 Output (W)",       "1.3.6.1.4.1.674.10892.5.4.600.12.1.6.1.1",  "uint",   "fast",   60),
            ("idrac.psu.1.input_watts",  "PSU 1 Max Input (W)",    "1.3.6.1.4.1.674.10892.5.4.600.12.1.7.1.1",  "uint",   "slow",   300),
            ("idrac.psu.1.type",         "PSU 1 Type",             "1.3.6.1.4.1.674.10892.5.4.600.12.1.21.1.1", "uint",   "inventory", 3600),
            ("idrac.psu.2.status",       "PSU 2 Status",           "1.3.6.1.4.1.674.10892.5.4.600.12.1.5.1.2",  "uint",   "fast",   60),
            ("idrac.psu.2.output_watts", "PSU 2 Output (W)",       "1.3.6.1.4.1.674.10892.5.4.600.12.1.6.1.2",  "uint",   "fast",   60),
            # powerUsageTable (5.4.600.30.1.*) cumulative power
            ("idrac.power.usage_watt",   "System Power Usage (W)", "1.3.6.1.4.1.674.10892.5.4.600.30.1.6.1.1",  "uint",   "fast",   60),
            ("idrac.power.peak_watt",    "Peak Power Usage (W)",   "1.3.6.1.4.1.674.10892.5.4.600.30.1.8.1.1",  "uint",   "slow",   300),
        ],
    },
    {
        "name": "Thermal - Temperatures",
        "description": "Temperature probe readings (°C × 10 — divide by 10 for display).",
        "items": [
            # temperatureProbeTable (5.4.700.20.1.*) — index .1=chassis, indices 1..N
            ("idrac.temp.1.reading",   "Temp Probe 1 (°C×10)",    "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1",  "uint",  "fast",  60),
            ("idrac.temp.1.status",    "Temp Probe 1 Status",     "1.3.6.1.4.1.674.10892.5.4.700.20.1.5.1.1",  "uint",  "fast",  60),
            ("idrac.temp.1.type",      "Temp Probe 1 Type",       "1.3.6.1.4.1.674.10892.5.4.700.20.1.7.1.1",  "uint",  "inventory", 3600),
            ("idrac.temp.1.warn_hi",   "Temp Probe 1 Warn High",  "1.3.6.1.4.1.674.10892.5.4.700.20.1.11.1.1", "uint",  "inventory", 3600),
            ("idrac.temp.1.crit_hi",   "Temp Probe 1 Crit High",  "1.3.6.1.4.1.674.10892.5.4.700.20.1.13.1.1", "uint",  "inventory", 3600),
            ("idrac.temp.2.reading",   "Temp Probe 2 (°C×10)",    "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.2",  "uint",  "fast",  60),
            ("idrac.temp.2.status",    "Temp Probe 2 Status",     "1.3.6.1.4.1.674.10892.5.4.700.20.1.5.1.2",  "uint",  "fast",  60),
        ],
    },
    {
        "name": "Thermal - Fans",
        "description": "Fan speed (RPM) and status.",
        "items": [
            # coolingDeviceTable (5.4.700.12.1.*) — index .1=chassis, .N=fan id
            ("idrac.fan.1.status",   "Fan 1 Status",   "1.3.6.1.4.1.674.10892.5.4.700.12.1.5.1.1",  "uint",  "fast",  60),
            ("idrac.fan.1.rpm",      "Fan 1 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1","uint",  "fast",  60),
            ("idrac.fan.2.status",   "Fan 2 Status",   "1.3.6.1.4.1.674.10892.5.4.700.12.1.5.1.2",  "uint",  "fast",  60),
            ("idrac.fan.2.rpm",      "Fan 2 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.2","uint",  "fast",  60),
            ("idrac.fan.3.status",   "Fan 3 Status",   "1.3.6.1.4.1.674.10892.5.4.700.12.1.5.1.3",  "uint",  "fast",  60),
            ("idrac.fan.3.rpm",      "Fan 3 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.3","uint",  "fast",  60),
            ("idrac.fan.4.rpm",      "Fan 4 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.4","uint",  "fast",  60),
            ("idrac.fan.5.rpm",      "Fan 5 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.5","uint",  "fast",  60),
            ("idrac.fan.6.rpm",      "Fan 6 Speed (RPM)", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.6","uint",  "fast",  60),
        ],
    },
    {
        "name": "CPU State",
        "description": "CPU device state from iDRAC system state table (index per socket).",
        "items": [
            # processorDeviceTable (5.4.1100.32.1.*)
            ("idrac.cpu.1.status",    "CPU 1 Status",    "1.3.6.1.4.1.674.10892.5.4.1100.32.1.5.1.1",  "uint",  "slow",  120),
            ("idrac.cpu.1.speed",     "CPU 1 Speed (MHz)","1.3.6.1.4.1.674.10892.5.4.1100.32.1.11.1.1", "uint",  "inventory", 3600),
            ("idrac.cpu.1.brand",     "CPU 1 Brand",     "1.3.6.1.4.1.674.10892.5.4.1100.32.1.23.1.1",  "string","inventory", 3600),
            ("idrac.cpu.1.cores",     "CPU 1 Core Count","1.3.6.1.4.1.674.10892.5.4.1100.32.1.17.1.1",  "uint",  "inventory", 3600),
            ("idrac.cpu.2.status",    "CPU 2 Status",    "1.3.6.1.4.1.674.10892.5.4.1100.32.1.5.1.2",  "uint",  "slow",  120),
            ("idrac.cpu.2.speed",     "CPU 2 Speed (MHz)","1.3.6.1.4.1.674.10892.5.4.1100.32.1.11.1.2", "uint",  "inventory", 3600),
            # memoryDeviceTable (5.4.1100.50.1.*)
            ("idrac.mem.total.status", "Memory Status",  "1.3.6.1.4.1.674.10892.5.4.1100.50.1.5.1.1",  "uint",  "slow",  120),
            ("idrac.mem.1.size_kb",   "DIMM 1 Size (KB)","1.3.6.1.4.1.674.10892.5.4.1100.50.1.14.1.1", "uint",  "inventory", 3600),
            ("idrac.mem.1.speed_mhz", "DIMM 1 Speed (MHz)","1.3.6.1.4.1.674.10892.5.4.1100.50.1.15.1.1","uint",  "inventory", 3600),
            ("idrac.mem.1.type",      "DIMM 1 Type",    "1.3.6.1.4.1.674.10892.5.4.1100.50.1.7.1.1",   "uint",  "inventory", 3600),
        ],
    },
    {
        "name": "Physical Disk & RAID",
        "description": "Physical disk presence and virtual disk (RAID) status.",
        "items": [
            # physicalDisk table (5.5.1.20.130.*)
            ("idrac.disk.phy.1.status",  "Physical Disk 1 Status","1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.1.1.1", "uint", "slow", 120),
            ("idrac.disk.phy.1.state",   "Physical Disk 1 State", "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.2.1.1", "uint", "slow", 120),
            ("idrac.disk.phy.1.cap_mb",  "Physical Disk 1 Cap (MB)","1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.10.1.1","uint", "inventory", 3600),
            ("idrac.disk.phy.1.vendor",  "Physical Disk 1 Vendor","1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.12.1.1","string","inventory",3600),
            ("idrac.disk.phy.2.status",  "Physical Disk 2 Status","1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.1.1.2", "uint", "slow", 120),
            ("idrac.disk.phy.2.state",   "Physical Disk 2 State", "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.2.1.2", "uint", "slow", 120),
            # virtualDisk table (5.5.1.20.140.*)
            ("idrac.disk.virt.1.status", "Virtual Disk 1 Status", "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.47.1.1","uint", "slow", 120),
            ("idrac.disk.virt.1.raid",   "Virtual Disk 1 RAID Level","1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.13.1.1","uint","inventory",3600),
        ],
    },
]


def _headers(tenant_id: str) -> dict:
    return {"X-Tenant-Id": tenant_id, "Content-Type": "application/json"}


def seed(api_url: str, tenant_id: str) -> None:
    base = f"{api_url}/api/v1/portal"
    h = _headers(tenant_id)

    with httpx.Client(timeout=30) as client:
        # 1. Create profile
        print(f"Creating profile: {PROFILE['name']}")
        r = client.post(f"{base}/profiles", headers=h, json=PROFILE)
        if r.status_code not in (200, 201):
            if r.status_code == 409:
                print("  ⚠  Profile already exists — trying to find it.")
                lst = client.get(f"{base}/profiles", headers=h).json()
                profile_id = next((p["id"] for p in lst if p["name"] == PROFILE["name"]), None)
                if not profile_id:
                    print("  ✗  Cannot locate existing profile. Aborting.")
                    sys.exit(1)
            else:
                print(f"  ✗  {r.status_code}: {r.text}")
                sys.exit(1)
        else:
            profile_id = r.json()["id"]
        print(f"  ✓  Profile id={profile_id}")

        # 2. Create templates + items
        for tmpl_def in TEMPLATES:
            print(f"\nCreating template: {tmpl_def['name']}")
            r = client.post(
                f"{base}/profiles/{profile_id}/templates",
                headers=h,
                json={"name": tmpl_def["name"], "description": tmpl_def.get("description", "")},
            )
            if r.status_code not in (200, 201):
                print(f"  ✗  {r.status_code}: {r.text}")
                continue
            tmpl_id = r.json()["id"]
            print(f"  ✓  Template id={tmpl_id}")

            created = 0
            skipped = 0
            for (key, name, oid, vtype, pclass, interval) in tmpl_def["items"]:
                ri = client.post(
                    f"{base}/templates/{tmpl_id}/items",
                    headers=h,
                    json={
                        "key": key,
                        "name": name,
                        "value_type": vtype,
                        "poll_class": pclass,
                        "interval_sec": interval,
                    },
                )
                if ri.status_code in (200, 201):
                    created += 1
                elif ri.status_code == 409:
                    skipped += 1
                else:
                    print(f"    ! item '{key}': {ri.status_code} {ri.text[:60]}")
            print(f"    Items: {created} created, {skipped} skipped (key already exists)")

        print("\n✅ iDRAC7/8/9 profile seeded successfully.")
        print(f"   Profile id={profile_id}, {len(TEMPLATES)} templates.")
        print(f"\nUse /network/profiles in the portal to assign templates to devices.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Dell iDRAC7/8/9 SNMP profile into NOCKO portal.")
    parser.add_argument("--api-url", default=DEFAULT_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT)
    args = parser.parse_args()
    seed(args.api_url, args.tenant_id)
