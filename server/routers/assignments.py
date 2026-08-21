"""
ObserveX Server — Device-User Assignment Management.

Admin-only endpoints for managing many-to-many device↔user assignments.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, User, DeviceUserAssignment
from server.schemas import DeviceAssignmentCreateRequest, DeviceAssignmentOut
from server.authorization import require_admin

router = APIRouter(prefix="/api/v1/admin/assignments", tags=["assignments"])


@router.get("", response_model=list[DeviceAssignmentOut])
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List all device-user assignments with enriched data."""
    result = await db.execute(
        select(DeviceUserAssignment).order_by(DeviceUserAssignment.assigned_at.desc())
    )
    assignments = result.scalars().all()

    out = []
    for a in assignments:
        device = await db.get(Device, a.device_id)
        user = await db.get(User, a.user_id)
        out.append(DeviceAssignmentOut(
            id=a.id,
            device_id=a.device_id,
            user_id=a.user_id,
            assigned_by=a.assigned_by,
            assigned_at=a.assigned_at,
            device_hostname=device.hostname if device else None,
            username=user.username if user else None,
        ))
    return out


@router.post("", response_model=DeviceAssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    req: DeviceAssignmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Assign a device to a user (admin only)."""
    device = await db.get(Device, req.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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

    return DeviceAssignmentOut(
        id=assignment.id,
        device_id=assignment.device_id,
        user_id=assignment.user_id,
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        device_hostname=device.hostname,
        username=user.username,
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
    await db.delete(assignment)
    await db.commit()
    return {"status": "deleted", "assignment_id": assignment_id}


@router.get("/device/{device_id}", response_model=list[DeviceAssignmentOut])
async def get_device_assignments(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List all users assigned to a specific device."""
    result = await db.execute(
        select(DeviceUserAssignment).where(DeviceUserAssignment.device_id == device_id)
    )
    assignments = result.scalars().all()
    out = []
    for a in assignments:
        user = await db.get(User, a.user_id)
        out.append(DeviceAssignmentOut(
            id=a.id, device_id=a.device_id, user_id=a.user_id,
            assigned_by=a.assigned_by, assigned_at=a.assigned_at,
            device_hostname=None, username=user.username if user else None,
        ))
    return out


@router.get("/user/{user_id}", response_model=list[DeviceAssignmentOut])
async def get_user_assignments(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List all devices assigned to a specific user."""
    result = await db.execute(
        select(DeviceUserAssignment).where(DeviceUserAssignment.user_id == user_id)
    )
    assignments = result.scalars().all()
    out = []
    for a in assignments:
        device = await db.get(Device, a.device_id)
        out.append(DeviceAssignmentOut(
            id=a.id, device_id=a.device_id, user_id=a.user_id,
            assigned_by=a.assigned_by, assigned_at=a.assigned_at,
            device_hostname=device.hostname if device else None, username=None,
        ))
    return out
