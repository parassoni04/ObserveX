import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Device, MetricSnapshot
from server.schemas import AnomalyItem, FailureForecastResponse, RootCauseSuggestionItem, AIOpsHealthInsightsResponse
from server.aiops.engine import detect_anomalies, forecast_failure, suggest_root_cause, generate_ai_health_insights
from server.websockets.hub import connection_manager

router = APIRouter(prefix="/api/v1/aiops/{device_id}", tags=["aiops"])


async def _dev_snaps(device_id: int, db: AsyncSession, hours: int = 6) -> list[dict]:
    dev = await db.get(Device, device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    snaps = [
        {"timestamp": s.timestamp.isoformat(), "metrics": s.metrics}
        for s in (await db.execute(
            select(MetricSnapshot).where(MetricSnapshot.device_id == device_id, MetricSnapshot.timestamp >= cutoff)
            .order_by(desc(MetricSnapshot.timestamp)).limit(300)
        )).scalars().all()
    ]
    latest_ws = connection_manager.latest_metrics.get(device_id)
    if latest_ws:
        snaps.insert(0, {"timestamp": datetime.datetime.utcnow().isoformat(), "metrics": latest_ws})
    return snaps


@router.get("/anomalies", response_model=list[AnomalyItem])
async def get_device_anomalies(device_id: int, hours: int = Query(default=6, ge=1, le=168), db: AsyncSession = Depends(get_db)):
    return detect_anomalies(await _dev_snaps(device_id, db, hours=hours))


@router.get("/forecast", response_model=FailureForecastResponse)
async def get_device_failure_forecast(device_id: int, db: AsyncSession = Depends(get_db)):
    return forecast_failure(await _dev_snaps(device_id, db, hours=1))


@router.get("/root-cause", response_model=list[RootCauseSuggestionItem])
async def get_root_cause_suggestions(device_id: int, db: AsyncSession = Depends(get_db)):
    snaps = await _dev_snaps(device_id, db, hours=2)
    return suggest_root_cause(
        detect_anomalies(snaps),
        connection_manager.device_processes.get(device_id, []),
        connection_manager.device_events.get(device_id, []),
    )


@router.get("/health-insights", response_model=AIOpsHealthInsightsResponse)
async def get_aiops_health_insights(device_id: int, db: AsyncSession = Depends(get_db)):
    snaps = await _dev_snaps(device_id, db, hours=2)
    return generate_ai_health_insights(snaps, detect_anomalies(snaps), forecast_failure(snaps))
