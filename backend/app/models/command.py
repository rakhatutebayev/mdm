import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Enum, Text, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


class CommandType(str, enum.Enum):
    # Apple MDM commands
    LOCK = "DeviceLock"
    ERASE = "EraseDevice"
    INSTALL_APP = "InstallApplication"
    REMOVE_APP = "RemoveApplication"
    CLEAR_PASSCODE = "ClearPasscode"
    DEVICE_INFO = "DeviceInformation"
    INSTALLED_APPS = "InstalledApplicationList"
    RESTART = "RestartDevice"
    SHUTDOWN = "ShutDownDevice"
    # Android commands
    ANDROID_LOCK = "android_lock"
    ANDROID_WIPE = "android_wipe"
    ANDROID_INSTALL_APP = "android_install_app"
    ANDROID_REMOVE_APP = "android_remove_app"
    ANDROID_RESET_PASSWORD = "android_reset_password"
    # Generic
    CHECKIN = "checkin"


class CommandStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    ERROR = "error"


class MDMCommand(Base):
    __tablename__ = "mdm_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), nullable=False)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=True)

    command_type: Mapped[CommandType] = mapped_column(Enum(CommandType), nullable=False)
    status: Mapped[CommandStatus] = mapped_column(Enum(CommandStatus), default=CommandStatus.QUEUED)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    device: Mapped["Device"] = relationship("Device", back_populates="commands")
