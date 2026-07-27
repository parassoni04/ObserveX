import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware
from server.schemas import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    StaticInfoPayload,
    SoftwarePayload,
    EventLogPayload,
)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _verify_api_key(api_key: str, device: Device) -> bool:
    """Simple API key check – ensures the agent key matches the registered device."""
    return device.api_key == api_key


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new device or re-register an existing one (by hostname + api_key)."""

    # Check if device with same hostname already exists
    result = await db.execute(
        select(Device).where(Device.hostname == req.hostname)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-registration: update last_seen and mark online
        if existing.api_key != req.api_key:
            raise HTTPException(status_code=403, detail="API key mismatch for existing device")
        existing.last_seen = datetime.datetime.utcnow()
        existing.is_online = True
        existing.os_name = req.os_name or existing.os_name
        existing.os_version = req.os_version or existing.os_version
        await db.commit()
        await db.refresh(existing)
        return DeviceRegisterResponse(device_id=existing.id, hostname=existing.hostname, status="re-registered")

    # New registration
    device = Device(
        hostname=req.hostname,
        os_name=req.os_name,
        os_version=req.os_version,
        api_key=req.api_key,
        registered_at=datetime.datetime.utcnow(),
        last_seen=datetime.datetime.utcnow(),
        is_online=True,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return DeviceRegisterResponse(device_id=device.id, hostname=device.hostname, status="registered")


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def agent_heartbeat(req: HeartbeatRequest, db: AsyncSession = Depends(get_db)):
    """Agent heartbeat – updates last_seen timestamp."""
    device = await db.get(Device, req.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not _verify_api_key(req.api_key, device):
        raise HTTPException(status_code=403, detail="Invalid API key")

    device.last_seen = datetime.datetime.utcnow()
    device.is_online = True
    await db.commit()
    return HeartbeatResponse(status="ok")


@router.post("/static-info")
async def upload_static_info(
    device_id: int,
    api_key: str,
    payload: StaticInfoPayload,
    db: AsyncSession = Depends(get_db),
):
    """Upload or update static hardware info for a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not _verify_api_key(api_key, device):
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Upsert static info
    result = await db.execute(
        select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id)
    )
    info = result.scalar_one_or_none()

    valid_cols = {c.name for c in DeviceStaticInfo.__table__.columns if c.name not in ("id", "device_id", "updated_at")}
    data = {k: v for k, v in payload.model_dump(exclude_none=True).items() if k in valid_cols}

    if info:
        for k, v in data.items():
            setattr(info, k, v)
        info.updated_at = datetime.datetime.utcnow()
    else:
        info = DeviceStaticInfo(device_id=device_id, **data)
        db.add(info)

    await db.commit()
    return {"status": "ok", "device_id": device_id}


@router.post("/software")
async def upload_software(
    device_id: int,
    api_key: str,
    payload: SoftwarePayload,
    db: AsyncSession = Depends(get_db),
):
    """Upload installed software list for a device (replaces existing)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not _verify_api_key(api_key, device):
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Delete existing software entries
    await db.execute(
        delete(DeviceSoftware).where(DeviceSoftware.device_id == device_id)
    )

    # Insert new entries
    for item in payload.software:
        sw = DeviceSoftware(
            device_id=device_id,
            name=item.name,
            version=item.version,
            publisher=item.publisher,
            install_date=item.install_date,
        )
        db.add(sw)

    await db.commit()
    return {"status": "ok", "device_id": device_id, "count": len(payload.software)}


@router.post("/events")
async def upload_events(
    device_id: int,
    api_key: str,
    payload: EventLogPayload,
    db: AsyncSession = Depends(get_db),
):
    """Upload event logs from an agent (stored in-memory on server, not persisted to DB for now)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not _verify_api_key(api_key, device):
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Store events in a server-side cache (imported from hub)
    from server.websockets.hub import connection_manager
    connection_manager.device_events[device_id] = [e.model_dump() for e in payload.events]

    return {"status": "ok", "device_id": device_id, "count": len(payload.events)}
