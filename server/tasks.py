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
