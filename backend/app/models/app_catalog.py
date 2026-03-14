from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

if TYPE_CHECKING:
    from app.models.device import Device


class AppCatalog(Base):
    """Corporate app catalog - apps available for push"""
    __tablename__ = "app_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bundle_id: Mapped[str] = mapped_column(String(255), nullable=False)   # iOS bundle / Android package
    app_store_id: Mapped[str] = mapped_column(String(100), nullable=True)  # Apple App Store ID
    play_store_url: Mapped[str] = mapped_column(String(500), nullable=True)
    icon_url: Mapped[str] = mapped_column(String(500), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=True)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=True)       # Managed distribution
    is_byod_allowed: Mapped[bool] = mapped_column(Boolean, default=False)  # Push to BYOD devices
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeviceApp(Base):
    """Apps installed on a specific device"""
    __tablename__ = "device_apps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), nullable=False)
    bundle_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=True)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    device: Mapped["Device"] = relationship("Device", back_populates="apps")
