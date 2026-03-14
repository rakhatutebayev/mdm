from datetime import datetime
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr

from app.db import get_db
from app.models.user import User, Organization, UserRole
from app.auth import verify_password, hash_password, create_access_token, create_refresh_token, decode_token
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    org_name: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    role: UserRole
    org_id: str

    class Config:
        from_attributes = True


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    x_org_id: Optional[str] = Header(default=None),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credentials_exception

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception

    # SUPER_ADMIN org switcher: honour X-Org-ID header
    if x_org_id and user.role == UserRole.SUPER_ADMIN and str(user.org_id) != x_org_id:
        # Verify org exists
        org_result = await db.execute(
            select(Organization).where(Organization.id == x_org_id)
        )
        if org_result.scalar_one_or_none():
            # Return a lightweight proxy with overridden org_id
            user = User(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                org_id=x_org_id,
                is_active=user.is_active,
            )
    return user


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register first admin + create organization."""
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    org = Organization(name=data.org_name)
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access = create_access_token({"sub": user.id, "org": org.id, "role": user.role})
    refresh = create_refresh_token({"sub": user.id})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    user.last_login = datetime.utcnow()
    await db.commit()

    access = create_access_token({"sub": user.id, "org": user.org_id, "role": user.role})
    refresh = create_refresh_token({"sub": user.id})
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(token: str, db: AsyncSession = Depends(get_db)):
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "User not found")

    access = create_access_token({"sub": user.id, "org": user.org_id, "role": user.role})
    new_refresh = create_refresh_token({"sub": user.id})
    return TokenResponse(access_token=access, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Microsoft Entra ID (Azure AD) — optional OAuth2 login
# ---------------------------------------------------------------------------

@router.get("/entra-status")
async def entra_status():
    """Returns whether Microsoft Entra login is configured on this server."""
    s = get_settings()
    return {"enabled": s.entra_enabled}


@router.get("/microsoft")
async def microsoft_login():
    """Redirect user to Microsoft OAuth2 consent screen."""
    s = get_settings()
    if not s.entra_enabled:
        raise HTTPException(status_code=501, detail="Microsoft Entra is not configured on this server")

    try:
        import msal
    except ImportError:
        raise HTTPException(status_code=500, detail="msal package not installed")

    app_msal = msal.ConfidentialClientApplication(
        client_id=s.ENTRA_CLIENT_ID,
        client_credential=s.ENTRA_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{s.ENTRA_TENANT_ID}",
    )
    auth_url = app_msal.get_authorization_request_url(
        scopes=["User.Read"],
        redirect_uri=s.ENTRA_REDIRECT_URI,
    )
    return RedirectResponse(url=auth_url)


@router.get("/microsoft/callback")
async def microsoft_callback(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Exchange Azure OAuth2 code for NOCKO MDM JWT."""
    s = get_settings()
    if not s.entra_enabled:
        raise HTTPException(status_code=501, detail="Microsoft Entra is not configured on this server")

    try:
        import msal
    except ImportError:
        raise HTTPException(status_code=500, detail="msal package not installed")

    app_msal = msal.ConfidentialClientApplication(
        client_id=s.ENTRA_CLIENT_ID,
        client_credential=s.ENTRA_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{s.ENTRA_TENANT_ID}",
    )
    result = app_msal.acquire_token_by_authorization_code(
        code=code,
        scopes=["User.Read"],
        redirect_uri=s.ENTRA_REDIRECT_URI,
    )

    if "error" in result:
        raise HTTPException(
            status_code=400,
            detail=result.get("error_description", "Microsoft OAuth2 error"),
        )

    id_token_claims = result.get("id_token_claims", {})
    ms_email: str = (
        id_token_claims.get("preferred_username")
        or id_token_claims.get("email")
        or ""
    ).lower()
    ms_name: str = id_token_claims.get("name", "")

    if not ms_email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from Microsoft account")

    # Find or create user
    res = await db.execute(select(User).where(User.email == ms_email))
    user = res.scalar_one_or_none()

    if not user:
        # Auto-create user — find or create a default org
        res_org = await db.execute(select(Organization).limit(1))
        org = res_org.scalar_one_or_none()
        if not org:
            org = Organization(id=uuid.uuid4(), name="Default Organization")
            db.add(org)
            await db.flush()

        user = User(
            id=uuid.uuid4(),
            email=ms_email,
            full_name=ms_name,
            hashed_password=hash_password(str(uuid.uuid4())),  # random password, Entra-only login
            role=UserRole.VIEWER,
            org_id=org.id,
            created_at=datetime.utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    access = create_access_token({"sub": str(user.id), "org": str(user.org_id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id)})

    # Redirect to frontend with tokens in query params
    # The frontend's /auth/callback page reads these and stores them in localStorage
    frontend_url = "http://localhost:3002"
    return RedirectResponse(
        url=f"{frontend_url}/auth/callback?access_token={access}&refresh_token={refresh}"
    )
