from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "NOCKO MDM"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://mdm:mdm_secret@localhost:5432/nocko_mdm"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # Apple MDM
    APPLE_PUSH_CERT_PATH: Optional[str] = None
    APPLE_PUSH_KEY_PATH: Optional[str] = None
    APPLE_MDM_TOPIC: Optional[str] = None
    APPLE_DEP_TOKEN_PATH: Optional[str] = None
    APPLE_DEP_SERVER_TOKEN_PATH: Optional[str] = None
    MDM_SERVER_URL: str = "https://mdm.it-uae.com"
    ENROLLMENT_URL: str = "https://mdm.it-uae.com/api/v1/enrollment"

    # Android EMM
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    ANDROID_ENTERPRISE_ID: Optional[str] = None

    # Microsoft Entra ID (Azure AD) — optional, leave blank to disable
    ENTRA_CLIENT_ID: Optional[str] = None
    ENTRA_CLIENT_SECRET: Optional[str] = None
    ENTRA_TENANT_ID: Optional[str] = None
    ENTRA_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/microsoft/callback"

    @property
    def entra_enabled(self) -> bool:
        return bool(self.ENTRA_CLIENT_ID and self.ENTRA_CLIENT_SECRET and self.ENTRA_TENANT_ID)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
