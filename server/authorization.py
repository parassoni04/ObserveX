"""
ObserveX Server — Device-Level Authorization.

Centralized helpers for checking whether a user has access to a device.
Admins have access to all devices. Regular users only see devices
assigned to them via the DeviceUserAssignment table (or legacy assigned_user_id).
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Device, DeviceUserAssignment
from server.auth import get_current_user


async def check_device_access(user: User, device_id: int, db: AsyncSession) -> bool:
    """
    Check if a user has access to a specific device.

    Returns True if:
      - User is admin, OR
      - Device is assigned to user via DeviceUserAssignment, OR
      - Device.assigned_user_id == user.id (legacy)
    """
    if user.role == "admin":
        return True

    # Check many-to-many assignment
    result = await db.execute(
        select(exists().where(
            DeviceUserAssignment.device_id == device_id,
            DeviceUserAssignment.user_id == user.id,
        ))
    )
    if result.scalar():
        return True

    # Legacy fallback: check direct FK
    device = await db.get(Device, device_id)
    if device and device.assigned_user_id == user.id:
        return True

    return False


async def get_accessible_device_ids(user: User, db: AsyncSession) -> list[int] | None:
    """
    Get the list of device IDs accessible to a user.

    Returns None for admins (meaning all devices).
    Returns a list of device IDs for regular users.
    """
    if user.role == "admin":
        return None  # Admin sees all

    # Many-to-many assignments
    result = await db.execute(
        select(DeviceUserAssignment.device_id).where(
            DeviceUserAssignment.user_id == user.id
        )
    )
    assigned_ids = set(result.scalars().all())

    # Legacy FK assignments
    result = await db.execute(
        select(Device.id).where(Device.assigned_user_id == user.id)
    )
    legacy_ids = set(result.scalars().all())

    return list(assigned_ids | legacy_ids)


async def require_device_access(
    device_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — raises 403 if user doesn't have access to the device.
    Returns the authenticated user on success.
    """
    has_access = await check_device_access(current_user, device_id, db)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this device",
        )
    return current_user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency — raises 403 if user is not admin."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
