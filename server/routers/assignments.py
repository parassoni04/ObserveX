"""
Device-User Assignment Router
==============================

Admin-only endpoints for managing many-to-many device↔user assignments.
All operations are scoped to the admin's organization.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from server.database import get_db
from server.models import Device, User, DeviceUserAssignment
from server.schemas.device import DeviceAssignmentCreateRequest, DeviceAssignmentOut
from server.authorization import require_admin, TenantGuard
from server.security import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("assignments")

router = APIRouter(prefix="/api/v1/admin/assignments", tags=["assignments"])


@router.get("", response_model=list[DeviceAssignmentOut])
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List all device-user assignments — scoped to admin's org."""
    stmt = (
        select(DeviceUserAssignment)
        .options(
            selectinload(DeviceUserAssignment.device),
            selectinload(DeviceUserAssignment.user),
        )
        .join(DeviceUserAssignment.device)
        .where(Device.organization_id == admin_user.organization_id)
        .order_by(DeviceUserAssignment.assigned_at.desc())
    )
    assignments = (await db.execute(stmt)).scalars().all()
    return [
        DeviceAssignmentOut(
            id=a.id, device_id=a.device_id, user_id=a.user_id,
            assigned_by=a.assigned_by, assigned_at=a.assigned_at,
            device_hostname=a.device.hostname if a.device else None,
            username=a.user.username if a.user else None,
        )
        for a in assignments
    ]


@router.post("", response_model=DeviceAssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    req: DeviceAssignmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Assign a device to a user (admin only). Both must be in admin's org."""
    device = await TenantGuard.get_or_404(Device, req.device_id, admin_user, db)
    user = await TenantGuard.get_or_404(User, req.user_id, admin_user, db)

    # Check for duplicate
    existing = await db.execute(
        select(DeviceUserAssignment).where(
            DeviceUserAssignment.device_id == req.device_id,
            DeviceUserAssignment.user_id == req.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Device is already assigned to this user")

    assignment = DeviceUserAssignment(
        device_id=req.device_id,
        user_id=req.user_id,
        assigned_by=admin_user.id,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    logger.info("Device assigned: device=%s user=%s by admin=%s", req.device_id, req.user_id, admin_user.id)
    await log_audit(
        ACTIONS["DEVICE_ASSIGNED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="device", target_id=str(req.device_id),
        detail=f"assigned_user={req.user_id}",
    )

    return DeviceAssignmentOut(
        id=assignment.id, device_id=assignment.device_id,
        user_id=assignment.user_id, assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        device_hostname=device.hostname, username=user.username,
    )


@router.delete("/{assignment_id}")
async def delete_assignment(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Remove a device-user assignment (admin only)."""
    assignment = await db.get(DeviceUserAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Verify device is in admin's org
    device = await db.get(Device, assignment.device_id)
    if not device or device.organization_id != admin_user.organization_id:
        raise HTTPException(status_code=404, detail="Assignment not found")

    device_id = assignment.device_id
    user_id = assignment.user_id
    await db.delete(assignment)
    await db.commit()

    logger.info("Device unassigned: device=%s user=%s by admin=%s", device_id, user_id, admin_user.id)
    await log_audit(
        ACTIONS["DEVICE_UNASSIGNED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="device", target_id=str(device_id),
        detail=f"unassigned_user={user_id}",
    )
    return {"status": "deleted", "assignment_id": assignment_id}
