"""
Background Tasks
================

Long-running async tasks that run in the background during the
server's lifecycle. Started from main.py lifespan.

cleanup: Delete old metric snapshots based on retention policy
health_check: Tri-state device health state machine
alert_evaluator: Evaluate alert rules against live telemetry
"""
import asyncio
import datetime
from sqlalchemy import delete, select, update

from server.database import get_session
from server.models import MetricSnapshot, Device, AlertRule, Alert, Incident
from server.config import settings
from server.logging import get_logger
from server.security.audit_logger import log_audit, ACTIONS

logger = get_logger("tasks")


async def cleanup_old_metrics():
    """Periodically delete metric snapshots older than the retention window."""
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=settings.METRIC_RETENTION_DAYS)
            async with get_session() as session:
                result = await session.execute(
                    delete(MetricSnapshot).where(MetricSnapshot.timestamp < cutoff)
                )
                if result.rowcount > 0:
                    logger.info("Deleted %s metric snapshots older than %s days", result.rowcount, settings.METRIC_RETENTION_DAYS)
                await session.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Cleanup error: %s", e)
        await asyncio.sleep(3600)


async def mark_stale_devices_offline():
    """
    Tri-state device health state machine:
      🟢 Online  → last_seen within HEARTBEAT_ONLINE_TIMEOUT
      🟡 Stale   → last_seen between ONLINE and STALE timeout
      🔴 Offline → last_seen beyond HEARTBEAT_STALE_TIMEOUT
    """
    online_timeout = settings.HEARTBEAT_ONLINE_TIMEOUT
    stale_timeout = settings.HEARTBEAT_STALE_TIMEOUT
    check_interval = settings.HEARTBEAT_CHECK_INTERVAL

    while True:
        try:
            now = datetime.datetime.utcnow()
            stale_cutoff = now - datetime.timedelta(seconds=online_timeout)
            offline_cutoff = now - datetime.timedelta(seconds=stale_timeout)

            async with get_session() as session:
                # Online → Stale
                stale_result = await session.execute(
                    update(Device)
                    .where(
                        Device.is_online == True,
                        Device.status == "active",
                        Device.last_seen < stale_cutoff,
                        Device.last_seen >= offline_cutoff,
                    )
                    .values(status="stale")
                )
                if stale_result.rowcount > 0:
                    logger.info("%s device(s) marked as stale", stale_result.rowcount)

                # Stale/Active → Offline
                offline_result = await session.execute(
                    update(Device)
                    .where(
                        Device.last_seen < offline_cutoff,
                        Device.status.in_(["active", "stale"]),
                    )
                    .values(is_online=False, status="offline")
                )
                if offline_result.rowcount > 0:
                    logger.info("%s device(s) marked as offline", offline_result.rowcount)

                # Legacy cleanup
                await session.execute(
                    update(Device)
                    .where(Device.is_online == True, Device.last_seen < offline_cutoff)
                    .values(is_online=False)
                )

                await session.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Health check error: %s", e)
        await asyncio.sleep(check_interval)


async def evaluate_alert_rules():
    """Periodically evaluate live telemetry against active AlertRules."""
    from server.websockets.manager import connection_manager

    ops = {
        ">": lambda v, t: v > t,
        "<": lambda v, t: v < t,
        "==": lambda v, t: abs(v - t) < 0.01,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
    }

    while True:
        try:
            async with get_session() as session:
                rules = (
                    await session.execute(
                        select(AlertRule).where(AlertRule.enabled == True)
                    )
                ).scalars().all()

                for rule in rules:
                    # Get target devices — either specific or all online in org
                    if rule.device_id:
                        target_ids = [rule.device_id]
                    else:
                        target_ids = connection_manager.get_online_device_ids_for_org(
                            rule.organization_id
                        )

                    check = ops.get(rule.operator)
                    if not check:
                        continue

                    for dev_id in target_ids:
                        metrics = connection_manager.latest_metrics.get(dev_id)
                        if not metrics or rule.metric_name not in metrics:
                            continue
                        try:
                            val = float(metrics[rule.metric_name])
                        except (ValueError, TypeError):
                            continue
                        if not check(val, float(rule.threshold_value)):
                            continue

                        now = datetime.datetime.utcnow()
                        msg = f"Rule '{rule.name}' triggered: {rule.metric_name} ({val:.1f}) {rule.operator} {rule.threshold_value:.1f}"

                        session.add(Alert(
                            device_id=dev_id,
                            organization_id=rule.organization_id,
                            alert_type=rule.metric_name,
                            severity=rule.severity,
                            title=rule.name,
                            message=msg,
                            timestamp=now,
                        ))

                        action_sent = False
                        if rule.action_type and rule.action_type != "notification":
                            if rule.action_type in settings.allowed_actions_set:
                                action_sent = await connection_manager.send_to_agent(dev_id, {
                                    "type": "command",
                                    "command_id": 0,
                                    "action": rule.action_type,
                                    "target": rule.action_target,
                                    "timestamp": now.isoformat(),
                                })
                                logger.info("Auto-remediation sent: rule=%s action=%s device=%s",
                                            rule.name, rule.action_type, dev_id)
                                await log_audit(
                                    ACTIONS["REMEDIATION_ISSUED"],
                                    actor_type="system",
                                    organization_id=rule.organization_id,
                                    target_type="device", target_id=str(dev_id),
                                    detail=f"Auto-rule: {rule.name} action={rule.action_type}",
                                    result="success" if action_sent else "error",
                                )
                            else:
                                logger.warning("Blocked auto-remediation: unpermitted action=%s",
                                               rule.action_type)

                        session.add(Incident(
                            device_id=dev_id,
                            organization_id=rule.organization_id,
                            rule_id=rule.id,
                            title=msg,
                            severity=rule.severity,
                            status="auto_remediated" if action_sent else "open",
                            action_taken=rule.action_type if action_sent else "notification",
                            triggered_at=now,
                            resolved_at=now if action_sent else None,
                        ))

                        # Broadcast alert to dashboards
                        await connection_manager.broadcast_alert_to_dashboards(dev_id, {
                            "alert_type": rule.metric_name,
                            "severity": rule.severity,
                            "title": rule.name,
                            "message": msg,
                            "device_id": dev_id,
                            "timestamp": now.isoformat(),
                        })

                await session.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Rule evaluation error: %s", e)
        await asyncio.sleep(10)
