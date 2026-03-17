"""Pydantic schemas for NOCKO MDM API."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


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
