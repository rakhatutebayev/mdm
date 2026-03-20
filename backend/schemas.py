"""Pydantic schemas for NOCKO MDM API."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Customer ──────────────────────────────────────────────────────────────────
class CustomerCreate(BaseModel):
    name: str
    slug: str

class CustomerOut(BaseModel):
    id: str
    name: str
    slug: str
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Network ───────────────────────────────────────────────────────────────────
class NetworkInfoOut(BaseModel):
    ip_address: str
    mac_address: str
    hostname: str
    wifi_ssid: str
    connection_type: str
    dns_server: str
    default_gateway: str
    model_config = {"from_attributes": True}


# ── Monitor ───────────────────────────────────────────────────────────────────
class MonitorInfoOut(BaseModel):
    display_index: int
    manufacturer: str
    model: str
    serial_number: str
    display_size: str
    resolution: str
    refresh_rate: str
    color_depth: str
    connection_type: str
    hdr_support: bool
    model_config = {"from_attributes": True}


class HardwareInventoryOut(BaseModel):
    processor_model: str
    processor_vendor: str
    physical_cores: Optional[int]
    logical_processors: Optional[int]
    memory_total_gb: Optional[float]
    memory_slot_count: Optional[int]
    memory_slots_used: Optional[int]
    memory_module_count: Optional[int]
    machine_class: str
    chassis_type: str
    gpu_model: str = ""
    gpu_manufacturer: str = ""
    gpu_vram_gb: Optional[float] = None
    gpu_driver_version: str = ""
    model_config = {"from_attributes": True}


class PhysicalDiskOut(BaseModel):
    disk_index: Optional[int]
    model: str
    serial_number: str
    media_type: str
    interface_type: str
    size_gb: Optional[float]
    model_config = {"from_attributes": True}


class LogicalDiskOut(BaseModel):
    name: str
    volume_name: str
    file_system: str
    drive_type: str
    size_gb: Optional[float]
    free_gb: Optional[float]
    used_gb: Optional[float]
    model_config = {"from_attributes": True}


class PrinterInfoOut(BaseModel):
    name: str
    driver_name: str
    port_name: str
    ip_address: str = ""
    is_default: bool
    is_network: bool
    is_shared: bool = False
    work_offline: bool = False
    job_count: Optional[int] = None
    connection_type: str = ""
    status: str
    model_config = {"from_attributes": True}


class PrinterCreateIn(BaseModel):
    name: str = ""
    driver_name: str = ""
    port_name: str = ""
    ip_address: str = ""
    is_default: bool = False
    is_network: bool = False
    is_shared: bool = False
    work_offline: bool = False
    job_count: Optional[int] = None
    connection_type: str = ""
    status: str = ""


# ── Device ────────────────────────────────────────────────────────────────────
class NetworkCreateIn(BaseModel):
    ip_address: str = ""
    mac_address: str = ""
    hostname: str = ""
    wifi_ssid: str = ""
    connection_type: str = "Ethernet"
    dns_server: str = ""
    dns_servers: str = ""  # alias sent by PS1
    default_gateway: str = ""
    gateway: str = ""      # alias sent by PS1
    interface: str = ""    # alias sent by PS1

class MonitorCreateIn(BaseModel):
    display_index: int = 1
    name: str = ""           # alias from PS1
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    display_size: str = ""
    resolution: str = ""
    refresh_rate: str = ""
    color_depth: str = ""
    connection_type: str = ""
    hdr_support: bool = False
    is_external: bool = True  # alias from PS1


class HardwareInventoryCreateIn(BaseModel):
    processor_model: str = ""
    processor_vendor: str = ""
    physical_cores: Optional[int] = None
    logical_processors: Optional[int] = None
    memory_total_gb: Optional[float] = None
    memory_slot_count: Optional[int] = None
    memory_slots_used: Optional[int] = None
    memory_module_count: Optional[int] = None
    machine_class: str = ""
    chassis_type: str = ""
    gpu_model: str = ""
    gpu_manufacturer: str = ""
    gpu_vram_gb: Optional[float] = None
    gpu_driver_version: str = ""


class PhysicalDiskCreateIn(BaseModel):
    disk_index: Optional[int] = None
    model: str = ""
    serial_number: str = ""
    media_type: str = ""
    interface_type: str = ""
    size_gb: Optional[float] = None


class LogicalDiskCreateIn(BaseModel):
    name: str = ""
    volume_name: str = ""
    file_system: str = ""
    drive_type: str = ""
    size_gb: Optional[float] = None
    free_gb: Optional[float] = None
    used_gb: Optional[float] = None

class DeviceCreate(BaseModel):
    customer_id: str
    device_name: str
    platform: str
    device_type: str = "Desktop"
    model: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    udid: str = ""
    os_version: str = ""
    architecture: str = ""
    owner: str = ""
    enrollment_method: str = "Agent"
    status: str = "Pending"
    agent_version: str = ""
    enrollment_token: Optional[str] = None   # validated on server but not stored as field
    network: Optional[NetworkCreateIn] = None
    monitors: Optional[list[MonitorCreateIn]] = None
    hardware_inventory: Optional[HardwareInventoryCreateIn] = None
    physical_disks: Optional[list[PhysicalDiskCreateIn]] = None
    logical_disks: Optional[list[LogicalDiskCreateIn]] = None
    printers: Optional[list[PrinterCreateIn]] = None

class DeviceListOut(BaseModel):
    id: str
    customer_id: str
    device_name: str
    platform: str
    os_version: str
    owner: str
    enrollment_method: str
    agent_version: str
    status: str
    enrolled_at: Optional[datetime]
    last_checkin: Optional[datetime]
    model_config = {"from_attributes": True}

class DeviceDetailOut(BaseModel):
    id: str
    customer_id: str
    device_name: str
    platform: str
    device_type: str
    model: str
    manufacturer: str
    serial_number: str
    udid: str
    os_version: str
    architecture: str
    shared_device: bool
    owner: str
    enrollment_method: str
    status: str
    enrolled_at: Optional[datetime]
    last_checkin: Optional[datetime]
    agent_version: str
    network: Optional[NetworkInfoOut]
    monitors: list[MonitorInfoOut]
    hardware_inventory: Optional[HardwareInventoryOut]
    physical_disks: list[PhysicalDiskOut]
    logical_disks: list[LogicalDiskOut]
    printers: list[PrinterInfoOut] = []
    customer_name: str
    model_config = {"from_attributes": True}

class DeviceStatusUpdate(BaseModel):
    status: str  # "Enrolled" | "Deprovisioned" | "Failed"


# ── Enrollment Token ──────────────────────────────────────────────────────────
class TokenOut(BaseModel):
    token: str
    customer_id: str
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Proxy Agent / Discovery ───────────────────────────────────────────────────
class AssetInventoryIn(BaseModel):
    processor_model: str = ""
    processor_vendor: str = ""
    processor_count: Optional[int] = None
    physical_cores: Optional[int] = None
    logical_processors: Optional[int] = None
    memory_total_gb: Optional[float] = None
    memory_slot_count: Optional[int] = None
    memory_slots_used: Optional[int] = None
    memory_module_count: Optional[int] = None
    storage_controller_count: Optional[int] = None
    physical_disk_count: Optional[int] = None
    virtual_disk_count: Optional[int] = None
    disk_total_gb: Optional[float] = None
    network_interface_count: Optional[int] = None
    power_supply_count: Optional[int] = None
    raid_summary: str = ""


class AssetInventoryOut(AssetInventoryIn):
    updated_at: datetime
    model_config = {"from_attributes": True}


class AssetComponentIn(BaseModel):
    component_type: str = ""
    name: str = ""
    slot: str = ""
    model: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    capacity_gb: Optional[float] = None
    status: str = ""
    health: str = ""
    extra_json: dict[str, object] = Field(default_factory=dict)


class AssetComponentOut(AssetComponentIn):
    id: int
    model_config = {"from_attributes": True}


class AssetHealthIn(BaseModel):
    overall_status: str = ""
    processor_status: str = ""
    memory_status: str = ""
    storage_status: str = ""
    power_status: str = ""
    network_status: str = ""
    thermal_status: str = ""
    power_state: str = ""
    alert_count: Optional[int] = None
    summary: str = ""


class AssetHealthOut(AssetHealthIn):
    updated_at: datetime
    model_config = {"from_attributes": True}


class AssetAlertIn(BaseModel):
    source: str = ""
    severity: str = ""
    code: str = ""
    message: str = ""
    status: str = "active"
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    cleared_at: Optional[datetime] = None
    extra_json: dict[str, object] = Field(default_factory=dict)


class AssetAlertOut(AssetAlertIn):
    id: int
    model_config = {"from_attributes": True}


class ProxyAgentCreate(BaseModel):
    customer_id: str
    name: str
    site_name: str = ""
    hostname: str = ""
    ip_address: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    auth_token: Optional[str] = None


class ProxyAgentOut(BaseModel):
    id: str
    customer_id: str
    name: str
    site_name: str
    hostname: str
    ip_address: str
    mac_address: str
    portal_url: str
    version: str
    status: str
    is_registered: bool
    capabilities: list[str] = Field(default_factory=list)
    auth_token: str
    last_checkin: Optional[datetime]
    registered_at: Optional[datetime]
    created_at: datetime


class ProxyAgentCommandCreate(BaseModel):
    command_type: str
    payload: dict[str, object] = Field(default_factory=dict)


class ProxyAgentCommandOut(BaseModel):
    id: str
    proxy_agent_id: str
    command_type: str
    payload: dict[str, object] = Field(default_factory=dict)
    status: str
    result: Optional[str] = None
    created_at: datetime
    acked_at: Optional[datetime]


class DiscoveredAssetIn(BaseModel):
    asset_class: str = "network"
    display_name: str = ""
    vendor: str = ""
    model: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    ip_address: str = ""
    management_ip: str = ""
    mac_address: str = ""
    status: str = "Discovered"
    raw_facts: dict[str, object] = Field(default_factory=dict)
    inventory: Optional[AssetInventoryIn] = None
    components: list[AssetComponentIn] = Field(default_factory=list)
    health: Optional[AssetHealthIn] = None
    alerts: list[AssetAlertIn] = Field(default_factory=list)


class DiscoveryAgentHeartbeatIn(BaseModel):
    hostname: str = ""
    ip_address: str = ""
    mac_address: str = ""
    portal_url: str = ""
    version: str = ""
    site_name: str = ""
    capabilities: list[str] = Field(default_factory=list)


class DiscoveryIngestRequest(BaseModel):
    agent_token: str
    agent: Optional[DiscoveryAgentHeartbeatIn] = None
    assets: list[DiscoveredAssetIn] = Field(default_factory=list)


class DiscoveryIngestOut(BaseModel):
    proxy_agent_id: str
    accepted_assets: int
    created_assets: int
    updated_assets: int
    last_checkin: datetime


class DiscoveredAssetOut(BaseModel):
    id: str
    customer_id: str
    proxy_agent_id: Optional[str]
    asset_class: str
    source_type: str
    display_name: str
    vendor: str
    model: str
    serial_number: str
    firmware_version: str
    ip_address: str
    management_ip: str
    mac_address: str
    status: str
    raw_facts: dict[str, object] = Field(default_factory=dict)
    inventory: Optional[AssetInventoryOut] = None
    components: list[AssetComponentOut] = Field(default_factory=list)
    health: Optional[AssetHealthOut] = None
    alerts: list[AssetAlertOut] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: Optional[datetime]
    created_at: datetime
