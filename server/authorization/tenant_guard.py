"""
Tenant Guard — Centralized Multi-Tenant Isolation
==================================================

Provides FastAPI dependencies that enforce organization boundaries.
Instead of each router duplicating `if user.organization_id:` checks,
these reusable dependencies centralize the logic.

TenantGuard: Injectable dependency that ensures a resource belongs
             to the current user's organization.
require_admin: Shorthand dependency for admin-only endpoints.
require_same_org: Validates that a target org matches the user's org.

Usage:
    @router.get("/devices/{device_id}")
    async def get_device(
        device_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        device = await TenantGuard.get_or_404(Device, device_id, current_user, db)
        ...
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import User, Device
from server.auth.dependencies import get_current_user
from server.database import get_db
from server.logging import get_logger

logger = get_logger("tenant_guard")


class TenantGuard:
    """Centralized tenant isolation helpers."""

    @staticmethod
    async def get_or_404(
        model_cls,
        resource_id: int,
        user: User,
        db: AsyncSession,
    ):
        """
        Fetch a resource by ID and verify it belongs to the user's organization.

        Returns the resource if authorized.
        Raises 404 if not found or cross-org (never 403, to avoid leaking existence).

        The model_cls must have an 'organization_id' attribute.
        """
        resource = await db.get(model_cls, resource_id)
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        if hasattr(resource, "organization_id"):
            if resource.organization_id != user.organization_id:
                logger.warning(
                    "Tenant isolation: user=%s (org=%s) denied access to %s=%s (org=%s)",
                    user.id, user.organization_id,
                    model_cls.__name__, resource_id,
                    resource.organization_id,
                )
                raise HTTPException(status_code=404, detail="Resource not found")

        return resource

    @staticmethod
    def org_filter(query, user: User, model_cls=None):
        """
        Apply organization filter to a SQLAlchemy query.

        Usage:
            stmt = select(Device).order_by(Device.hostname)
            stmt = TenantGuard.org_filter(stmt, current_user, Device)
        """
        target = model_cls or Device
        if hasattr(target, "organization_id"):
            return query.where(target.organization_id == user.organization_id)
        return query


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency — raises 403 if user is not admin."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


async def require_same_org(
    target_org_id: int,
    current_user: User = Depends(get_current_user),
) -> bool:
    """Verify that a target organization matches the current user's org."""
    if current_user.organization_id != target_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access resources in another organization",
        )
    return True
