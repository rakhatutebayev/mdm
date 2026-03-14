"""Enrollment tokens router."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import EnrollmentToken, Customer
from schemas import TokenOut

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


def _new_token() -> str:
    return "enroll-" + secrets.token_urlsafe(8).upper()


async def _resolve_customer(customer_id: str, db: AsyncSession) -> Customer:
    result = await db.execute(
        select(Customer).where(
            (Customer.id == customer_id) | (Customer.slug == customer_id)
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.get("/token", response_model=TokenOut)
async def get_token(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Return the active (non-revoked) token for a customer; auto-creates one if none exists."""
    customer = await _resolve_customer(customer_id, db)

    result = await db.execute(
        select(EnrollmentToken)
        .where(EnrollmentToken.customer_id == customer.id, EnrollmentToken.revoked == False)  # noqa: E712
        .order_by(EnrollmentToken.created_at.desc())
        .limit(1)
    )
    token = result.scalar_one_or_none()

    if not token:
        token = EnrollmentToken(customer_id=customer.id, token=_new_token())
        db.add(token)
        await db.commit()
        await db.refresh(token)

    return TokenOut(token=token.token, customer_id=customer.id, created_at=token.created_at)


@router.post("/token/{customer_id}/regenerate", response_model=TokenOut)
async def regenerate_token(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Revoke all existing tokens for the customer and issue a fresh one."""
    customer = await _resolve_customer(customer_id, db)

    # Revoke old tokens
    result = await db.execute(
        select(EnrollmentToken)
        .where(EnrollmentToken.customer_id == customer.id, EnrollmentToken.revoked == False)  # noqa: E712
    )
    for old in result.scalars().all():
        old.revoked = True

    # Create new
    new_token = EnrollmentToken(customer_id=customer.id, token=_new_token())
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)

    return TokenOut(token=new_token.token, customer_id=customer.id, created_at=new_token.created_at)
