"""
FastAPI main application entry point for NOCKO MDM.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import auth, devices, apps, enrollment, users
from app.routers import mdm_apple, mdm_android, mdm_windows
from app.routers import windows_enrollment, organizations
from app.routers import agent_packages

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables
    await init_db()
    print(f"✅ NOCKO MDM server started — {settings.APP_NAME} v{settings.APP_VERSION}")
    yield
    print("👋 NOCKO MDM server shutting down")


app = FastAPI(
    title="NOCKO MDM API",
    description="Mobile Device Management API for Apple, Android, Windows, and macOS devices",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS — restrict in production to your frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:8000",
        "https://mdm.it-uae.com",
        "https://mdm.nocko.ae",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(organizations.router, prefix=API_PREFIX)
app.include_router(devices.router, prefix=API_PREFIX)
app.include_router(apps.router, prefix=API_PREFIX)
app.include_router(enrollment.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(mdm_apple.router, prefix=API_PREFIX)
app.include_router(mdm_android.router, prefix=API_PREFIX)
app.include_router(mdm_windows.router, prefix=API_PREFIX)
app.include_router(windows_enrollment.router)  # has /api/v1/... and /EnrollmentServer/... paths built-in
app.include_router(agent_packages.router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "NOCKO MDM", "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
    }
