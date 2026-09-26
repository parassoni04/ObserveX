"""
AIOps Router
============

Exposes the AIOps engine's statistical analysis as REST endpoints:
- Anomaly detection
- Failure forecasting
- Root cause analysis
- Health insights summary
"""
from fastapi import APIRouter, Depends, HTTPException
from server.auth import get_current_user
from server.models import User
from server.authorization import check_device_access
from server.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from server.websockets.manager import connection_manager
from server.services.aiops_engine import (
    detect_anomalies, forecast_failure,
    suggest_root_cause, generate_ai_health_insights,
)

router = APIRouter(prefix="/api/v1/aiops", tags=["aiops"])


@router.get("/{device_id}/anomalies")
async def get_anomalies(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")
    snapshots = connection_manager.metric_history.get(device_id, [])
    return detect_anomalies(snapshots)


@router.get("/{device_id}/forecast")
async def get_forecast(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")
    snapshots = connection_manager.metric_history.get(device_id, [])
    return forecast_failure(snapshots)


@router.get("/{device_id}/root-cause")
async def get_root_cause(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")
    snapshots = connection_manager.metric_history.get(device_id, [])
    anomalies = detect_anomalies(snapshots)
    processes = connection_manager.latest_processes.get(device_id, [])
    events = connection_manager.device_events.get(device_id, [])
    return suggest_root_cause(anomalies, processes, events)


@router.get("/{device_id}/insights")
async def get_insights(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await check_device_access(current_user, device_id, db):
        raise HTTPException(status_code=404, detail="Device not found")
    snapshots = connection_manager.metric_history.get(device_id, [])
    anomalies = detect_anomalies(snapshots)
    forecast = forecast_failure(snapshots)
    return generate_ai_health_insights(snapshots, anomalies, forecast)
