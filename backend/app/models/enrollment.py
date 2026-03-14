import uuid
from datetime import datetime, timedelta
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column
import enum
from app.db import Base


class EnrollmentPlatform(str, enum.Enum):
    IOS = "ios"
    ANDROID = "android"
    MACOS = "macos"
    WINDOWS = "windows"
    ANY = "any"


class EnrollmentToken(Base):
    """One-time or multi-use enrollment invitation tokens (used for BYOD)"""
    __tablename__ = "enrollment_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_user_email: Mapped[str] = mapped_column(String(255), nullable=True)

    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False,
                                        default=lambda: str(uuid.uuid4()).replace("-", ""))
    platform: Mapped[EnrollmentPlatform] = mapped_column(Enum(EnrollmentPlatform),
                                                           default=EnrollmentPlatform.ANY)
    is_byod: Mapped[bool] = mapped_column(Boolean, default=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    max_uses: Mapped[int] = mapped_column(default=1)
    use_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(days=7)
    )

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_expired and self.use_count < self.max_uses
