"""
Alerts & Alert Rules Router
============================

Endpoints for managing alert rules and viewing alert history.
All operations are scoped to the user's organization.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import Alert, AlertRule, User
from server.schemas.alert import AlertOut, AlertRuleCreateRequest, AlertRuleOut
from server.auth import get_current_user
from server.authorization import require_admin, TenantGuard
from server.logging import get_logger

logger = get_logger("alerts")

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    device_id: int = Query(default=None),
    severity: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent alerts — scoped to user's organization."""
    stmt = (
        select(Alert)
        .where(Alert.organization_id == current_user.organization_id)
        .order_by(desc(Alert.timestamp))
        .limit(limit)
    )
    if device_id:
        stmt = stmt.where(Alert.device_id == device_id)
    if severity:
        stmt = stmt.where(Alert.severity == severity)

    return (await db.execute(stmt)).scalars().all()


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_alert_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List alert rules — scoped to user's organization."""
    stmt = (
        select(AlertRule)
        .where(AlertRule.organization_id == current_user.organization_id)
        .order_by(AlertRule.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    req: AlertRuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Create a new alert rule (admin only)."""
    rule = AlertRule(
        organization_id=admin_user.organization_id,
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

    logger.info("Alert rule created: id=%s name=%s by admin=%s", rule.id, rule.name, admin_user.id)
    return rule


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def update_alert_rule(
    rule_id: int,
    req: AlertRuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Update an alert rule (admin only)."""
    rule = await TenantGuard.get_or_404(AlertRule, rule_id, admin_user, db)

    for field in ["name", "metric_name", "operator", "threshold_value", "duration_seconds",
                   "severity", "action_type", "action_target", "enabled", "device_id"]:
        val = getattr(req, field, None)
        if val is not None:
            setattr(rule, field, val)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Delete an alert rule (admin only)."""
    rule = await TenantGuard.get_or_404(AlertRule, rule_id, admin_user, db)
    await db.delete(rule)
    await db.commit()
    return {"status": "deleted", "rule_id": rule_id}
