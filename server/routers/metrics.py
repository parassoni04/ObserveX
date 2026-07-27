import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, MetricSnapshot
from server.schemas import MetricSnapshotOut, MetricHistoryResponse, MetricSummaryResponse

router = APIRouter(prefix="/api/v1/devices/{device_id}/metrics", tags=["metrics"])


@router.get("/latest", response_model=MetricSnapshotOut | None)
async def get_latest_metric(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get the most recent metric snapshot for a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.device_id == device_id)
        .order_by(desc(MetricSnapshot.timestamp))
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        return None
    return snapshot


@router.get("", response_model=MetricHistoryResponse)
async def get_metric_history(
    device_id: int,
    minutes: int = Query(default=60, ge=1, le=10080, description="Look-back window in minutes"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Get historical metric snapshots within a time window."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)

    result = await db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= since)
        .order_by(desc(MetricSnapshot.timestamp))
        .limit(limit)
    )
    snapshots = result.scalars().all()

    return MetricHistoryResponse(
        device_id=device_id,
        count=len(snapshots),
        snapshots=snapshots,
    )


@router.get("/summary", response_model=MetricSummaryResponse)
async def get_metric_summary(
    device_id: int,
    minutes: int = Query(default=60, ge=1, le=10080),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated metric stats (avg/max) over a time range.

    Because metrics are stored as JSON, we extract values via SQL JSON operators.
    For PostgreSQL, we use ->> to get text and cast to float.
    """
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)

    # Use raw SQL for JSON extraction aggregation (PostgreSQL specific)
    from sqlalchemy import text

    if "sqlite" in str(db.bind.url if db.bind else ""):
        query = text("""
            SELECT
                COUNT(*) as snapshot_count,
                AVG(json_extract(metrics, '$.cpu_usage')) as avg_cpu,
                MAX(json_extract(metrics, '$.cpu_usage')) as max_cpu,
                AVG(json_extract(metrics, '$.ram_usage_percent')) as avg_ram,
                MAX(json_extract(metrics, '$.ram_usage_percent')) as max_ram,
                AVG(json_extract(metrics, '$.gpu_usage')) as avg_gpu,
                MAX(json_extract(metrics, '$.gpu_usage')) as max_gpu
            FROM metric_snapshots
            WHERE device_id = :device_id AND timestamp >= :since
        """)
    else:
        query = text("""
            SELECT
                COUNT(*) as snapshot_count,
                AVG((metrics->>'cpu_usage')::float) as avg_cpu,
                MAX((metrics->>'cpu_usage')::float) as max_cpu,
                AVG((metrics->>'ram_usage_percent')::float) as avg_ram,
                MAX((metrics->>'ram_usage_percent')::float) as max_ram,
                AVG((metrics->>'gpu_usage')::float) as avg_gpu,
                MAX((metrics->>'gpu_usage')::float) as max_gpu
            FROM metric_snapshots
            WHERE device_id = :device_id AND timestamp >= :since
        """)

    result = await db.execute(query, {"device_id": device_id, "since": since})
    row = result.fetchone()

    return MetricSummaryResponse(
        device_id=device_id,
        period_minutes=minutes,
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
):
    """Get statistical trend analysis (min, max, avg, slope) for a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    period_minutes = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080}[period]
    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=period_minutes)

    result = await db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= since)
        .order_by(MetricSnapshot.timestamp.asc())
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return {
            "device_id": device_id,
            "period": period,
            "snapshot_count": 0,
            "cpu_avg": 0, "cpu_min": 0, "cpu_max": 0, "cpu_trend_slope": 0,
            "ram_avg": 0, "ram_min": 0, "ram_max": 0,
            "disk_read_max": 0, "disk_write_max": 0,
            "net_download_max": 0, "net_upload_max": 0
        }

    cpus = [s.metrics.get("cpu_usage", 0) for s in snapshots if "cpu_usage" in s.metrics]
    rams = [s.metrics.get("ram_usage_percent", 0) for s in snapshots if "ram_usage_percent" in s.metrics]
    disk_reads = [s.metrics.get("disk_read_speed", 0) for s in snapshots]
    disk_writes = [s.metrics.get("disk_write_speed", 0) for s in snapshots]
    net_down = [s.metrics.get("net_download_speed", 0) for s in snapshots]
    net_up = [s.metrics.get("net_upload_speed", 0) for s in snapshots]

    # Calculate slope: difference between first half avg and second half avg
    slope = 0.0
    if len(cpus) >= 4:
        half = len(cpus) // 2
        first_half_avg = sum(cpus[:half]) / half
        second_half_avg = sum(cpus[half:]) / (len(cpus) - half)
        slope = round(second_half_avg - first_half_avg, 2)

    return {
        "device_id": device_id,
        "period": period,
        "snapshot_count": len(snapshots),
        "cpu_avg": round(sum(cpus) / len(cpus), 1) if cpus else 0,
        "cpu_min": round(min(cpus), 1) if cpus else 0,
        "cpu_max": round(max(cpus), 1) if cpus else 0,
        "cpu_trend_slope": slope,
        "ram_avg": round(sum(rams) / len(rams), 1) if rams else 0,
        "ram_min": round(min(rams), 1) if rams else 0,
        "ram_max": round(max(rams), 1) if rams else 0,
        "disk_read_max": round(max(disk_reads), 1) if disk_reads else 0,
        "disk_write_max": round(max(disk_writes), 1) if disk_writes else 0,
        "net_download_max": round(max(net_down), 1) if net_down else 0,
        "net_upload_max": round(max(net_up), 1) if net_up else 0,
    }


@router.get("/correlate")
async def get_log_correlation(
    device_id: int,
    timestamp: str = Query(description="Target ISO timestamp or time string"),
    window_minutes: int = Query(default=5, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
):
    """Correlate metrics, Windows event logs, and processes around a specific target timestamp."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.datetime.utcnow()

    start_t = dt - datetime.timedelta(minutes=window_minutes)
    end_t = dt + datetime.timedelta(minutes=window_minutes)

    # Fetch metric snapshots in window
    result = await db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.device_id == device_id,
            MetricSnapshot.timestamp >= start_t,
            MetricSnapshot.timestamp <= end_t
        )
        .order_by(MetricSnapshot.timestamp.asc())
    )
    snapshots = result.scalars().all()

    # Get cached processes and events from WebSocket hub
    from server.websockets.hub import connection_manager
    cached_events = connection_manager.device_events.get(device_id, [])
    cached_procs = connection_manager.device_processes.get(device_id, [])

    # Fetch historic alerts in window
    from server.models import Alert
    alert_res = await db.execute(
        select(Alert)
        .where(
            Alert.device_id == device_id,
            Alert.timestamp >= start_t,
            Alert.timestamp <= end_t
        )
        .order_by(Alert.timestamp.desc())
    )
    alerts = alert_res.scalars().all()

    closest_metrics = snapshots[0].metrics if snapshots else connection_manager.latest_metrics.get(device_id, {})

    return {
        "device_id": device_id,
        "target_timestamp": timestamp,
        "window_minutes": window_minutes,
        "metrics_at_timestamp": closest_metrics,
        "events": cached_events[:50],
        "processes": cached_procs[:30],
        "alerts": alerts,
    }
