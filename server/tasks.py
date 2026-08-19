import asyncio
import datetime
from sqlalchemy import delete, select, update
import server.database as db
from server.models import MetricSnapshot, Device, AlertRule, Incident, Alert
from server.config import settings


async def cleanup_old_metrics():
    """Periodically delete metric snapshots older than the retention window."""
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=settings.METRIC_RETENTION_DAYS)
            async with db.async_session_factory() as session:
                result = await session.execute(delete(MetricSnapshot).where(MetricSnapshot.timestamp < cutoff))
                if result.rowcount > 0:
                    print(f"[Cleanup] Deleted {result.rowcount} metric snapshots older than {settings.METRIC_RETENTION_DAYS} days")
                await session.commit()
        except Exception as e:
            print(f"[Cleanup] Error: {e}")
        await asyncio.sleep(3600)


async def mark_stale_devices_offline():
    """Periodically mark devices as offline if no recent heartbeat."""
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=30)
            async with db.async_session_factory() as session:
                await session.execute(update(Device).where(Device.is_online == True, Device.last_seen < cutoff).values(is_online=False))
                await session.commit()
        except Exception as e:
            print(f"[Stale Check] Error: {e}")
        await asyncio.sleep(15)


async def evaluate_alert_rules():
    """Periodically evaluate live telemetry against active AlertRules."""
    from server.websockets.hub import connection_manager
    ops = {">": lambda v, t: v > t, "<": lambda v, t: v < t, "==": lambda v, t: abs(v - t) < 0.01}

    while True:
        try:
            async with db.async_session_factory() as session:
                rules = (await session.execute(select(AlertRule).where(AlertRule.enabled == True))).scalars().all()
                for rule in rules:
                    target_ids = [rule.device_id] if rule.device_id else connection_manager.get_online_device_ids()
                    check = ops.get(rule.operator)
                    if not check:
                        continue
                    for dev_id in target_ids:
                        metrics = connection_manager.latest_metrics.get(dev_id)
                        if not metrics or rule.metric_name not in metrics:
                            continue
                        val = float(metrics[rule.metric_name])
                        if not check(val, float(rule.threshold_value)):
                            continue
                        now = datetime.datetime.utcnow()
                        msg = f"Rule '{rule.name}' triggered: {rule.metric_name} ({val:.1f}) {rule.operator} {rule.threshold_value:.1f}"
                        session.add(Alert(device_id=dev_id, alert_type=rule.metric_name, severity=rule.severity, message=msg, timestamp=now))
                        action_sent = False
                        if rule.action_type != "notification":
                            action_sent = await connection_manager.send_agent_command(dev_id, {
                                "type": "command", "action": rule.action_type, "target": rule.action_target, "timestamp": now.isoformat(),
                            })
                        session.add(Incident(
                            device_id=dev_id, rule_id=rule.id, title=msg, severity=rule.severity,
                            status="auto_remediated" if action_sent else "open",
                            action_taken=rule.action_type if action_sent else "notification",
                            log_output=f"Auto-triggered: {rule.action_type} target={rule.action_target} (success={action_sent})",
                            triggered_at=now, resolved_at=now if action_sent else None,
                        ))
                await session.commit()
        except Exception as e:
            print(f"[Rule Engine] Error: {e}")
        await asyncio.sleep(10)
