"""
Device-Level Access Control
============================

Determines whether a specific user can access a specific device.
This is the core RBAC check used throughout the platform.

Access rules:
1. The device must be in the same organization as the user (always).
2. Admins can access any device in their organization.
3. Regular users can only access devices assigned to them via
   DeviceUserAssignment.

Cross-organization access is ALWAYS denied, regardless of role.
This is the primary tenant isolation boundary for device resources.
"""
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import User, Device, DeviceUserAssignment
from server.logging import get_logger

logger = get_logger("authorization")


async def check_device_access(user: User, device_id: int, db: AsyncSession) -> bool:
    """
    Check if a user has access to a specific device.

    Returns True if the user is authorized, False otherwise.
    Never raises — callers should convert False to 404 (not 403)
    to avoid leaking resource existence.
    """
    device = await db.get(Device, device_id)
    if not device:
        return False

    # Hard boundary: organization isolation
    if device.organization_id != user.organization_id:
        logger.warning(
            "Cross-org access denied: user=%s (org=%s) → device=%s (org=%s)",
            user.id, user.organization_id, device_id, device.organization_id,
        )
        return False

    # Admins can access any device in their org
    if user.role == "admin":
        return True

    # Regular users: check assignment table
    result = await db.execute(
        select(exists().where(
            DeviceUserAssignment.device_id == device_id,
            DeviceUserAssignment.user_id == user.id,
        ))
    )
    return result.scalar()


async def get_accessible_device_ids(user: User, db: AsyncSession) -> list[int] | None:
    """
    Get the list of device IDs accessible to a user.

    Returns:
        None for admins (meaning "all devices in their org" — the caller
        should apply org filtering).
        A list of specific device IDs for regular users.
    """
    if user.role == "admin":
        return None  # Caller applies org filter

    result = await db.execute(
        select(DeviceUserAssignment.device_id).where(
            DeviceUserAssignment.user_id == user.id,
        )
    )
    return list(result.scalars().all())
