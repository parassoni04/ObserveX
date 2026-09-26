"""
Devices Router
==============

Device CRUD & information endpoints. All endpoints require authentication.
Admins can access any device in their org. Regular users can only access
assigned devices. Cross-org access is always denied (returns 404).
"""
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware, User, DeviceUserAssignment
from server.schemas.device import DeviceOut, DeviceStatusOut, AssignedUserSummary, DeviceAssignmentCreateRequest, DeviceAssignmentOut
from server.schemas.telemetry import StaticInfoOut, SoftwareItem
from server.auth import get_current_user
from server.authorization import check_device_access, get_accessible_device_ids, require_admin, TenantGuard
from server.security import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("devices")

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


async def _get_authorized_device_or_404(device_id: int, user: User, db: AsyncSession) -> Device:
    """Fetch device and verify user has access, raising 404 if not found or unauthorized."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not await check_device_access(user, device_id, db):
        logger.warning("Unauthorized device access: user_id=%s device_id=%s", user.id, device_id)
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def _enrich_device_out(device: Device, db: AsyncSession) -> DeviceOut:
    """Build DeviceOut with assigned_users from the association table."""
    result = await db.execute(
        select(DeviceUserAssignment)
        .options(selectinload(DeviceUserAssignment.user))
        .where(DeviceUserAssignment.device_id == device.id)
    )
    assignments = result.scalars().all()

    assigned_users = [
        AssignedUserSummary(
            id=a.user.id, username=a.user.username,
            full_name=a.user.full_name, email=a.user.email,
        )
        for a in assignments if a.user
    ]

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
        assigned_users=assigned_users,
    )


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List devices accessible to the current user."""
    accessible_ids = await get_accessible_device_ids(current_user, db)

    if accessible_ids is None:
        # Admin — scoped to organization
        stmt = (
            select(Device)
            .where(Device.organization_id == current_user.organization_id)
            .order_by(Device.hostname)
        )
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
    """Get device details. Requires access."""
    device = await _get_authorized_device_or_404(device_id, current_user, db)
    return await _enrich_device_out(device, db)


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Delete a device (admin only)."""
    client_ip = request.client.host if request.client else "unknown"
    device = await _get_authorized_device_or_404(device_id, admin_user, db)

    hostname = device.hostname
    await db.delete(device)
    await db.commit()

    logger.info("Device deleted: device_id=%s hostname=%s by admin=%s", device_id, hostname, admin_user.id)
    await log_audit(
        ACTIONS["DEVICE_DELETED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="device", target_id=str(device_id),
        ip_address=client_ip,
        detail=f"Deleted hostname={hostname}",
    )
    return {"status": "deleted", "device_id": device_id}


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def get_device_status(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device online/offline status."""
    device = await _get_authorized_device_or_404(device_id, current_user, db)
    return DeviceStatusOut(
        device_id=device.id, is_online=device.is_online,
        status=device.status, last_seen=device.last_seen,
    )


@router.get("/{device_id}/static-info", response_model=StaticInfoOut)
async def get_device_static_info(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get device hardware/OS info."""
    await _get_authorized_device_or_404(device_id, current_user, db)
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
    """Get device installed software."""
    await _get_authorized_device_or_404(device_id, current_user, db)
    rows = (await db.execute(
        select(DeviceSoftware).where(DeviceSoftware.device_id == device_id).order_by(DeviceSoftware.name)
    )).scalars().all()
    return [SoftwareItem(name=r.name, version=r.version, publisher=r.publisher, install_date=r.install_date) for r in rows]
