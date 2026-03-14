"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import customers, devices, enrollment
from routers.packages import router as packages_router
from routers.dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


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


@app.get("/health")
async def health():
    return {"status": "ok"}
