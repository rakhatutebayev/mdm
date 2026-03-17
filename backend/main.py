"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import customers, devices, enrollment
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
        # printer_info table (created via create_all above, explicit fallback)
        await conn.execute(__import__("sqlalchemy").text("""
            CREATE TABLE IF NOT EXISTS printer_info (
                id SERIAL PRIMARY KEY,
                device_id VARCHAR(36) REFERENCES devices(id) ON DELETE CASCADE,
                name VARCHAR(255) DEFAULT '',
                driver_name VARCHAR(255) DEFAULT '',
                port_name VARCHAR(255) DEFAULT '',
                is_default BOOLEAN DEFAULT FALSE,
                is_network BOOLEAN DEFAULT FALSE,
                status VARCHAR(100) DEFAULT ''
            )
        """))
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
app.include_router(packages_router)
app.include_router(dashboard_router)
app.include_router(mdm_router)
app.include_router(settings_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
