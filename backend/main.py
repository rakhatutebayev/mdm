"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import customers, devices, enrollment, discovery
from routers.packages import router as packages_router
from routers.dashboard import router as dashboard_router
from routers.mdm import router as mdm_router
from routers.settings import router as settings_router
from mqtt_publisher import MqttPublisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Inline schema migrations for new columns on existing tables
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE monitor_info ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(255) DEFAULT ''"
            )
        )
        # GPU info columns on hardware_inventory
        for col_ddl in [
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_model VARCHAR(255) DEFAULT ''",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_manufacturer VARCHAR(100) DEFAULT ''",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_vram_gb FLOAT",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_driver_version VARCHAR(100) DEFAULT ''",
        ]:
            await conn.execute(__import__("sqlalchemy").text(col_ddl))
        # printer_info — new columns added for CimInstance fields
        for col_ddl in [
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45) DEFAULT ''",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS work_offline BOOLEAN DEFAULT FALSE",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS job_count INTEGER",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS connection_type VARCHAR(50) DEFAULT ''",
        ]:
            await conn.execute(__import__("sqlalchemy").text(col_ddl))

        # proxy_agents — registration lifecycle and self-reported portal metadata
        for col_ddl in [
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS mac_address VARCHAR(17) DEFAULT ''",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS portal_url VARCHAR(255) DEFAULT ''",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS is_registered BOOLEAN DEFAULT FALSE",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP NULL",
        ]:
            await conn.execute(__import__("sqlalchemy").text(col_ddl))

    # Start MQTT publisher (non-blocking background task)
    await MqttPublisher.connect()
    yield
    await MqttPublisher.disconnect()


app = FastAPI(
    title="NOCKO MDM API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router)
app.include_router(devices.router)
app.include_router(enrollment.router)
app.include_router(discovery.router)
app.include_router(packages_router)
app.include_router(dashboard_router)
app.include_router(mdm_router)
app.include_router(settings_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
