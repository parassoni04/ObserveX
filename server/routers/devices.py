"""
ObserveX Server — Device CRUD & Information Endpoints.

All endpoints require authentication. Device-level authorization
ensures users can only access devices assigned to them.
Admins can access all devices.
"""
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware, User, DeviceUserAssignment
from server.schemas import DeviceOut, DeviceStatusOut, StaticInfoOut, SoftwareItem, DeviceAssignRequest, AssignedUserSummary
from server.auth import get_current_user, require_role
from server.authorization import check_device_access, get_accessible_device_ids, require_admin

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


async def _get_device_or_404(device_id: int, db: AsyncSession) -> Device:
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def _enrich_device_out(device: Device, db: AsyncSession) -> DeviceOut:
    """Build DeviceOut with assigned_users populated from the association table."""
    # Fetch assigned users from many-to-many table
    result = await db.execute(
        select(DeviceUserAssignment).where(DeviceUserAssignment.device_id == device.id)
    )
    assignments = result.scalars().all()

    assigned_users = []
    for a in assignments:
        user = await db.get(User, a.user_id)
        if user:
            assigned_users.append(AssignedUserSummary(
                id=user.id, username=user.username,
                full_name=user.full_name, email=user.email,
            ))

    return DeviceOut(
        id=device.id,
        device_uuid=device.device_uuid,
        hostname=device.hostname,
        os_name=device.os_name,
        os_version=device.os_version,
        agent_version=device.agent_version,
        status=device.status,
        registered_at=device.registered_at,
        last_seen=device.last_seen,
        is_online=device.is_online,
        organization_id=device.organization_id,
        assigned_user_id=device.assigned_user_id,
        assigned_users=assigned_users,
    )


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List devices accessible to the current user. Admins see all."""
    accessible_ids = await get_accessible_device_ids(current_user, db)

    if accessible_ids is None:
        # Admin — all devices
        stmt = select(Device).order_by(Device.hostname)
    else:
        if not accessible_ids:
            return []
        stmt = select(Device).where(Device.id.in_(accessible_ids)).order_by(Device.hostname)

    devices = (await db.execute(stmt)).scalars().all()
    return [await _enrich_device_out(d, db) for d in devices]


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device details. Requires access to the device."""
    device = await _get_device_or_404(device_id, db)
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=403, detail="You do not have access to this device")
    return await _enrich_device_out(device, db)


@router.post("/{device_id}/assign", response_model=DeviceOut)
async def assign_device(
    device_id: int,
    req: DeviceAssignRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Assign device to a user (admin only). Updates both legacy FK and association table."""
    device = await _get_device_or_404(device_id, db)

    if req.assigned_user_id is not None:
        if req.assigned_user_id > 0:
            target_user = await db.get(User, req.assigned_user_id)
            if not target_user:
                raise HTTPException(status_code=404, detail="Assigned user not found")

            # Update legacy FK
            device.assigned_user_id = target_user.id
            if target_user.organization_id:
                device.organization_id = target_user.organization_id

            # Also create many-to-many assignment if not exists
            existing = await db.execute(
                select(DeviceUserAssignment).where(
                    DeviceUserAssignment.device_id == device_id,
                    DeviceUserAssignment.user_id == target_user.id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(DeviceUserAssignment(
                    device_id=device_id,
                    user_id=target_user.id,
                    assigned_by=admin_user.id,
                ))
        else:
            device.assigned_user_id = None

    if req.organization_id is not None:
        device.organization_id = req.organization_id if req.organization_id > 0 else None

    await db.commit()
    await db.refresh(device)
    return await _enrich_device_out(device, db)


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Delete a device (admin only)."""
    device = await _get_device_or_404(device_id, db)
    await db.delete(device)
    await db.commit()
    return {"status": "deleted", "device_id": device_id}


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def get_device_status(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device online/offline status. Requires access."""
    device = await _get_device_or_404(device_id, db)
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=403, detail="You do not have access to this device")

    is_online = device.is_online
    if device.last_seen and (datetime.datetime.utcnow() - device.last_seen).total_seconds() > 30:
        is_online = False
        if device.is_online:
            device.is_online = False
            device.status = "offline"
            await db.commit()

    return DeviceStatusOut(
        device_id=device.id, is_online=is_online,
        status=device.status, last_seen=device.last_seen,
    )


@router.get("/{device_id}/static-info", response_model=StaticInfoOut)
async def get_device_static_info(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device hardware/OS info. Requires access."""
    await _get_device_or_404(device_id, db)
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=403, detail="You do not have access to this device")

    info = (await db.execute(
        select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id)
    )).scalar_one_or_none()
    if not info:
        raise HTTPException(status_code=404, detail="Static info not yet reported")
    return info


@router.get("/{device_id}/software", response_model=list[SoftwareItem])
async def get_device_software(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device installed software. Requires access."""
    await _get_device_or_404(device_id, db)
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=403, detail="You do not have access to this device")

    rows = (await db.execute(
        select(DeviceSoftware).where(DeviceSoftware.device_id == device_id).order_by(DeviceSoftware.name)
    )).scalars().all()
    return [SoftwareItem(name=r.name, version=r.version, publisher=r.publisher, install_date=r.install_date) for r in rows]
