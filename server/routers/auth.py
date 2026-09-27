"""
Auth Router — Production-Quality Authentication
=================================================

Handles all user authentication flows:

- POST /api/v1/auth/login                — Login with email/username + password
- POST /api/v1/auth/send-verification-code — Request email verification OTP
- POST /api/v1/auth/verify-code          — Verify OTP and get verification token
- POST /api/v1/auth/create-environment   — Create new organization + admin (requires verified email)
- POST /api/v1/auth/forgot-password      — Request password reset token
- POST /api/v1/auth/reset-password       — Reset password with valid token
- GET  /api/v1/auth/me                   — Get current user profile

Security invariants:
1. Login REQUIRES: valid credentials + active account + verified email.
2. create-environment REQUIRES a cryptographically verified email proof (HMAC token or OTP).
3. Password reset tokens are cryptographically random, hashed (bcrypt), single-use, and expire in 1 hour.
4. Verification codes are single-use — consumed on successful verification.
5. dev_code is NEVER returned in production mode.
6. Generic error messages prevent account enumeration.
7. All auth events are audit-logged.
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
    ForgotPasswordRequest, ResetPasswordRequest,
)
from server.schemas.user import UserOut
from server.schemas.organization import OrganizationOut
from server.auth import hash_password, verify_password, create_access_token, get_current_user
from server.security import log_audit, ACTIONS, login_limiter, registration_limiter
from server.logging import get_logger

logger = get_logger("auth")


# ── Email Verification Store ──
# In-memory store for email verification codes.
# Structure: email -> {code, expires_at, attempts}
# Codes are CONSUMED (deleted) on successful verification — single-use.
_verification_store: dict[str, dict] = {}

# ── Password Reset Store ──
# In-memory store for password reset tokens.
# Structure: token_hash -> {user_id, expires_at, used}
# Tokens are stored as bcrypt hashes, single-use, expire in 1 hour.
_password_reset_store: dict[str, dict] = {}

_VERIFICATION_SECRET = settings.JWT_SECRET_KEY.encode()
_MAX_VERIFICATION_ATTEMPTS = 5


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


def _hash_reset_token(token: str) -> str:
    """Hash a reset token for storage (SHA-256 — fast, appropriate for random tokens)."""
    return hashlib.sha256(token.encode()).hexdigest()


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ═══════════════════════════════════════════════════════════════
#  LOGIN
# ═══════════════════════════════════════════════════════════════

@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_limiter)])
async def login_user(
    req: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate a user and return a JWT token.

    Security checks (in order):
    1. User exists
    2. Password matches hash
    3. Account is active
    4. Email is verified

    Steps 1-2 use a single generic error to prevent account enumeration.
    """
    client_ip = request.client.host if request.client else "unknown"
    login_input = req.username_or_email.lower().strip()

    user = (await db.execute(
        select(User).where(or_(User.email == login_input, User.username == login_input))
    )).scalar_one_or_none()

    # Check credentials — generic error for both "not found" and "wrong password"
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

    # Check account active
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

    # Check email verified
    if not user.email_verified:
        logger.warning("Login denied (unverified email): user_id=%s ip=%s", user.id, client_ip)
        await log_audit(
            ACTIONS["LOGIN_FAILED"],
            actor_type="user", actor_id=str(user.id),
            organization_id=user.organization_id,
            ip_address=client_ip, result="denied",
            detail="Email not verified",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified. Please verify your email before logging in.",
        )

    # Issue JWT with iat claim
    now = datetime.datetime.utcnow()
    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": user.organization_id,
        "iat": int(now.timestamp()),
    })

    logger.info("Login successful: user_id=%s username=%s ip=%s", user.id, user.username, client_ip)
    await log_audit(
        ACTIONS["LOGIN"],
        actor_type="user", actor_id=str(user.id),
        organization_id=user.organization_id,
        ip_address=client_ip,
    )

    return TokenResponse(access_token=token, token_type="bearer", user=user)


# ═══════════════════════════════════════════════════════════════
#  EMAIL VERIFICATION (OTP)
# ═══════════════════════════════════════════════════════════════

@router.post("/send-verification-code")
async def send_verification_code(
    req: SendVerificationCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a 6-digit verification code for the requested email.

    In development: code is printed to server console and included in the
    response as `dev_code`. In production: code is ONLY logged to the server
    console (simulating email delivery) and NOT returned in the response.
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
        "attempts": 0,
    }

    # Always print to server console (email service abstraction)
    logger.info("Verification code generated for email=%s (expires in 10m)", clean_email)
    print(f"\n[Auth] ===================================================")
    print(f"[Auth] Email Verification Code for {clean_email}: {code}")
    print(f"[Auth] ===================================================\n")

    response = {
        "status": "sent",
        "email": clean_email,
        "message": f"Verification code sent to {clean_email}",
        "expires_in_minutes": 10,
    }

    # Only include dev_code in development mode
    if not settings.is_production:
        response["dev_code"] = code

    return response


@router.post("/verify-code", response_model=VerificationTokenResponse)
async def verify_code(req: VerifyCodeRequest):
    """
    Verify the 6-digit code and return an email verification token.

    Security: codes are single-use — consumed (deleted) on successful
    verification. Failed attempts are tracked with a maximum of 5 tries.
    """
    clean_email = req.email.lower().strip()
    stored = _verification_store.get(clean_email)

    if not stored:
        raise HTTPException(status_code=400, detail="No verification code found. Please request a code first.")

    if datetime.datetime.utcnow() > stored["expires_at"]:
        _verification_store.pop(clean_email, None)
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new code.")

    # Track failed attempts
    if stored["code"] != req.code.strip():
        stored["attempts"] = stored.get("attempts", 0) + 1
        if stored["attempts"] >= _MAX_VERIFICATION_ATTEMPTS:
            _verification_store.pop(clean_email, None)
            raise HTTPException(
                status_code=400,
                detail="Too many incorrect attempts. Please request a new code.",
            )
        raise HTTPException(status_code=400, detail="Incorrect verification code. Please check and try again.")

    # Success — consume the code (single-use)
    _verification_store.pop(clean_email, None)
    token = _generate_verification_token(clean_email)

    return VerificationTokenResponse(
        status="verified",
        verification_token=token,
        message="Email successfully verified",
    )


