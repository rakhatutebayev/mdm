"""
VMware ESXi / vCenter collector for NOCKO Proxy Agent.

Connects to vSphere REST API (no pyVmomi needed) and collects metrics
defined in the imported VMware Zabbix template (collector_type="vmware").

Supported key patterns (subset of Zabbix vmware.* keys):
  vmware.fullname, vmware.version
  vmware.hv.cpu.usage, vmware.hv.cpu.usage.perf
  vmware.hv.hw.memory, vmware.hv.mem.usage, vmware.hv.uptime
  vmware.hv.status, vmware.hv.connectionstate, vmware.hv.fullname
  vmware.hv.hw.cpu.num, vmware.hv.hw.cpu.model, vmware.hv.hw.vendor, vmware.hv.hw.model
  vmware.vm.powerstate, vmware.vm.cpu.usage.perf, vmware.vm.memory.*
  vmware.datastore.size (pfree, total)
  icmpping — reported as 1 (alive) since we connected
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
from typing import Any

import aiohttp

from core.logger import log
from core.database import get_session, Device, DeviceProfile
from core.poll_diag import poll_diag
from sqlmodel import select

# ──────────────────────────────────────────────────────────────────────────────
# vSphere REST API client
# ──────────────────────────────────────────────────────────────────────────────

class VSphereClient:
    """Minimal async vSphere REST API client (no pyVmomi)."""

    def __init__(self, base_url: str, username: str, password: str):
        # Normalize: strip /sdk suffix if present
        self.base = base_url.rstrip("/").removesuffix("/sdk")
        self.username = username
        self.password = password
        self._session: aiohttp.ClientSession | None = None
        self._token: str = ""
        # Disable SSL verification for self-signed ESXi certs
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=self._ssl)
        self._session = aiohttp.ClientSession(connector=connector)
        await self._login()
        return self

    async def __aexit__(self, *args):
        try:
            await self._logout()
        except Exception:
            pass
        if self._session:
            await self._session.close()

    async def _login(self):
        """Try vSphere 7+ API first, fall back to older REST API."""
        url = f"{self.base}/api/session"
        try:
            async with self._session.post(
                url,
                auth=aiohttp.BasicAuth(self.username, self.password),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (200, 201):
                    token = await resp.text()
                    self._token = token.strip('"')
                    return
        except Exception:
            pass
        # Fallback: older REST API
        url2 = f"{self.base}/rest/com/vmware/cis/session"
        async with self._session.post(
            url2,
            auth=aiohttp.BasicAuth(self.username, self.password),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._token = data.get("value", "")

    async def _logout(self):
        if not self._token:
            return
        try:
            await self._session.delete(
                f"{self.base}/api/session",
                headers={"vmware-api-session-id": self._token},
                timeout=aiohttp.ClientTimeout(total=5),
            )
        except Exception:
            pass

    async def get(self, path: str) -> Any:
        """GET JSON from vSphere API path."""
        url = f"{self.base}{path}"
        async with self._session.get(
            url,
            headers={"vmware-api-session-id": self._token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ── High-level data fetchers ──────────────────────────────────────────────

    async def get_hosts(self) -> list[dict]:
        try:
            return await self.get("/api/vcenter/host") or []
        except Exception:
            # Standalone ESXi: try /api/hosts equivalent
            return []

    async def get_vms(self) -> list[dict]:
        try:
            return await self.get("/api/vcenter/vm") or []
        except Exception:
            return []

    async def get_datastores(self) -> list[dict]:
        try:
            return await self.get("/api/vcenter/datastore") or []
        except Exception:
            return []

    async def get_host_summary(self, host_id: str) -> dict:
        try:
            return await self.get(f"/api/vcenter/host/{host_id}") or {}
        except Exception:
            return {}

    async def get_vm_info(self, vm_id: str) -> dict:
        try:
            return await self.get(f"/api/vcenter/vm/{vm_id}") or {}
        except Exception:
            return {}

    async def get_datastore_info(self, ds_id: str) -> dict:
        try:
            return await self.get(f"/api/vcenter/datastore/{ds_id}") or {}
        except Exception:
            return {}

    async def get_appliance_version(self) -> dict:
        try:
            return await self.get("/api/appliance/system/version") or {}
        except Exception:
            return {}


# ──────────────────────────────────────────────────────────────────────────────
# Key-to-metric resolver
# ──────────────────────────────────────────────────────────────────────────────

def _strip_params(key: str) -> str:
    """vmware.hv.cpu.usage.perf[url,uuid] → vmware.hv.cpu.usage.perf"""
    return re.split(r"\[", key)[0].strip()


def _resolve_vmware_key(bare_key: str, ctx: dict[str, Any]) -> float | int | str | None:
    """
    Map a bare Zabbix vmware.* key to a value using pre-fetched context data.
    ctx keys: hosts, vms, datastores, version_info, host_summaries, vm_infos, ds_infos
    """
    k = bare_key.lower()

    # ── Service-level ─────────────────────────────────────────────────────────
    if k in ("vmware.fullname", "vmware.fullname[{$vmware.url}]"):
        v = ctx.get("version_info", {})
        return str(v.get("version", "") or v.get("build", "unknown"))

    if k in ("vmware.version", "vmware.version[{$vmware.url}]"):
        return str(ctx.get("version_info", {}).get("version", "unknown"))

    if k.startswith("icmpping"):
        return 1  # we connected → alive

    # ── Hypervisor ────────────────────────────────────────────────────────────
    hosts = ctx.get("hosts", [])
    if not hosts:
        return None

    host = hosts[0]  # primary host (standalone ESXi = 1 host)
    host_summary = ctx.get("host_summaries", {}).get(host.get("host", ""), {})

    if "vmware.hv.status" in k:
        status = str(host.get("connection_state", "connected")).lower()
        return 0 if status == "connected" else 1

    if "vmware.hv.connectionstate" in k:
        cs = str(host.get("connection_state", "connected")).lower()
        return {"connected": 0, "disconnected": 1, "notresponding": 2}.get(cs, 3)

    if "vmware.hv.power_state" in k or "powerstate" in k:
        ps = str(host.get("power_state", "POWERED_ON")).upper()
        return 0 if ps == "POWERED_ON" else 1

    config = host_summary.get("config", {})
    quick = host_summary.get("quick_stats", {})
    hw = config.get("hardware", {})

    if "vmware.hv.cpu.usage.perf" in k:
        # CPU usage MHz / total MHz * 100
        total_mhz = (hw.get("num_cpu_cores", 1) or 1) * (hw.get("cpu_mhz", 1000) or 1000)
        used_mhz = quick.get("overall_cpu_usage", 0) or 0
        return round(used_mhz / total_mhz * 100, 2)

    if "vmware.hv.cpu.usage" in k and "perf" not in k:
        return int(quick.get("overall_cpu_usage", 0) or 0) * 1_000_000  # MHz → Hz

    if "vmware.hv.hw.memory" in k:
        # RAM total in bytes
        return int(hw.get("memory_size", 0) or 0)

    if "vmware.hv.mem.usage" in k:
        total = int(hw.get("memory_size", 1) or 1)
        used_mb = int(quick.get("overall_memory_usage", 0) or 0)
        return round(used_mb * 1024 * 1024 / total * 100, 2)

    if "vmware.hv.uptime" in k:
        return int(quick.get("uptime", 0) or 0)

    if "vmware.hv.fullname" in k:
        return str(config.get("product", {}).get("full_name", "unknown"))

    if "vmware.hv.hw.cpu.num" in k:
        return int(hw.get("num_cpu_cores", 0) or 0)

    if "vmware.hv.hw.cpu.model" in k:
        return str(hw.get("cpu_model", "unknown"))

    if "vmware.hv.hw.vendor" in k:
        return str(hw.get("vendor", "unknown"))

    if "vmware.hv.hw.model" in k:
        return str(hw.get("model", "unknown"))

    if "vmware.hv.cluster.name" in k:
        return str(host.get("cluster", "—") or "—")

    if "vmware.hv.datacenter.name" in k:
        return str(host.get("datacenter", "—") or "—")

    # ── VMs ───────────────────────────────────────────────────────────────────
    vms = ctx.get("vms", [])
    if "vmware.vm" in k:
        # Aggregate across all VMs
        if "count" in k or k == "vmware.vm.num":
            return len(vms)
        if "powerstate" in k:
            return sum(
                1 for v in vms
                if str(v.get("power_state", "")).upper() == "POWERED_ON"
            )
        return None

    # ── Datastores ────────────────────────────────────────────────────────────
    datastores = ctx.get("datastores", [])
    if "vmware.datastore" in k:
        if not datastores:
            return None
        ds = datastores[0]
        ds_info = ctx.get("ds_infos", {}).get(ds.get("datastore", ""), {})
        capacity = int(ds_info.get("capacity", 0) or 0)
        free = int(ds_info.get("free_space", 0) or 0)
        if "pfree" in k:
            if capacity == 0:
                return 0.0
            return round(free / capacity * 100, 2)
        if "free" in k:
            return free
        return capacity  # total

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main poller loop
# ──────────────────────────────────────────────────────────────────────────────

_last_poll: dict[str, float] = {}


async def _poll_device(device: Device, mapping: list[dict]) -> list[dict]:
    """Poll one VMware device, return list of {key, value} dicts."""
    url = device.vmware_url or f"https://{device.ip}/sdk"
    results: list[dict] = []

    try:
        async with VSphereClient(url, device.vmware_username, device.vmware_password) as client:
            # Fetch all context data in parallel
            hosts, vms, datastores, version_info = await asyncio.gather(
                client.get_hosts(),
                client.get_vms(),
                client.get_datastores(),
                client.get_appliance_version(),
                return_exceptions=True,
            )
            hosts = hosts if isinstance(hosts, list) else []
            vms = vms if isinstance(vms, list) else []
            datastores = datastores if isinstance(datastores, list) else []
            version_info = version_info if isinstance(version_info, dict) else {}

            # Fetch host summaries
            host_summaries = {}
            for h in hosts[:5]:  # cap at 5 hosts
                hid = h.get("host", "")
                if hid:
                    host_summaries[hid] = await client.get_host_summary(hid)

            # Fetch datastore details
            ds_infos = {}
            for ds in datastores[:20]:
                dsid = ds.get("datastore", "")
                if dsid:
                    ds_infos[dsid] = await client.get_datastore_info(dsid)

            ctx = {
                "hosts": hosts,
                "vms": vms,
                "datastores": datastores,
                "version_info": version_info,
                "host_summaries": host_summaries,
                "ds_infos": ds_infos,
            }

            for row in mapping:
                if row.get("collector_type") != "vmware":
                    continue
                vmware_key = row.get("vmware_key", row.get("key", ""))
                bare_key = _strip_params(vmware_key).lower()
                try:
                    value = _resolve_vmware_key(bare_key, ctx)
                except Exception as e:
                    log.debug(f"VMware key resolve error {bare_key}: {e}")
                    value = None

                if value is not None:
                    results.append({
                        "key": row.get("key", bare_key),
                        "value": value,
                        "unit": row.get("unit", ""),
                    })

    except Exception as e:
        log.warning(f"VMware poll failed for {device.device_id} ({url}): {e}")

    return results


async def _publish_metrics(device: Device, metrics: list[dict], tier: str, mqtt_publish_fn):
    """Publish collected VMware metrics to MQTT."""
    if not metrics:
        return
    from core.database import kv_get
    tenant_id = kv_get("tenant_id", "")
    agent_id = kv_get("agent_id", "")
    topic = f"tenants/{tenant_id}/agents/{agent_id}/metrics/{tier}"
    payload = {
        "device_id": device.device_id,
        "ts": int(time.time()),
        "collector": "vmware",
        "metrics": {m["key"]: m["value"] for m in metrics},
    }
    try:
        await mqtt_publish_fn(topic, json.dumps(payload))
        log.debug(f"VMware: published {len(metrics)} metrics ({tier}) for {device.device_id}")
    except Exception as e:
        log.warning(f"VMware MQTT publish error: {e}")


async def vmware_poll_loop(mqtt_publish_fn, stop_event: asyncio.Event):
    """
    Main VMware polling loop. Runs until stop_event is set.
    Polls all devices with collector_type='vmware' on their configured intervals.
    """
    log.info("VMware poller started")
    while not stop_event.is_set():
        try:
            with get_session() as s:
                devices = s.exec(
                    select(Device).where(Device.collector_type == "vmware")
                    .where(Device.status == "active")
                ).all()
                # Load profiles
                device_profiles: dict[str, list[dict]] = {}
                for dev in devices:
                    if dev.profile_id:
                        prof = s.exec(
                            select(DeviceProfile).where(DeviceProfile.profile_id == dev.profile_id)
                        ).first()
                        if prof:
                            try:
                                mapping = json.loads(prof.output_mapping or "[]")
                            except Exception:
                                mapping = []
                            device_profiles[dev.device_id] = mapping
                    else:
                        device_profiles[dev.device_id] = []
                # expunge all devices so they can be used outside session
                for dev in devices:
                    s.expunge(dev)

            now = time.time()
            for dev in devices:
                mapping = device_profiles.get(dev.device_id, [])
                # Check fast interval
                last_fast = _last_poll.get(f"{dev.device_id}.fast", 0)
                if now - last_fast >= dev.poll_interval_fast:
                    fast_mapping = [r for r in mapping if r.get("poll_class") == "fast"]
                    if fast_mapping:
                        metrics = await _poll_device(dev, fast_mapping)
                        await _publish_metrics(dev, metrics, "fast", mqtt_publish_fn)
                        poll_diag.record_poll(dev.device_id, "fast", {
                            "values_published": len(metrics),
                            "snmp_failed": 0,
                            "mqtt_ok": True,
                        })
                    _last_poll[f"{dev.device_id}.fast"] = now

                # Check slow interval
                last_slow = _last_poll.get(f"{dev.device_id}.slow", 0)
                if now - last_slow >= dev.poll_interval_slow:
                    slow_mapping = [r for r in mapping if r.get("poll_class") == "slow"]
                    if slow_mapping:
                        metrics = await _poll_device(dev, slow_mapping)
                        await _publish_metrics(dev, metrics, "slow", mqtt_publish_fn)
                    _last_poll[f"{dev.device_id}.slow"] = now

        except Exception as e:
            log.error(f"VMware poller loop error: {e}")

        await asyncio.sleep(10)  # check interval tick

    log.info("VMware poller stopped")
