"""FastAPI application entry point."""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from database import engine, Base, AsyncSessionLocal
from routers import customers, devices, enrollment, discovery
from routers.packages import router as packages_router, download_router as packages_download_router
from routers.dashboard import router as dashboard_router
from routers.mdm import router as mdm_router
from routers.settings import router as settings_router
from routers.agent_router import router as agent_router
from routers.agent_portal import router as agent_portal_router
from routers.auth import router as auth_router
from mqtt_publisher import MqttPublisher
from mqtt_consumer import get_consumer
from auth import get_current_user
import agent_models  # ensure models are registered with Base



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist
    # This includes agent_models tables since agent_models.py is imported above
    # and registers all new Zabbix-style tables with the same Base.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Inline schema migrations for new columns on existing tables
        await conn.execute(text(
            "ALTER TABLE monitor_info ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(255) DEFAULT ''"
        ))
        # GPU info columns on hardware_inventory
        for col_ddl in [
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_model VARCHAR(255) DEFAULT ''",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_manufacturer VARCHAR(100) DEFAULT ''",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_vram_gb FLOAT",
            "ALTER TABLE hardware_inventory ADD COLUMN IF NOT EXISTS gpu_driver_version VARCHAR(100) DEFAULT ''",
        ]:
            await conn.execute(text(col_ddl))
        # printer_info — new columns added for CimInstance fields
        for col_ddl in [
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45) DEFAULT ''",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS work_offline BOOLEAN DEFAULT FALSE",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS job_count INTEGER",
            "ALTER TABLE printer_info ADD COLUMN IF NOT EXISTS connection_type VARCHAR(50) DEFAULT ''",
        ]:
            await conn.execute(text(col_ddl))

        # proxy_agents — registration lifecycle and self-reported portal metadata
        for col_ddl in [
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS mac_address VARCHAR(17) DEFAULT ''",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS portal_url VARCHAR(255) DEFAULT ''",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS is_registered BOOLEAN DEFAULT FALSE",
            "ALTER TABLE proxy_agents ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP NULL",
        ]:
            await conn.execute(text(col_ddl))

        # users — portal auth (created by Base.metadata.create_all above, migration for existing DBs)
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP NULL"
        ))

    # Start MQTT publisher (non-blocking background task)
    await MqttPublisher.connect()

    # Start MQTT ingest consumer (proxy agent data plane)
    consumer = get_consumer(AsyncSessionLocal)
    consumer.start()

    # Start trends aggregator (hourly rollup)
    from trends_aggregator import get_aggregator
    aggregator = get_aggregator(AsyncSessionLocal)
    agg_task = asyncio.create_task(aggregator.run_forever())

    yield

    agg_task.cancel()
    consumer.stop()
    await MqttPublisher.disconnect()




app = FastAPI(
    title="NOCKO MDM API",
    version="1.0.0",
    lifespan=lifespan,
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=bool(_raw_origins),
)

app.include_router(auth_router)          # Public: login/me

# Portal routes — all require a valid JWT
_portal_dep = [Depends(get_current_user)]
app.include_router(customers.router,      dependencies=_portal_dep)
app.include_router(devices.router,        dependencies=_portal_dep)
app.include_router(enrollment.router,     dependencies=_portal_dep)
app.include_router(discovery.router,      dependencies=_portal_dep)
app.include_router(packages_router,       dependencies=_portal_dep)
app.include_router(dashboard_router,      dependencies=_portal_dep)
app.include_router(settings_router,       dependencies=_portal_dep)
app.include_router(agent_portal_router,   dependencies=_portal_dep)

# Agent-facing routes — authenticated by enrollment token / agent token (no JWT)
app.include_router(mdm_router)
app.include_router(agent_router)
app.include_router(packages_download_router)  # Public: JWT validated via ?t= query param



@app.get("/health")
async def health():
    return {"status": "ok"}
