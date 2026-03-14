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
    model: str
    serial_number: str
    display_size: str
    resolution: str
    refresh_rate: str
    color_depth: str
    connection_type: str
    hdr_support: bool
    model_config = {"from_attributes": True}


# ── Device ────────────────────────────────────────────────────────────────────
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

class DeviceListOut(BaseModel):
    id: str
    customer_id: str
    device_name: str
    platform: str
    owner: str
    enrollment_method: str
    status: str
    enrolled_at: Optional[datetime]
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
