"""
ObserveX Server — Metric History & Analytics Endpoints.

All endpoints require authentication and device-level authorization.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, MetricSnapshot, Alert, User
from server.schemas import MetricSnapshotOut, MetricHistoryResponse, MetricSummaryResponse
from server.websockets.hub import connection_manager
from server.auth import get_current_user
from server.authorization import check_device_access

router = APIRouter(prefix="/api/v1/devices/{device_id}/metrics", tags=["metrics"])


async def _dev_authorized(device_id: int, current_user: User, db: AsyncSession) -> Device:
    """Get device and verify user access."""
    d = await db.get(Device, device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Device not found")
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=403, detail="You do not have access to this device")
    return d


@router.get("/latest", response_model=MetricSnapshotOut | None)
async def get_latest_metric(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _dev_authorized(device_id, current_user, db)
    return (await db.execute(
        select(MetricSnapshot).where(MetricSnapshot.device_id == device_id).order_by(desc(MetricSnapshot.timestamp)).limit(1)
    )).scalar_one_or_none()


@router.get("", response_model=MetricHistoryResponse)
async def get_metric_history(
    device_id: int,
    minutes: int = Query(default=60, ge=1, le=10080),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _dev_authorized(device_id, current_user, db)
    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
    snaps = (await db.execute(
        select(MetricSnapshot).where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= since)
        .order_by(desc(MetricSnapshot.timestamp)).limit(limit)
    )).scalars().all()
    return MetricHistoryResponse(device_id=device_id, count=len(snaps), snapshots=snaps)


@router.get("/summary", response_model=MetricSummaryResponse)
async def get_metric_summary(
    device_id: int,
    minutes: int = Query(default=60, ge=1, le=10080),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _dev_authorized(device_id, current_user, db)
    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)

    is_sqlite = "sqlite" in str(db.bind.url if db.bind else "")
    jx = "json_extract(metrics, '$.{}')" if is_sqlite else "(metrics->>'{}')::float"
    q = f"""SELECT COUNT(*) as snapshot_count,
        AVG({jx.format('cpu_usage')}) as avg_cpu, MAX({jx.format('cpu_usage')}) as max_cpu,
        AVG({jx.format('ram_usage_percent')}) as avg_ram, MAX({jx.format('ram_usage_percent')}) as max_ram,
        AVG({jx.format('gpu_usage')}) as avg_gpu, MAX({jx.format('gpu_usage')}) as max_gpu
        FROM metric_snapshots WHERE device_id = :device_id AND timestamp >= :since"""

    row = (await db.execute(text(q), {"device_id": device_id, "since": since})).fetchone()
    return MetricSummaryResponse(
        device_id=device_id, period_minutes=minutes,
        avg_cpu=round(row.avg_cpu, 2) if row.avg_cpu else None,
        max_cpu=round(row.max_cpu, 2) if row.max_cpu else None,
        avg_ram=round(row.avg_ram, 2) if row.avg_ram else None,
        max_ram=round(row.max_ram, 2) if row.max_ram else None,
        avg_gpu=round(row.avg_gpu, 2) if row.avg_gpu else None,
        max_gpu=round(row.max_gpu, 2) if row.max_gpu else None,
        snapshot_count=row.snapshot_count or 0,
    )


@router.get("/trends")
async def get_metric_trends(
    device_id: int,
    period: str = Query(default="24h", pattern="^(15m|1h|6h|24h|7d)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _dev_authorized(device_id, current_user, db)
    minutes = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080}[period]
    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)

    snapshots = (await db.execute(
        select(MetricSnapshot).where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= since)
        .order_by(MetricSnapshot.timestamp.asc())
    )).scalars().all()

    empty = {"device_id": device_id, "period": period, "snapshot_count": 0,
             "cpu_avg": 0, "cpu_min": 0, "cpu_max": 0, "cpu_trend_slope": 0,
             "ram_avg": 0, "ram_min": 0, "ram_max": 0,
             "disk_read_max": 0, "disk_write_max": 0, "net_download_max": 0, "net_upload_max": 0}
    if not snapshots:
        return empty

    keys = {"cpu_usage": [], "ram_usage_percent": [], "disk_read_speed": [], "disk_write_speed": [], "net_download_speed": [], "net_upload_speed": []}
    for s in snapshots:
        m = s.metrics
        for k in keys:
            if k in m:
                keys[k].append(m[k])

    cpus, rams = keys["cpu_usage"], keys["ram_usage_percent"]
    slope = 0.0
    if len(cpus) >= 4:
        half = len(cpus) // 2
        slope = round(sum(cpus[half:]) / (len(cpus) - half) - sum(cpus[:half]) / half, 2)

    _avg = lambda v: round(sum(v) / len(v), 1) if v else 0
    _mx = lambda v: round(max(v), 1) if v else 0
    _mn = lambda v: round(min(v), 1) if v else 0

    return {
        "device_id": device_id, "period": period, "snapshot_count": len(snapshots),
        "cpu_avg": _avg(cpus), "cpu_min": _mn(cpus), "cpu_max": _mx(cpus), "cpu_trend_slope": slope,
        "ram_avg": _avg(rams), "ram_min": _mn(rams), "ram_max": _mx(rams),
        "disk_read_max": _mx(keys["disk_read_speed"]), "disk_write_max": _mx(keys["disk_write_speed"]),
        "net_download_max": _mx(keys["net_download_speed"]), "net_upload_max": _mx(keys["net_upload_speed"]),
    }


@router.get("/correlate")
async def get_log_correlation(
    device_id: int,
    timestamp: str = Query(description="Target ISO timestamp"),
    window_minutes: int = Query(default=5, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _dev_authorized(device_id, current_user, db)
    try:
        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.datetime.utcnow()

    start_t = dt - datetime.timedelta(minutes=window_minutes)
    end_t = dt + datetime.timedelta(minutes=window_minutes)

    snapshots = (await db.execute(
        select(MetricSnapshot).where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= start_t, MetricSnapshot.timestamp <= end_t)
        .order_by(MetricSnapshot.timestamp.asc())
    )).scalars().all()

    alerts = (await db.execute(
        select(Alert).where(Alert.device_id == device_id, Alert.timestamp >= start_t, Alert.timestamp <= end_t)
        .order_by(Alert.timestamp.desc())
    )).scalars().all()

    return {
        "device_id": device_id, "target_timestamp": timestamp, "window_minutes": window_minutes,
        "metrics_at_timestamp": snapshots[0].metrics if snapshots else connection_manager.latest_metrics.get(device_id, {}),
        "events": connection_manager.device_events.get(device_id, [])[:50],
        "processes": connection_manager.device_processes.get(device_id, [])[:30],
        "alerts": alerts,
    }
