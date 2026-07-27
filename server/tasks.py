import asyncio
import datetime
from sqlalchemy import delete
import server.database as db
from server.models import MetricSnapshot, Device
from server.config import settings


async def cleanup_old_metrics():
    """Periodically delete metric snapshots older than the retention window."""
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=settings.METRIC_RETENTION_DAYS)
            async with db.async_session_factory() as session:
                result = await session.execute(
                    delete(MetricSnapshot).where(MetricSnapshot.timestamp < cutoff)
                )
                deleted = result.rowcount
                await session.commit()
                if deleted > 0:
                    print(f"[Cleanup] Deleted {deleted} metric snapshots older than {settings.METRIC_RETENTION_DAYS} days")
        except Exception as e:
            print(f"[Cleanup] Error: {e}")

        # Run every hour
        await asyncio.sleep(3600)


async def mark_stale_devices_offline():
    """Periodically mark devices as offline if they haven't sent a heartbeat recently."""
    while True:
        try:
            from sqlalchemy import select, update
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=30)
            async with db.async_session_factory() as session:
                await session.execute(
                    update(Device)
                    .where(Device.is_online == True, Device.last_seen < cutoff)
                    .values(is_online=False)
                )
                await session.commit()
        except Exception as e:
            print(f"[Stale Check] Error: {e}")

        # Run every 15 seconds
        await asyncio.sleep(15)


async def evaluate_alert_rules():
    """Periodically evaluate live telemetry metrics against active AlertRules."""
    from sqlalchemy import select
    from server.models import AlertRule, Incident, Alert
    from server.websockets.hub import connection_manager

    while True:
        try:
            async with db.async_session_factory() as session:
                rule_res = await session.execute(
                    select(AlertRule).where(AlertRule.enabled == True)
                )
                rules = rule_res.scalars().all()

                for rule in rules:
                    target_device_ids = [rule.device_id] if rule.device_id else connection_manager.get_online_device_ids()

                    for dev_id in target_device_ids:
                        metrics = connection_manager.latest_metrics.get(dev_id)
                        if not metrics or rule.metric_name not in metrics:
                            continue

                        val = float(metrics[rule.metric_name])
                        thresh = float(rule.threshold_value)
                        triggered = False

                        if rule.operator == ">" and val > thresh:
                            triggered = True
                        elif rule.operator == "<" and val < thresh:
                            triggered = True
                        elif rule.operator == "==" and abs(val - thresh) < 0.01:
                            triggered = True

                        if triggered:
                            msg = f"Rule '{rule.name}' triggered: {rule.metric_name} ({val:.1f}) {rule.operator} {thresh:.1f}"

                            alert = Alert(
                                device_id=dev_id,
                                alert_type=rule.metric_name,
                                severity=rule.severity,
                                message=msg,
                                timestamp=datetime.datetime.utcnow(),
                            )
                            session.add(alert)

                            action_sent = False
                            if rule.action_type != "notification":
                                cmd_payload = {
                                    "type": "command",
                                    "action": rule.action_type,
                                    "target": rule.action_target,
                                    "timestamp": datetime.datetime.utcnow().isoformat(),
                                }
                                action_sent = await connection_manager.send_agent_command(dev_id, cmd_payload)

                            inc = Incident(
                                device_id=dev_id,
                                rule_id=rule.id,
                                title=msg,
                                severity=rule.severity,
                                status="auto_remediated" if action_sent else "open",
                                action_taken=rule.action_type if action_sent else "notification",
                                log_output=f"Auto-triggered remediation: {rule.action_type} target={rule.action_target} (success={action_sent})",
                                triggered_at=datetime.datetime.utcnow(),
                                resolved_at=datetime.datetime.utcnow() if action_sent else None,
                            )
                            session.add(inc)

                await session.commit()
        except Exception as e:
            print(f"[Rule Engine] Error: {e}")

        await asyncio.sleep(10)

