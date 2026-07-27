from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Organization, Device
from server.schemas import (
    UserOut,
    UserCreateAdmin,
    UserUpdateAdmin,
    OrganizationOut,
    OrgOverviewResponse,
)
from server.auth import hash_password, require_role
from server.websockets.hub import connection_manager

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Guard all endpoints in this router to admin role only
admin_guard = Depends(require_role(["admin"]))


@router.get("/overview", response_model=OrgOverviewResponse, dependencies=[admin_guard])
async def get_admin_overview(db: AsyncSession = Depends(get_db)):
    """Enterprise admin overview stats."""
    # Count total users & admins
    total_users_res = await db.execute(select(func.count(User.id)))
    total_users = total_users_res.scalar() or 0

    admin_count_res = await db.execute(select(func.count(User.id)).where(User.role == "admin"))
    admin_count = admin_count_res.scalar() or 0

    # Count devices
    total_devices_res = await db.execute(select(func.count(Device.id)))
    total_devices = total_devices_res.scalar() or 0

    online_devices_res = await db.execute(select(func.count(Device.id)).where(Device.is_online == True))
    online_devices = online_devices_res.scalar() or 0
    offline_devices = max(0, total_devices - online_devices)

    # Org name
    org_res = await db.execute(select(Organization.name).limit(1))
    org_name = org_res.scalar() or "ObserveX Enterprise"

    # Compute aggregate health score across active live metrics
    health_scores = []
    for metrics in connection_manager.latest_metrics.values():
        if "health_score" in metrics:
            health_scores.append(metrics["health_score"])

    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else 100.0

    return OrgOverviewResponse(
        organization_name=org_name,
        total_users=total_users,
        total_devices=total_devices,
        online_devices=online_devices,
        offline_devices=offline_devices,
        admin_count=admin_count,
        avg_health_score=avg_health,
    )


@router.get("/users", response_model=list[UserOut], dependencies=[admin_guard])
async def list_users(db: AsyncSession = Depends(get_db)):
    """List all registered users in the system."""
    stmt = select(User).order_by(User.username)
    users = (await db.execute(stmt)).scalars().all()
    return users


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[admin_guard])
async def create_user_admin(req: UserCreateAdmin, db: AsyncSession = Depends(get_db)):
    """Admin endpoint to create a new user with specific role & org."""
    stmt = select(User).where(or_(User.email == req.email, User.username == req.username))
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email or username already exists")

    hashed = hash_password(req.password)
    user = User(
        email=req.email.lower().strip(),
        username=req.username.strip(),
        full_name=req.full_name,
        hashed_password=hashed,
        role=req.role if req.role in ["admin", "user"] else "user",
        is_active=True,
        organization_id=req.organization_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[admin_guard])
async def update_user_admin(user_id: int, req: UserUpdateAdmin, db: AsyncSession = Depends(get_db)):
    """Admin endpoint to update user role, status, or organization."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.role is not None and req.role in ["admin", "user"]:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.organization_id is not None:
        user.organization_id = req.organization_id

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", dependencies=[admin_guard])
async def delete_user_admin(user_id: int, db: AsyncSession = Depends(get_db)):
    """Admin endpoint to delete a user."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return {"status": "deleted", "user_id": user_id}


@router.get("/organizations", response_model=list[OrganizationOut], dependencies=[admin_guard])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    """List all organizations."""
    stmt = select(Organization).order_by(Organization.name)
    orgs = (await db.execute(stmt)).scalars().all()
    return orgs
