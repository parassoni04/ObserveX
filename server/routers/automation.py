import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import AlertRule, Incident, MaintenanceTask, Device
from server.schemas import (
    AlertRuleCreateRequest,
    AlertRuleOut,
    IncidentOut,
    ActionDispatchPayload,
    MaintenanceTaskOut,
)
from server.websockets.hub import connection_manager

router = APIRouter(prefix="/api/v1/automation", tags=["automation"])


# ── Alert Rules Endpoints ──

@router.get("/rules", response_model=list[AlertRuleOut])
async def get_alert_rules(
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List all alert rules (filtered optionally by device_id)."""
    stmt = select(AlertRule).order_by(desc(AlertRule.id))
    if device_id is not None:
        stmt = stmt.where((AlertRule.device_id == device_id) | (AlertRule.device_id == None))

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(req: AlertRuleCreateRequest, db: AsyncSession = Depends(get_db)):
    """Create a new intelligent alert rule."""
    if req.device_id:
        dev = await db.get(Device, req.device_id)
        if not dev:
            raise HTTPException(status_code=404, detail="Target device not found")

    rule = AlertRule(
        device_id=req.device_id,
        name=req.name,
        metric_name=req.metric_name,
        operator=req.operator,
        threshold_value=req.threshold_value,
        duration_seconds=req.duration_seconds,
        severity=req.severity,
        action_type=req.action_type,
        action_target=req.action_target,
        enabled=req.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an alert rule."""
    rule = await db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    await db.delete(rule)
    await db.commit()
    return {"status": "ok", "deleted_rule_id": rule_id}


# ── Incident History Endpoints ──

@router.get("/incidents", response_model=list[IncidentOut])
async def get_incidents(
    device_id: int | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve incident audit logs."""
    stmt = select(Incident).order_by(desc(Incident.triggered_at)).limit(limit)

    if device_id is not None:
        stmt = stmt.where(Incident.device_id == device_id)
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve_incident(incident_id: int, db: AsyncSession = Depends(get_db)):
    """Mark an open incident as resolved."""
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident.status = "resolved"
    incident.resolved_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(incident)
    return incident


# ── Remote Action Trigger Endpoint ──

@router.post("/trigger-action")
async def trigger_remote_action(payload: ActionDispatchPayload, db: AsyncSession = Depends(get_db)):
    """Dispatch an automated IT remediation command (service restart, temp cleanup, process kill) to an agent."""
    dev = await db.get(Device, payload.device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    cmd_payload = {
        "type": "command",
        "action": payload.action_type,
        "target": payload.target,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }

    # Dispatch to agent over WebSocket
    sent = await connection_manager.send_agent_command(payload.device_id, cmd_payload)

    # Log Incident entry
    incident = Incident(
        device_id=payload.device_id,
        title=f"Manual Trigger: {payload.action_type} ({payload.target or 'System'})",
        severity="info",
        status="auto_remediated" if sent else "open",
        action_taken=payload.action_type,
        log_output=f"Command sent via WebSocket (Online={sent})",
        triggered_at=datetime.datetime.utcnow(),
        resolved_at=datetime.datetime.utcnow() if sent else None,
    )
    db.add(incident)
    await db.commit()

    return {
        "status": "ok" if sent else "queued_offline",
        "sent_to_agent": sent,
        "incident_id": incident.id,
    }


# ── Maintenance Tasks Endpoints ──

@router.get("/maintenance", response_model=list[MaintenanceTaskOut])
async def get_maintenance_tasks(
    device_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve maintenance reminders and scheduled cleanup tasks."""
    stmt = select(MaintenanceTask).order_by(MaintenanceTask.id)
    if device_id is not None:
        stmt = stmt.where((MaintenanceTask.device_id == device_id) | (MaintenanceTask.device_id == None))

    result = await db.execute(stmt)
    tasks = result.scalars().all()

    # Seed default tasks if empty
    if not tasks:
        t1 = MaintenanceTask(title="Weekly Temporary File & Cache Cleanup", task_type="temp_cleanup", frequency="weekly", enabled=True)
        t2 = MaintenanceTask(title="Monthly Windows Event Log Rotation", task_type="log_rotate", frequency="monthly", enabled=True)
        db.add_all([t1, t2])
        await db.commit()
        result = await db.execute(stmt)
        tasks = result.scalars().all()

    return tasks
