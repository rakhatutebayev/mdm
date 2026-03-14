"""
Seed script — creates the default admin user in the database.
Run AFTER docker-compose is up and the database is initialized.

Usage:
    cd backend
    python seed_admin.py

Or inside the container:
    docker exec -it nocko-mdm-backend python seed_admin.py
"""
import asyncio
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(__file__))

# Import ALL models first so SQLAlchemy can resolve all relationships
# (Organization.devices → Device, User.devices → Device, etc.)
import app.models.device      # noqa: F401
import app.models.enrollment  # noqa: F401
import app.models.command     # noqa: F401
import app.models.app_catalog # noqa: F401

from app.db import AsyncSessionLocal, init_db
from app.models.user import User, Organization, UserRole
from app.auth import hash_password
from sqlalchemy import select


ADMIN_EMAIL = "admin@nocko.ae"
ADMIN_PASSWORD = "Admin@MDM2024"
ADMIN_FULL_NAME = "NOCKO Admin"
ORG_NAME = "NOCKO IT"


async def seed():
    await init_db()

    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"✅ Admin already exists: {ADMIN_EMAIL}")
            return

        # Create organization
        org = Organization(name=ORG_NAME, domain="nocko.ae")
        db.add(org)
        await db.flush()

        # Create admin user
        admin = User(
            org_id=org.id,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_FULL_NAME,
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        await db.commit()

    print("=" * 50)
    print("✅ Admin user created successfully!")
    print(f"   Email:    {ADMIN_EMAIL}")
    print(f"   Password: {ADMIN_PASSWORD}")
    print(f"   Role:     ADMIN")
    print(f"   Org:      {ORG_NAME}")
    print("=" * 50)
    print("\n📌 Login at: http://localhost:3000/login")
    print("📌 API docs: http://localhost:8000/api/docs")


if __name__ == "__main__":
    asyncio.run(seed())
