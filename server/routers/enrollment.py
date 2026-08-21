"""
ObserveX Server — Enrollment Code Management.

Admin-only endpoints for generating, listing, and revoking
enrollment codes that agents use for first-time registration.
"""
import datetime
import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import EnrollmentCode, Device, User
from server.schemas import (
    EnrollmentCodeCreateRequest, EnrollmentCodeOut,
    EnrollmentRequest, EnrollmentResponse,
)
from server.authorization import require_admin

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


def _generate_code() -> str:
    """Generate a human-friendly enrollment code like OX-7F29-A82D."""
    part1 = secrets.token_hex(2).upper()
    part2 = secrets.token_hex(2).upper()
    return f"OX-{part1}-{part2}"


# ── Admin endpoints ──

@router.post("/codes", response_model=EnrollmentCodeOut, status_code=status.HTTP_201_CREATED)
async def create_enrollment_code(
    req: EnrollmentCodeCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Generate a new enrollment code (admin only)."""
    code = _generate_code()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=req.expires_in_hours)

    enrollment_code = EnrollmentCode(
        code=code,
        organization_id=req.organization_id or admin_user.organization_id,
        created_by_user_id=admin_user.id,
        expires_at=expires_at,
        max_uses=req.max_uses,
    )
    db.add(enrollment_code)
    await db.commit()
    await db.refresh(enrollment_code)
    return enrollment_code


@router.get("/codes", response_model=list[EnrollmentCodeOut])
async def list_enrollment_codes(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List all enrollment codes (admin only)."""
    result = await db.execute(
        select(EnrollmentCode).order_by(EnrollmentCode.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/codes/{code_id}")
async def revoke_enrollment_code(
    code_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Revoke an enrollment code (admin only)."""
    code_obj = await db.get(EnrollmentCode, code_id)
    if not code_obj:
        raise HTTPException(status_code=404, detail="Enrollment code not found")
    code_obj.is_revoked = True
    await db.commit()
    return {"status": "revoked", "code_id": code_id}


# ── Agent enrollment endpoint ──

@router.post("/enroll", response_model=EnrollmentResponse)
async def enroll_agent(
    req: EnrollmentRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Agent enrollment endpoint. Validates an enrollment code,
    creates a device record, and returns credentials.

    This is also mounted at /api/v1/agent/enroll for convenience.
    """
    # Find the enrollment code
    result = await db.execute(
        select(EnrollmentCode).where(EnrollmentCode.code == req.enrollment_code)
    )
    code_obj = result.scalar_one_or_none()

    if not code_obj:
        raise HTTPException(status_code=404, detail="Invalid enrollment code")

    if code_obj.is_revoked:
        raise HTTPException(status_code=410, detail="Enrollment code has been revoked")

    if code_obj.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=410, detail="Enrollment code has expired")

    if code_obj.max_uses > 0 and code_obj.usage_count >= code_obj.max_uses:
        raise HTTPException(status_code=410, detail="Enrollment code has reached maximum uses")

    # Generate device credentials
    device_uuid = str(uuid.uuid4())
    raw_api_key = secrets.token_urlsafe(32)
    api_key_hash = bcrypt.hashpw(raw_api_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # Create the device
    device = Device(
        device_uuid=device_uuid,
        hostname=req.hostname,
        os_name=req.os_name,
        os_version=req.os_version,
        api_key_hash=api_key_hash,
        api_key=raw_api_key,  # Legacy column — will be removed after migration
        status="active",
        organization_id=code_obj.organization_id,
        registered_at=datetime.datetime.utcnow(),
        last_seen=datetime.datetime.utcnow(),
        is_online=False,
    )
    db.add(device)

    # Update enrollment code usage
    code_obj.usage_count += 1
    await db.commit()
    await db.refresh(device)

    print(f"[Enrollment] Device enrolled: id={device.id}, uuid={device_uuid}, hostname={req.hostname}")

    return EnrollmentResponse(
        device_id=device.id,
        device_uuid=device_uuid,
        api_key=raw_api_key,
        status="enrolled",
    )