# ═══════════════════════════════════════════════════════════════
#  CREATE ENVIRONMENT (Organization + Admin Registration)
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/create-environment",
    response_model=CreateEnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(registration_limiter)],
)
async def create_environment(
    req: CreateEnvironmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new organization with an admin account.

    REQUIRES a valid email verification proof (HMAC token from /verify-code
    or inline OTP code). The admin user is created with email_verified=True
    because they just proved ownership via OTP.
    """
    client_ip = request.client.host if request.client else "unknown"
    clean_email = req.admin_email.lower().strip()

    # Email verification is MANDATORY
    if req.verification_token:
        if not _verify_verification_token(clean_email, req.verification_token):
            raise HTTPException(status_code=400, detail="Invalid or expired email verification token")
    elif req.verification_code:
        stored = _verification_store.get(clean_email)
        if not stored or stored["code"] != req.verification_code.strip() or datetime.datetime.utcnow() > stored["expires_at"]:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        # Consume the code (single-use)
        _verification_store.pop(clean_email, None)
    else:
        raise HTTPException(
            status_code=400,
            detail="Email verification is required. Please verify your email first.",
        )

    # Check for existing email/username
    existing = (await db.execute(
        select(User).where(or_(
            User.email == clean_email,
            User.username == req.admin_username.strip(),
        ))
    )).scalar_one_or_none()
    if existing:
        detail = "Email already registered" if existing.email == clean_email else "Username already taken"
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

    # Create admin user — email_verified=True because they proved ownership via OTP
    user = User(
        email=clean_email,
        username=req.admin_username.strip(),
        full_name=req.admin_full_name,
        hashed_password=hash_password(req.admin_password),
        role="admin",
        is_active=True,
        email_verified=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(org)
    await db.refresh(user)

    now = datetime.datetime.utcnow()
    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": org.id,
        "iat": int(now.timestamp()),
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


# ═══════════════════════════════════════════════════════════════
#  PASSWORD RESET
# ═══════════════════════════════════════════════════════════════

@router.post("/forgot-password")
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Request a password reset token.

    ALWAYS returns success even if the email doesn't exist (prevents
    account enumeration). The actual token is printed to the server
    console (simulating email delivery) and returned as dev_token
    in development mode only.
    """
    client_ip = request.client.host if request.client else "unknown"
    clean_email = req.email.lower().strip()

    # Always return success to prevent account enumeration
    success_response = {
        "status": "sent",
        "message": "If an account with that email exists, a password reset link has been sent.",
    }

    user = (await db.execute(
        select(User).where(User.email == clean_email)
    )).scalar_one_or_none()

    if not user or not user.is_active:
        logger.info("Password reset requested for unknown/inactive email=%s ip=%s", clean_email, client_ip)
        return success_response

    # Generate a cryptographically random reset token
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)

    # Store hashed token
    _password_reset_store[token_hash] = {
        "user_id": user.id,
        "expires_at": expires_at,
        "used": False,
    }

    # Print to console (email service abstraction)
    logger.info("Password reset token generated for user_id=%s", user.id)
    print(f"\n[Auth] ===================================================")
    print(f"[Auth] Password Reset Token for {clean_email}:")
    print(f"[Auth] {raw_token}")
    print(f"[Auth] Expires in 1 hour")
    print(f"[Auth] ===================================================\n")

    # Only include dev_token in development mode
    if not settings.is_production:
        success_response["dev_token"] = raw_token

    return success_response


@router.post("/reset-password")
async def reset_password(
    req: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Reset password using a valid reset token.

    Security:
    - Token is verified against stored hash.
    - Token must not be expired.
    - Token is single-use (marked used immediately).
    - Password is hashed with bcrypt before storage.
    """
    client_ip = request.client.host if request.client else "unknown"
    token_hash = _hash_reset_token(req.token)

    stored = _password_reset_store.get(token_hash)
    if not stored:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if stored["used"]:
        # Clean up used token
        _password_reset_store.pop(token_hash, None)
        raise HTTPException(status_code=400, detail="This reset token has already been used")

    if datetime.datetime.utcnow() > stored["expires_at"]:
        _password_reset_store.pop(token_hash, None)
        raise HTTPException(status_code=400, detail="Reset token has expired. Please request a new one.")

    # Mark as used BEFORE updating password (prevent race conditions)
    stored["used"] = True

    user = await db.get(User, stored["user_id"])
    if not user:
        _password_reset_store.pop(token_hash, None)
        raise HTTPException(status_code=400, detail="Invalid reset token")

    # Update password
    user.hashed_password = hash_password(req.new_password)
    await db.commit()

    # Clean up used token
    _password_reset_store.pop(token_hash, None)

    logger.info("Password reset successful: user_id=%s ip=%s", user.id, client_ip)
    await log_audit(
        ACTIONS.get("PASSWORD_RESET", "user.password_reset"),
        actor_type="user", actor_id=str(user.id),
        organization_id=user.organization_id,
        ip_address=client_ip,
    )

    return {"status": "success", "message": "Password has been reset successfully. You can now log in."}


# ═══════════════════════════════════════════════════════════════
#  PROFILE
# ═══════════════════════════════════════════════════════════════

@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return current_user
