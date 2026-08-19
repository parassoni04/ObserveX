from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Organization, Device
from server.schemas import UserOut, UserCreateAdmin, UserUpdateAdmin, OrganizationOut, OrgOverviewResponse
from server.auth import hash_password, require_role
from server.websockets.hub import connection_manager

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
admin_guard = Depends(require_role(["admin"]))


@router.get("/overview", response_model=OrgOverviewResponse, dependencies=[admin_guard])
async def get_admin_overview(db: AsyncSession = Depends(get_db)):
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    admin_count = (await db.execute(select(func.count(User.id)).where(User.role == "admin"))).scalar() or 0
    total_devices = (await db.execute(select(func.count(Device.id)))).scalar() or 0
    online_devices = (await db.execute(select(func.count(Device.id)).where(Device.is_online == True))).scalar() or 0
    org_name = (await db.execute(select(Organization.name).limit(1))).scalar() or "ObserveX Enterprise"
    scores = [m["health_score"] for m in connection_manager.latest_metrics.values() if "health_score" in m]
    return OrgOverviewResponse(
        organization_name=org_name, total_users=total_users, total_devices=total_devices,
        online_devices=online_devices, offline_devices=max(0, total_devices - online_devices),
        admin_count=admin_count, avg_health_score=round(sum(scores) / len(scores), 1) if scores else 100.0,
    )


@router.get("/users", response_model=list[UserOut], dependencies=[admin_guard])
async def list_users(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(User).order_by(User.username))).scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[admin_guard])
async def create_user_admin(req: UserCreateAdmin, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(User).where(or_(User.email == req.email, User.username == req.username)))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email or username already exists")
    user = User(email=req.email.lower().strip(), username=req.username.strip(), full_name=req.full_name,
                hashed_password=hash_password(req.password), role=req.role if req.role in ("admin", "user") else "user",
                is_active=True, organization_id=req.organization_id)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[admin_guard])
async def update_user_admin(user_id: int, req: UserUpdateAdmin, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.role is not None and req.role in ("admin", "user"):
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
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"status": "deleted", "user_id": user_id}


@router.get("/organizations", response_model=list[OrganizationOut], dependencies=[admin_guard])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
