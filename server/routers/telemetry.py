"""
Telemetry Router
================

Endpoints for querying telemetry history, live metrics,
process lists, and Windows event logs for a device.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import MetricSnapshot, User
from server.auth import get_current_user
from server.authorization import check_device_access
from server.websockets.manager import connection_manager
from server.logging import get_logger

logger = get_logger("telemetry")

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


@router.get("/{device_id}/live")
async def get_live_metrics(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the latest cached live metrics for a device."""
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")

    metrics = connection_manager.latest_metrics.get(device_id)
    if not metrics:
        return {"device_id": device_id, "status": "no_data"}
    return {"device_id": device_id, "metrics": metrics}


@router.get("/{device_id}/processes")
async def get_processes(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the latest cached process list for a device."""
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")

    processes = connection_manager.latest_processes.get(device_id, [])
    return {"device_id": device_id, "processes": processes, "count": len(processes)}


@router.get("/{device_id}/events")
async def get_events(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cached Windows event logs for a device."""
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")

    events = connection_manager.device_events.get(device_id, [])
    return {"device_id": device_id, "events": events, "count": len(events)}


@router.get("/{device_id}/history")
async def get_metric_history(
    device_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get persisted metric history from the database."""
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")

    stmt = (
        select(MetricSnapshot)
        .where(
            MetricSnapshot.device_id == device_id,
            MetricSnapshot.organization_id == current_user.organization_id,
        )
        .order_by(desc(MetricSnapshot.timestamp))
        .limit(limit)
    )
    snapshots = (await db.execute(stmt)).scalars().all()

    return {
        "device_id": device_id,
        "count": len(snapshots),
        "snapshots": [
            {"id": s.id, "timestamp": s.timestamp.isoformat(), "metrics": s.metrics}
            for s in snapshots
        ],
    }
