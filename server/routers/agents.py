"""
ObserveX Server — Agent Communication Endpoints.

Handles device registration (legacy), enrollment (new), heartbeat,
static info, software, and event log uploads from agents.
"""
import datetime

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware
from server.schemas import (
    DeviceRegisterRequest, DeviceRegisterResponse,
    HeartbeatRequest, HeartbeatResponse,
    StaticInfoPayload, SoftwarePayload, EventLogPayload,
    EnrollmentRequest, EnrollmentResponse,
)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


# ── Agent Authentication ──

async def _auth_agent_from_bearer(
    request: Request,
    device_id: int,
    db: AsyncSession,
) -> Device:
    """
    Authenticate an agent via Bearer token in Authorization header.
    Verifies the credential against the device's api_key_hash.
    Falls back to legacy plaintext api_key check.
    """
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Agent authentication required")

    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status == "revoked":
        raise HTTPException(status_code=403, detail="Device has been revoked")

    # Try hashed key first
    if device.api_key_hash:
        try:
            if bcrypt.checkpw(token.encode("utf-8"), device.api_key_hash.encode("utf-8")):
                return device
        except Exception:
            pass

    # Legacy fallback: plaintext comparison
    if device.api_key and device.api_key == token:
        return device

    raise HTTPException(status_code=403, detail="Invalid agent credential")


async def _auth_device(device_id: int, api_key: str, db: AsyncSession) -> Device:
    """Legacy auth: plaintext API key comparison (for backward compat)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status == "revoked":
        raise HTTPException(status_code=403, detail="Device has been revoked")

    # Try hashed key
    if device.api_key_hash:
        try:
            if bcrypt.checkpw(api_key.encode("utf-8"), device.api_key_hash.encode("utf-8")):
                return device
        except Exception:
            pass

    # Legacy fallback
    if device.api_key and device.api_key == api_key:
        return device

    raise HTTPException(status_code=403, detail="Invalid API key")


# ── Enrollment (delegates to enrollment router) ──

@router.post("/enroll", response_model=EnrollmentResponse)
async def enroll_device(req: EnrollmentRequest, db: AsyncSession = Depends(get_db)):
    """Convenience alias — delegates to the enrollment router's enroll_agent."""
    from server.routers.enrollment import enroll_agent
    return await enroll_agent(req, db)


# ── Legacy Registration ──

@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(req: DeviceRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Legacy device registration (kept for backward compatibility)."""
    existing = (await db.execute(select(Device).where(Device.hostname == req.hostname))).scalar_one_or_none()
    if existing:
        # Verify key
        valid = False
        if existing.api_key_hash:
            try:
                valid = bcrypt.checkpw(req.api_key.encode("utf-8"), existing.api_key_hash.encode("utf-8"))
            except Exception:
                pass
        if not valid and existing.api_key:
            valid = existing.api_key == req.api_key
        if not valid:
            raise HTTPException(status_code=403, detail="API key mismatch for existing device")

        existing.last_seen = datetime.datetime.utcnow()
        existing.is_online = True
        existing.status = "active"
        existing.os_name = req.os_name or existing.os_name
        existing.os_version = req.os_version or existing.os_version
        await db.commit()
        await db.refresh(existing)
        return DeviceRegisterResponse(device_id=existing.id, hostname=existing.hostname, status="re-registered")

    # Hash the API key for new devices
    api_key_hash = bcrypt.hashpw(req.api_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    device = Device(
        hostname=req.hostname, os_name=req.os_name, os_version=req.os_version,
        api_key=req.api_key, api_key_hash=api_key_hash, status="active",
        registered_at=datetime.datetime.utcnow(), last_seen=datetime.datetime.utcnow(), is_online=True,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return DeviceRegisterResponse(device_id=device.id, hostname=device.hostname, status="registered")


# ── Heartbeat ──

@router.post("/heartbeat", response_model=HeartbeatResponse)
async def agent_heartbeat(
    req: HeartbeatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Agent heartbeat — supports both Bearer token and legacy api_key."""
    # Try Bearer auth first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        device = await _auth_agent_from_bearer(request, req.device_id, db)
    elif req.api_key:
        device = await _auth_device(req.device_id, req.api_key, db)
    else:
        raise HTTPException(status_code=401, detail="Agent authentication required")

    device.last_seen = datetime.datetime.utcnow()
    device.is_online = True
    if device.status in ("pending", "offline", "stale"):
        device.status = "active"
    await db.commit()
    return HeartbeatResponse(status="ok")


# ── Static Info ──

@router.post("/static-info")
async def upload_static_info(
    device_id: int,
    payload: StaticInfoPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[str] = None,
):
    """Upload device static hardware/OS info."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await _auth_agent_from_bearer(request, device_id, db)
    elif api_key:
        await _auth_device(device_id, api_key, db)
    else:
        raise HTTPException(status_code=401, detail="Agent authentication required")

    info = (await db.execute(
        select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id)
    )).scalar_one_or_none()

    valid_cols = {c.name for c in DeviceStaticInfo.__table__.columns if c.name not in ("id", "device_id", "updated_at")}
    data = {k: v for k, v in payload.model_dump(exclude_none=True).items() if k in valid_cols}

    if info:
        for k, v in data.items():
            setattr(info, k, v)
        info.updated_at = datetime.datetime.utcnow()
    else:
        db.add(DeviceStaticInfo(device_id=device_id, **data))
    await db.commit()
    return {"status": "ok", "device_id": device_id}


# ── Software ──

@router.post("/software")
async def upload_software(
    device_id: int,
    payload: SoftwarePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[str] = None,
):
    """Upload installed software list."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await _auth_agent_from_bearer(request, device_id, db)
    elif api_key:
        await _auth_device(device_id, api_key, db)
    else:
        raise HTTPException(status_code=401, detail="Agent authentication required")

    await db.execute(delete(DeviceSoftware).where(DeviceSoftware.device_id == device_id))
    for item in payload.software:
        db.add(DeviceSoftware(
            device_id=device_id, name=item.name, version=item.version,
            publisher=item.publisher, install_date=item.install_date,
        ))
    await db.commit()
    return {"status": "ok", "device_id": device_id, "count": len(payload.software)}


# ── Event Logs ──

@router.post("/events")
async def upload_events(
    device_id: int,
    payload: EventLogPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: Optional[str] = None,
):
    """Upload Windows event logs."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        await _auth_agent_from_bearer(request, device_id, db)
    elif api_key:
        await _auth_device(device_id, api_key, db)
    else:
        raise HTTPException(status_code=401, detail="Agent authentication required")

    from server.websockets.hub import connection_manager
    connection_manager.device_events[device_id] = [e.model_dump() for e in payload.events]
    return {"status": "ok", "device_id": device_id, "count": len(payload.events)}
