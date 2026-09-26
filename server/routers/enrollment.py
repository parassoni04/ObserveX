"""
Enrollment Router
=================

Admin-only endpoints for generating, listing, and revoking enrollment codes.
Agent-facing endpoint for enrolling a device with a valid code.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, EnrollmentCode
from server.schemas.enrollment import (
    EnrollmentCodeCreateRequest, EnrollmentCodeOut,
    EnrollmentRequest, EnrollmentResponse,
)
from server.authorization import require_admin
from server.security import log_audit, ACTIONS, enrollment_limiter
from server.services.enrollment_service import (
    generate_enrollment_code, validate_enrollment_code,
    create_device_from_enrollment, get_org_name,
)
from server.logging import get_logger

logger = get_logger("enrollment")

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


@router.post("/codes", response_model=EnrollmentCodeOut, status_code=status.HTTP_201_CREATED)
async def create_enrollment_code(
    req: EnrollmentCodeCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Generate a new enrollment code (admin only). Scoped to admin's organization."""
    code = generate_enrollment_code()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=req.expires_in_hours)

    enrollment_code = EnrollmentCode(
        code=code,
        organization_id=admin_user.organization_id,
        created_by_user_id=admin_user.id,
        expires_at=expires_at,
        max_uses=req.max_uses,
    )
    db.add(enrollment_code)
    await db.commit()
    await db.refresh(enrollment_code)

    logger.info("Enrollment code created: id=%s code=%s org=%s by admin=%s",
                enrollment_code.id, code, admin_user.organization_id, admin_user.id)
    await log_audit(
        ACTIONS["ENROLLMENT_CODE_CREATED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="enrollment_code", target_id=str(enrollment_code.id),
        detail=f"code={code} expires={expires_at.isoformat()} max_uses={req.max_uses}",
    )
    return enrollment_code


@router.get("/codes", response_model=list[EnrollmentCodeOut])
async def list_enrollment_codes(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List enrollment codes — scoped to admin's organization."""
    stmt = (
        select(EnrollmentCode)
        .where(EnrollmentCode.organization_id == admin_user.organization_id)
        .order_by(EnrollmentCode.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/codes/{code_id}")
async def revoke_enrollment_code(
    code_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Revoke an enrollment code (admin only). Must belong to admin's org."""
    code_obj = await db.get(EnrollmentCode, code_id)
    if not code_obj or code_obj.organization_id != admin_user.organization_id:
        raise HTTPException(status_code=404, detail="Enrollment code not found")

    code_obj.is_revoked = True
    await db.commit()

    logger.info("Enrollment code revoked: id=%s by admin=%s", code_id, admin_user.id)
    await log_audit(
        ACTIONS["ENROLLMENT_CODE_REVOKED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="enrollment_code", target_id=str(code_id),
    )
    return {"status": "revoked", "code_id": code_id}


@router.post("/enroll", response_model=EnrollmentResponse, dependencies=[Depends(enrollment_limiter)])
async def enroll_agent(
    req: EnrollmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Agent enrollment endpoint. Validates an enrollment code, creates
    a device record, and returns credentials.

    SECURITY:
      - Rate limited to prevent brute force
      - API key is returned ONCE and stored only as bcrypt hash
      - Enrollment code must be valid, not expired, not revoked
    """
    code_obj, error = await validate_enrollment_code(req.enrollment_code, db)

    if error:
        logger.warning("Enrollment failed: %s code=%s", error, req.enrollment_code)
        await log_audit(
            ACTIONS["ENROLLMENT_FAILED"],
            actor_type="agent",
            detail=f"{error}: {req.enrollment_code}",
            result="denied",
        )
        status_code = 404 if "Invalid" in error else 410
        raise HTTPException(status_code=status_code, detail=error)

    device, raw_api_key = await create_device_from_enrollment(
        code_obj, req.hostname, req.os_name, req.os_version, db,
    )

    org_name = await get_org_name(code_obj.organization_id, db)

    await log_audit(
        ACTIONS["DEVICE_ENROLLED"],
        actor_type="agent", actor_id=str(device.id),
        organization_id=code_obj.organization_id,
        target_type="device", target_id=str(device.id),
        detail=f"hostname={req.hostname} code={req.enrollment_code}",
    )

    server_url = str(request.base_url).rstrip("/")
    ws_scheme = "wss" if request.url.scheme == "https" else "ws"
    ws_url = f"{ws_scheme}://{request.url.netloc}/ws/v1/agent/{device.id}"

    return EnrollmentResponse(
        device_id=device.id,
        device_uuid=device.device_uuid,
        api_key=raw_api_key,
        organization_name=org_name,
        server_ws_url=ws_url,
        status="enrolled",
    )
