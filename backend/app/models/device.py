from __future__ import annotations

import uuid
import enum
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.user import Organization, User
    from app.models.command import MDMCommand
    from app.models.app_catalog import DeviceApp


class DevicePlatform(str, enum.Enum):
    IOS = "ios"
    IPADOS = "ipados"
    MACOS = "macos"
    ANDROID = "android"
    WINDOWS = "windows"


class EnrollmentType(str, enum.Enum):
    DEP = "dep"              # Apple Business Manager / Zero-Touch
    MANUAL = "manual"        # Manual MDM profile install
    USER_ENROLLMENT = "user_enrollment"  # BYOD Apple User Enrollment
    ANDROID_ENTERPRISE = "android_enterprise"  # Full device management
    WORK_PROFILE = "work_profile"            # BYOD Android Work Profile
    AGENT = "agent"          # Windows/Mac agent-based


class DeviceStatus(str, enum.Enum):
    PENDING = "pending"          # Enrolled but not yet checked in
    ENROLLED = "enrolled"        # Active, managed
    SUPERVISED = "supervised"    # iOS supervised mode
    UNENROLLED = "unenrolled"    # Removed from MDM
    WIPED = "wiped"              # Remote wipe issued


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Identifiers
    udid: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)    # Apple UDID
    serial_number: Mapped[str] = mapped_column(String(255), nullable=True)
    android_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    push_token: Mapped[str] = mapped_column(Text, nullable=True)       # APNs / FCM token
    enrollment_token: Mapped[str] = mapped_column(String(255), nullable=True)  # Android enrollment

    # Device info
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str] = mapped_column(String(100), nullable=True)
    platform: Mapped[DevicePlatform] = mapped_column(Enum(DevicePlatform), nullable=False)
    enrollment_type: Mapped[EnrollmentType] = mapped_column(Enum(EnrollmentType), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(Enum(DeviceStatus), default=DeviceStatus.PENDING)
    is_byod: Mapped[bool] = mapped_column(Boolean, default=False)

    # MDM state
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    checked_out: Mapped[bool] = mapped_column(Boolean, default=False)

    # Extra info (battery, storage, etc.)
    device_info: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="devices")
    owner: Mapped["User"] = relationship("User", back_populates="devices")
    commands: Mapped[list["MDMCommand"]] = relationship("MDMCommand", back_populates="device")
    apps: Mapped[list["DeviceApp"]] = relationship("DeviceApp", back_populates="device")
