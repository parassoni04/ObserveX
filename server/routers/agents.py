"""
Agent Router
============

Agent-facing HTTP endpoints for heartbeat, static info, software,
and event log uploads. All endpoints authenticate via Bearer token
(bcrypt hash verification against device's api_key_hash).

The legacy plaintext api_key fallback has been removed.
"""
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, DeviceStaticInfo, DeviceSoftware, WindowsEvent
from server.schemas.telemetry import (
    HeartbeatRequest, HeartbeatResponse,
    StaticInfoPayload, SoftwarePayload, EventLogPayload,
)
from server.auth.device_auth import verify_device_credential
from server.security import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("agents")

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


async def _auth_agent(request: Request, device_id: int, db: AsyncSession) -> Device:
    """
    Authenticate an agent via Bearer token.

    CRITICAL: After authentication, verifies the device_id matches
    the authenticated device to prevent cross-device impersonation.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Agent authentication required (Bearer token)")

    token = auth_header[7:]
    device = await verify_device_credential(device_id, token, db)
    if not device:
        raise HTTPException(status_code=403, detail="Invalid agent credential")

    return device


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def agent_heartbeat(
    req: HeartbeatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Agent heartbeat — updates last_seen and status.
    Verifies the authenticated device matches req.device_id.
    """
    device = await _auth_agent(request, req.device_id, db)

    if device.id != req.device_id:
        logger.warning("Heartbeat device_id mismatch: auth=%s req=%s", device.id, req.device_id)
        raise HTTPException(status_code=403, detail="Device ID mismatch")

    device.last_seen = datetime.datetime.utcnow()
    device.is_online = True
    if device.status in ("pending", "offline", "stale"):
        device.status = "active"
    await db.commit()
    return HeartbeatResponse(status="ok")


@router.post("/static-info")
async def upload_static_info(
    device_id: int,
    payload: StaticInfoPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upload device static hardware/OS info."""
    device = await _auth_agent(request, device_id, db)
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Device ID mismatch")

    info = (await db.execute(
        select(DeviceStaticInfo).where(DeviceStaticInfo.device_id == device_id)
    )).scalar_one_or_none()

    valid_cols = {c.name for c in DeviceStaticInfo.__table__.columns if c.name not in ("id", "device_id", "organization_id", "updated_at")}
    data = {k: v for k, v in payload.model_dump(exclude_none=True).items() if k in valid_cols}

    if info:
        for k, v in data.items():
            setattr(info, k, v)
        info.updated_at = datetime.datetime.utcnow()
    else:
        db.add(DeviceStaticInfo(
            device_id=device_id,
            organization_id=device.organization_id,
            **data,
        ))
    await db.commit()
    return {"status": "ok", "device_id": device_id}


@router.post("/software")
async def upload_software(
    device_id: int,
    payload: SoftwarePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upload installed software list (atomic replace)."""
    device = await _auth_agent(request, device_id, db)
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Device ID mismatch")

    await db.execute(delete(DeviceSoftware).where(DeviceSoftware.device_id == device_id))
    for item in payload.software:
        db.add(DeviceSoftware(
            device_id=device_id,
            organization_id=device.organization_id,
            name=item.name, version=item.version,
            publisher=item.publisher, install_date=item.install_date,
        ))
    await db.commit()
    return {"status": "ok", "device_id": device_id, "count": len(payload.software)}


@router.post("/events")
async def upload_events(
    device_id: int,
    payload: EventLogPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upload Windows event logs — stored in-memory and optionally in DB."""
    device = await _auth_agent(request, device_id, db)
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Device ID mismatch")

    from server.websockets.manager import connection_manager
    connection_manager.device_events[device_id] = [e.model_dump() for e in payload.events]

    return {"status": "ok", "device_id": device_id, "count": len(payload.events)}
