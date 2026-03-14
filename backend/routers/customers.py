"""Customers router."""
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Customer
from schemas import CustomerCreate, CustomerOut

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.get("", response_model=list[CustomerOut])
async def list_customers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Customer).order_by(Customer.name))
    return result.scalars().all()


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(body: CustomerCreate, db: AsyncSession = Depends(get_db)):
    slug = body.slug or slugify(body.name)
    customer = Customer(name=body.name, slug=slug)
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(customer_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.delete(customer)
    await db.commit()
