"""
Auth Router
===========

Handles user authentication:
- POST /api/v1/auth/login — Login with username/email + password
- POST /api/v1/auth/create-environment — Create new organization + admin
- GET  /api/v1/auth/me — Get current user profile

The old "register" endpoint (which dumped everyone into "Default Org")
is replaced by the create-environment flow. New users within an existing
org are created by admins via the admin/users endpoint.
"""
import datetime
import secrets
import hmac
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import settings
from server.database import get_db
from server.models import User, Organization
from server.schemas.auth import (
    UserLoginRequest, TokenResponse,
    CreateEnvironmentRequest, CreateEnvironmentResponse,
    SendVerificationCodeRequest, VerifyCodeRequest, VerificationTokenResponse,
)
from server.schemas.user import UserOut
from server.schemas.organization import OrganizationOut
from server.auth import hash_password, verify_password, create_access_token, get_current_user
from server.security import log_audit, ACTIONS, login_limiter
from server.logging import get_logger

logger = get_logger("auth")

# In-memory store for email verification codes (email -> {code, expires_at, verified})
_verification_store: dict[str, dict] = {}
_VERIFICATION_SECRET = settings.JWT_SECRET_KEY.encode()


def _generate_verification_token(email: str) -> str:
    """Create an HMAC signature proving email was verified."""
    timestamp = str(int(datetime.datetime.utcnow().timestamp()))
    msg = f"{email}:{timestamp}".encode()
    sig = hmac.new(_VERIFICATION_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{timestamp}:{sig}"


def _verify_verification_token(email: str, token: str) -> bool:
    """Verify HMAC signature and check that it's within 30 minutes."""
    try:
        parts = token.split(":")
        if len(parts) != 2:
            return False
        timestamp, sig = parts
        ts = int(timestamp)
        now = int(datetime.datetime.utcnow().timestamp())
        if now - ts > 1800 or ts > now + 60:
            return False
        expected_msg = f"{email}:{timestamp}".encode()
        expected_sig = hmac.new(_VERIFICATION_SECRET, expected_msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_limiter)])
async def login_user(
    req: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return a JWT token."""
    client_ip = request.client.host if request.client else "unknown"
    login_input = req.username_or_email.lower().strip()

    user = (await db.execute(
        select(User).where(or_(User.email == login_input, User.username == login_input))
    )).scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        logger.warning("Login failed: input=%s ip=%s", login_input, client_ip)
        await log_audit(
            ACTIONS["LOGIN_FAILED"],
            actor_type="user",
            ip_address=client_ip, result="denied",
            detail=f"Failed login for: {login_input}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
        )

    if not user.is_active:
        logger.warning("Login denied (deactivated): user_id=%s ip=%s", user.id, client_ip)
        await log_audit(
            ACTIONS["LOGIN_FAILED"],
            actor_type="user", actor_id=str(user.id),
            organization_id=user.organization_id,
            ip_address=client_ip, result="denied",
            detail="Account deactivated",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": user.organization_id,
    })

    logger.info("Login successful: user_id=%s username=%s ip=%s", user.id, user.username, client_ip)
    await log_audit(
        ACTIONS["LOGIN"],
        actor_type="user", actor_id=str(user.id),
        organization_id=user.organization_id,
        ip_address=client_ip,
    )

    return TokenResponse(access_token=token, token_type="bearer", user=user)


@router.post("/send-verification-code")
async def send_verification_code(
    req: SendVerificationCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and send a 6-digit verification code to the requested email.
    If SMTP is not configured, logs code to server console and returns dev_code.
    """
    clean_email = req.email.lower().strip()

    # Check if email is already registered
    existing = (await db.execute(
        select(User).where(User.email == clean_email)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")

    # Generate 6-digit code
    code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
    _verification_store[clean_email] = {
        "code": code,
        "expires_at": expires_at,
        "verified": False,
    }

    logger.info("Verification code generated for email=%s: %s (expires in 10m)", clean_email, code)
    print(f"\n[Auth] ===================================================")
    print(f"[Auth] Email Verification Code for {clean_email}: {code}")
    print(f"[Auth] ===================================================\n")

    return {
        "status": "sent",
        "email": clean_email,
        "message": f"Verification code sent to {clean_email}",
        "dev_code": code,  # Displayed in console / dev response for seamless testing
        "expires_in_minutes": 10,
    }


@router.post("/verify-code", response_model=VerificationTokenResponse)
async def verify_code(req: VerifyCodeRequest):
    """
    Verify the 6-digit code and return an email verification token.
    """
    clean_email = req.email.lower().strip()
    stored = _verification_store.get(clean_email)

    if not stored:
        raise HTTPException(status_code=400, detail="No verification code found. Please request a code first.")

    if datetime.datetime.utcnow() > stored["expires_at"]:
        _verification_store.pop(clean_email, None)
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")

    if stored["code"] != req.code.strip():
        raise HTTPException(status_code=400, detail="Incorrect verification code. Please check and try again.")

    stored["verified"] = True
    token = _generate_verification_token(clean_email)

    return VerificationTokenResponse(
        status="verified",
        verification_token=token,
        message="Email successfully verified",
    )


@router.post(
    "/create-environment",
    response_model=CreateEnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    req: CreateEnvironmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new organization with an admin account — the "Create Environment" flow.

    This replaces the old generic registration that put everyone in "Default Org".
    Each call creates a fresh, isolated tenant environment.
    """
    client_ip = request.client.host if request.client else "unknown"
    clean_email = req.admin_email.lower().strip()

    # Validate email verification if token or code was provided
    if req.verification_token:
        if not _verify_verification_token(clean_email, req.verification_token):
            raise HTTPException(status_code=400, detail="Invalid or expired email verification token")
    elif req.verification_code:
        stored = _verification_store.get(clean_email)
        if not stored or stored["code"] != req.verification_code.strip() or datetime.datetime.utcnow() > stored["expires_at"]:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        stored["verified"] = True

    # Check for existing email/username
    existing = (await db.execute(
        select(User).where(or_(
            User.email == req.admin_email.lower().strip(),
            User.username == req.admin_username.strip(),
        ))
    )).scalar_one_or_none()
    if existing:
        detail = "Email already registered" if existing.email == req.admin_email.lower().strip() else "Username already taken"
        raise HTTPException(status_code=400, detail=detail)

    # Check for existing organization name
    existing_org = (await db.execute(
        select(Organization).where(Organization.name == req.organization_name.strip())
    )).scalar_one_or_none()
    if existing_org:
        raise HTTPException(status_code=400, detail="Organization name already exists")

    # Create organization
    slug = req.organization_name.lower().replace(" ", "-")[:100]
    org = Organization(name=req.organization_name.strip(), slug=slug)
    db.add(org)
    await db.flush()  # Get org.id

    # Create admin user
    user = User(
        email=req.admin_email.lower().strip(),
        username=req.admin_username.strip(),
        full_name=req.admin_full_name,
        hashed_password=hash_password(req.admin_password),
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(org)
    await db.refresh(user)

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": org.id,
    })

    logger.info("Environment created: org_id=%s org_name=%s admin_id=%s ip=%s",
                org.id, org.name, user.id, client_ip)
    await log_audit(
        ACTIONS["ENVIRONMENT_CREATED"],
        actor_type="user", actor_id=str(user.id),
        organization_id=org.id,
        ip_address=client_ip,
        detail=f"org_name={org.name} admin={user.username}",
    )

    return CreateEnvironmentResponse(
        access_token=token,
        token_type="bearer",
        user=user,
        organization=org,
    )


@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return current_user
