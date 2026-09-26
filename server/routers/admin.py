"""
Admin Router
=============

Admin-only endpoints for user management, organization overview,
device management, and audit log access.

All operations are scoped to the admin's organization using the
TenantGuard pattern — no inline org checks.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Organization, Device, AuditLog
from server.schemas.user import UserOut, UserCreateAdmin, UserUpdateAdmin
from server.schemas.organization import OrganizationOut, OrgOverviewResponse
from server.schemas.alert import AuditLogOut
from server.auth import hash_password
from server.authorization import require_admin, TenantGuard
from server.websockets.manager import connection_manager
from server.security import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview", response_model=OrgOverviewResponse)
async def get_admin_overview(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Organization overview — scoped to admin's org."""
    org_id = admin_user.organization_id

    total_users = (await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id)
    )).scalar() or 0

    admin_count = (await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.role == "admin")
    )).scalar() or 0

    total_devices = (await db.execute(
        select(func.count(Device.id)).where(Device.organization_id == org_id)
    )).scalar() or 0

    online_devices = (await db.execute(
        select(func.count(Device.id)).where(Device.organization_id == org_id, Device.is_online == True)
    )).scalar() or 0

    org = await db.get(Organization, org_id)
    org_name = org.name if org else "ObserveX Enterprise"

    scores = [
        m["health_score"] for m in connection_manager.latest_metrics.values()
        if "health_score" in m
    ]

    return OrgOverviewResponse(
        organization_name=org_name,
        total_users=total_users,
        total_devices=total_devices,
        online_devices=online_devices,
        offline_devices=max(0, total_devices - online_devices),
        admin_count=admin_count,
        avg_health_score=round(sum(scores) / len(scores), 1) if scores else 100.0,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List users — scoped to admin's organization."""
    stmt = (
        select(User)
        .where(User.organization_id == admin_user.organization_id)
        .order_by(User.username)
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    req: UserCreateAdmin,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Create a user — forced to admin's organization for isolation."""
    existing = (await db.execute(
        select(User).where(or_(User.email == req.email.lower().strip(), User.username == req.username.strip()))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email or username already exists")

    user = User(
        email=req.email.lower().strip(),
        username=req.username.strip(),
        full_name=req.full_name,
        hashed_password=hash_password(req.password),
        role=req.role if req.role in ("admin", "user") else "user",
        is_active=True,
        organization_id=admin_user.organization_id,  # Always forced to admin's org
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("User created by admin: user_id=%s username=%s by admin=%s", user.id, user.username, admin_user.id)
    await log_audit(
        ACTIONS["USER_CREATED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="user", target_id=str(user.id),
        detail=f"username={user.username} role={user.role}",
    )
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user_admin(
    user_id: int,
    req: UserUpdateAdmin,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Update a user — must be in admin's organization."""
    user = await TenantGuard.get_or_404(User, user_id, admin_user, db)

    if req.role is not None and req.role in ("admin", "user"):
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active

    await db.commit()
    await db.refresh(user)

    logger.info("User updated by admin: user_id=%s by admin=%s", user_id, admin_user.id)
    await log_audit(
        ACTIONS["USER_UPDATED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="user", target_id=str(user_id),
        detail=f"fields={req.model_dump(exclude_none=True)}",
    )
    return user


@router.delete("/users/{user_id}")
async def delete_user_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Delete a user — must be in admin's organization."""
    user = await TenantGuard.get_or_404(User, user_id, admin_user, db)

    await db.delete(user)
    await db.commit()

    logger.info("User deleted by admin: user_id=%s by admin=%s", user_id, admin_user.id)
    await log_audit(
        ACTIONS["USER_DELETED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="user", target_id=str(user_id),
    )
    return {"status": "deleted", "user_id": user_id}


@router.get("/audit-log", response_model=list[AuditLogOut])
async def get_audit_log(
    action: Optional[str] = Query(default=None),
    actor_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Query audit logs (admin only). Scoped to admin's organization."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == admin_user.organization_id)
        .order_by(desc(AuditLog.timestamp))
        .limit(limit)
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)

    return (await db.execute(stmt)).scalars().all()
