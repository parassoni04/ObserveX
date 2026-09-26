"""
Commands Router
===============

Endpoints for dispatching commands to agents and viewing command history.
All commands are validated against the server's allowlist before dispatch.
Every command is logged with full audit trail.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_db
from server.models import User, Device, CommandLog
from server.schemas.command import CommandDispatchRequest, CommandLogOut
from server.auth import get_current_user
from server.authorization import require_admin, check_device_access, TenantGuard
from server.config import settings
from server.websockets.manager import connection_manager
from server.security import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("commands")

router = APIRouter(prefix="/api/v1/commands", tags=["commands"])


@router.post("", response_model=CommandLogOut, status_code=status.HTTP_201_CREATED)
async def dispatch_command(
    req: CommandDispatchRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """
    Dispatch a command to a device (admin only).

    SECURITY:
    - Command type validated against server allowlist by schema validation
    - Device must be in admin's organization
    - Command is logged before dispatch for audit trail
    - Agent must be online to receive the command
    """
    # Verify device access
    device = await db.get(Device, req.device_id)
    if not device or device.organization_id != admin_user.organization_id:
        raise HTTPException(status_code=404, detail="Device not found")

    # Verify against server-side allowlist (belt-and-suspenders with schema validation)
    if req.command_type not in settings.allowed_actions_set:
        raise HTTPException(
            status_code=403,
            detail=f"Command type '{req.command_type}' is not permitted by server policy",
        )

    # Create command log (pending)
    cmd_log = CommandLog(
        organization_id=admin_user.organization_id,
        device_id=req.device_id,
        requested_by=admin_user.id,
        command_type=req.command_type,
        target=req.target,
        status="pending",
    )
    db.add(cmd_log)
    await db.commit()
    await db.refresh(cmd_log)

    # Attempt to send to agent
    if not connection_manager.is_agent_online(req.device_id):
        cmd_log.status = "failed"
        cmd_log.result_output = "Device is offline"
        cmd_log.completed_at = datetime.datetime.utcnow()
        await db.commit()
        await db.refresh(cmd_log)

        logger.warning("Command dispatch failed: device=%s is offline", req.device_id)
        await log_audit(
            ACTIONS["COMMAND_DISPATCHED"],
            actor_type="user", actor_id=str(admin_user.id),
            organization_id=admin_user.organization_id,
            target_type="device", target_id=str(req.device_id),
            detail=f"command={req.command_type} target={req.target} result=device_offline",
            result="error",
        )
        return cmd_log

    sent = await connection_manager.send_to_agent(req.device_id, {
        "type": "command",
        "command_id": cmd_log.id,
        "action": req.command_type,
        "target": req.target,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    })

    if sent:
        cmd_log.status = "sent"
    else:
        cmd_log.status = "failed"
        cmd_log.result_output = "Failed to send to agent"
        cmd_log.completed_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(cmd_log)

    logger.info(
        "Command dispatched: id=%s type=%s device=%s by=%s sent=%s",
        cmd_log.id, req.command_type, req.device_id, admin_user.id, sent,
    )
    await log_audit(
        ACTIONS["COMMAND_DISPATCHED"],
        actor_type="user", actor_id=str(admin_user.id),
        organization_id=admin_user.organization_id,
        target_type="device", target_id=str(req.device_id),
        detail=f"command_id={cmd_log.id} type={req.command_type} target={req.target}",
    )

    return cmd_log


@router.get("", response_model=list[CommandLogOut])
async def list_commands(
    device_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List command history — scoped to user's organization."""
    stmt = (
        select(CommandLog)
        .where(CommandLog.organization_id == current_user.organization_id)
        .order_by(desc(CommandLog.created_at))
        .limit(limit)
    )
    if device_id:
        stmt = stmt.where(CommandLog.device_id == device_id)
    return (await db.execute(stmt)).scalars().all()
