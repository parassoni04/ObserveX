from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Organization
from server.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserOut,
)
from server.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(req: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Self-registration endpoint for standard users."""
    # Check if username or email already exists
    stmt = select(User).where(or_(User.email == req.email, User.username == req.username))
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        if existing.email == req.email:
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=400, detail="Username already taken")

    # Get default organization (or create one)
    org_stmt = select(Organization).order_by(Organization.id).limit(1)
    default_org = (await db.execute(org_stmt)).scalar_one_or_none()
    if not default_org:
        default_org = Organization(name="Default Org")
        db.add(default_org)
        await db.commit()
        await db.refresh(default_org)

    hashed = hash_password(req.password)
    user = User(
        email=req.email.lower().strip(),
        username=req.username.strip(),
        full_name=req.full_name,
        hashed_password=hashed,
        role="user",  # Self-registered users default to standard 'user'
        is_active=True,
        organization_id=default_org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
async def login_user(req: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user with username or email & password, returning JWT access token."""
    login_input = req.username_or_email.lower().strip()
    stmt = select(User).where(or_(User.email == login_input, User.username == login_input))
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    token = create_access_token({"sub": str(user.id), "role": user.role, "org_id": user.organization_id})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=user,
    )


@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Return profile of currently authenticated user."""
    return current_user
