import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware
from server.schemas import DeviceOut, DeviceStatusOut, StaticInfoOut, SoftwareItem

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
async def list_devices(db: AsyncSession = Depends(get_db)):
    """List all registered devices."""
    result = await db.execute(select(Device).order_by(Device.hostname))
    devices = result.scalars().all()
    return devices


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single device by ID."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.delete("/{device_id}")
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a registered device and all its data."""
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
