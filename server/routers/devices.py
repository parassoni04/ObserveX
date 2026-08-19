import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware, User
from server.schemas import DeviceOut, DeviceStatusOut, StaticInfoOut, SoftwareItem, DeviceAssignRequest
from server.auth import get_current_user, require_role, security

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


async def get_optional_current_user(credentials=Depends(security), db: AsyncSession = Depends(get_db)) -> Optional[User]:
    if not credentials or not credentials.credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except Exception:
        return None


async def _get_device_or_404(device_id: int, db: AsyncSession) -> Device:
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("", response_model=list[DeviceOut])
async def list_devices(db: AsyncSession = Depends(get_db), current_user: Optional[User] = Depends(get_optional_current_user)):
    if current_user and current_user.role == "admin":
        stmt = select(Device).order_by(Device.hostname)
    elif current_user:
        stmt = select(Device).where(
            (Device.assigned_user_id == current_user.id) |
            (Device.assigned_user_id.is_(None) & (Device.organization_id == current_user.organization_id))
        ).order_by(Device.hostname)
    else:
        stmt = select(Device).order_by(Device.hostname)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_device_or_404(device_id, db)


@router.post("/{device_id}/assign", response_model=DeviceOut)
async def assign_device(device_id: int, req: DeviceAssignRequest, db: AsyncSession = Depends(get_db), admin_user: User = Depends(require_role(["admin"]))):
    device = await _get_device_or_404(device_id, db)
    if req.assigned_user_id is not None:
        if req.assigned_user_id > 0:
            target_user = await db.get(User, req.assigned_user_id)
            if not target_user:
                raise HTTPException(status_code=404, detail="Assigned user not found")
            device.assigned_user_id = target_user.id
            if target_user.organization_id:
                device.organization_id = target_user.organization_id
        else:
            device.assigned_user_id = None
    if req.organization_id is not None:
        device.organization_id = req.organization_id if req.organization_id > 0 else None
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}")
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db), current_user: Optional[User] = Depends(get_optional_current_user)):
    if current_user and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required to remove devices")
    device = await _get_device_or_404(device_id, db)
    await db.delete(device)
    await db.commit()
    return {"status": "deleted", "device_id": device_id}


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def get_device_status(device_id: int, db: AsyncSession = Depends(get_db)):
    device = await _get_device_or_404(device_id, db)
    is_online = device.is_online
    if device.last_seen and (datetime.datetime.utcnow() - device.last_seen).total_seconds() > 30:
        is_online = False
        if device.is_online:
            device.is_online = False
            await db.commit()
    return DeviceStatusOut(device_id=device.id, is_online=is_online, last_seen=device.last_seen)


@router.get("/{device_id}/static-info", response_model=StaticInfoOut)
async def get_device_static_info(device_id: int, db: AsyncSession = Depends(get_db)):
    await _get_device_or_404(device_id, db)
    info = (await db.execute(select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id))).scalar_one_or_none()
    if not info:
        raise HTTPException(status_code=404, detail="Static info not yet reported")
    return info


@router.get("/{device_id}/software", response_model=list[SoftwareItem])
async def get_device_software(device_id: int, db: AsyncSession = Depends(get_db)):
    await _get_device_or_404(device_id, db)
    rows = (await db.execute(select(DeviceSoftware).where(DeviceSoftware.device_id == device_id).order_by(DeviceSoftware.name))).scalars().all()
    return [SoftwareItem(name=r.name, version=r.version, publisher=r.publisher, install_date=r.install_date) for r in rows]
