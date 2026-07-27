import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware, User
from server.schemas import DeviceOut, DeviceStatusOut, StaticInfoOut, SoftwareItem, DeviceAssignRequest
from server.auth import get_current_user, require_role, security

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


async def get_optional_current_user(
    credentials=Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Helper to get current user if Bearer token is provided, or None if unauthenticated."""
    if not credentials or not credentials.credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except Exception:
        return None


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """List registered devices. Admins see all devices; non-admin users see only their assigned devices."""
    if current_user and current_user.role == "admin":
        stmt = select(Device).order_by(Device.hostname)
    elif current_user:
        # Non-admin user: only see devices assigned to them or unassigned in their org
        stmt = select(Device).where(
            (Device.assigned_user_id == current_user.id) |
            (Device.assigned_user_id.is_(None) & (Device.organization_id == current_user.organization_id))
        ).order_by(Device.hostname)
    else:
        # Unauthenticated / local mode fallback: return all devices
        stmt = select(Device).order_by(Device.hostname)

    result = await db.execute(stmt)
    devices = result.scalars().all()
    return devices


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single device by ID."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("/{device_id}/assign", response_model=DeviceOut)
async def assign_device(
    device_id: int,
    req: DeviceAssignRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_role(["admin"]))
):
    """Assign a device to a specific user and/or organization (Admin only)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if req.assigned_user_id is not None:
        if req.assigned_user_id > 0:
            target_user = await db.get(User, req.assigned_user_id)
            if not target_user:
                raise HTTPException(status_code=404, detail="Assigned user not found")
            device.assigned_user_id = target_user.id
            if target_user.organization_id:
                device.organization_id = target_user.organization_id
        else:
            # Unassign
            device.assigned_user_id = None

    if req.organization_id is not None:
        device.organization_id = req.organization_id if req.organization_id > 0 else None

    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """Remove a registered device and all its data."""
    if current_user and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required to remove devices")

    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await db.delete(device)
    await db.commit()
    return {"status": "deleted", "device_id": device_id}


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def get_device_status(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get online/offline status and last_seen timestamp."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Mark as offline if last_seen is older than 30 seconds
    is_online = device.is_online
    if device.last_seen:
        age = (datetime.datetime.utcnow() - device.last_seen).total_seconds()
        if age > 30:
            is_online = False
            if device.is_online:
                device.is_online = False
                await db.commit()

    return DeviceStatusOut(
        device_id=device.id,
        is_online=is_online,
        last_seen=device.last_seen,
    )


@router.get("/{device_id}/static-info")
async def get_device_static_info(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get hardware/OS specs for a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await db.execute(
        select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id)
    )
    info = result.scalar_one_or_none()
    if not info:
        return {"device_id": device_id, "message": "Static info not yet reported"}

    return {
        "device_id": info.device_id,
        "computer_name": info.computer_name,
        "os_release": info.os_release,
        "cpu_model": info.cpu_model,
        "cpu_cores_physical": info.cpu_cores_physical,
        "cpu_cores_logical": info.cpu_cores_logical,
        "total_ram_gb": info.total_ram_gb,
        "gpu_model": info.gpu_model,
        "motherboard_mfg": info.motherboard_mfg,
        "motherboard_product": info.motherboard_product,
        "bios_name": info.bios_name,
        "bios_version": info.bios_version,
        "storage_devices": info.storage_devices,
        "network_adapters": info.network_adapters,
        "updated_at": info.updated_at,
    }


@router.get("/{device_id}/software", response_model=list[SoftwareItem])
async def get_device_software(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get installed software for a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await db.execute(
        select(DeviceSoftware)
        .where(DeviceSoftware.device_id == device_id)
        .order_by(DeviceSoftware.name)
    )
    rows = result.scalars().all()
    return [
        SoftwareItem(name=r.name, version=r.version, publisher=r.publisher, install_date=r.install_date)
        for r in rows
    ]
