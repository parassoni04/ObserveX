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
