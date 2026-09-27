"""
Audit Logger
============

Fire-and-forget audit log writer. Records security-relevant events
to the audit_logs table. Must never crash the application — all
errors are caught and logged.

Usage:
    from server.security import log_audit, ACTIONS
    await log_audit(
        ACTIONS["LOGIN"],
        actor_type="user", actor_id=str(user.id),
        organization_id=user.organization_id,
        ip_address=client_ip,
    )
"""
import datetime
from typing import Optional
from server.models import AuditLog
from server.logging import get_logger

logger = get_logger("audit")

# Action constants — centralized action type definitions
ACTIONS = {
    "LOGIN": "user.login",
    "LOGIN_FAILED": "user.login_failed",
    "USER_CREATED": "user.created",
    "USER_UPDATED": "user.updated",
    "USER_DELETED": "user.deleted",
    "ENVIRONMENT_CREATED": "environment.created",
    "DEVICE_REGISTERED": "device.registered",
    "DEVICE_ENROLLED": "device.enrolled",
    "DEVICE_DELETED": "device.deleted",
    "DEVICE_ASSIGNED": "device.assigned",
    "DEVICE_UNASSIGNED": "device.unassigned",
    "DEVICE_REVOKED": "device.revoked",
    "AGENT_CONNECTED": "agent.connected",
    "AGENT_DISCONNECTED": "agent.disconnected",
    "AGENT_AUTH_FAILED": "agent.auth_failed",
    "DASHBOARD_CONNECTED": "dashboard.connected",
    "DASHBOARD_AUTH_FAILED": "dashboard.auth_failed",
    "COMMAND_DISPATCHED": "command.dispatched",
    "COMMAND_RESULT": "command.result",
    "REMEDIATION_ISSUED": "remediation.issued",
    "REMEDIATION_SUCCESS": "remediation.success",
    "REMEDIATION_FAILED": "remediation.failed",
    "ENROLLMENT_CODE_CREATED": "enrollment.code_created",
    "ENROLLMENT_CODE_REVOKED": "enrollment.code_revoked",
    "ENROLLMENT_FAILED": "enrollment.failed",
    "ACCESS_DENIED": "access.denied",
    "CREDENTIAL_REVOKED": "credential.revoked",
    "PASSWORD_RESET": "user.password_reset",
}


async def log_audit(
    action: str,
    *,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    result: str = "success",
    db_session=None,
):
    """
    Record an audit log entry. Fire-and-forget — never raises.

    Can be called with an existing db_session, or will create its own.
    """
    try:
        entry = AuditLog(
            timestamp=datetime.datetime.utcnow(),
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            organization_id=organization_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
            ip_address=ip_address,
            result=result,
        )

        if db_session:
            db_session.add(entry)
        else:
            from server.database import get_session
            async with get_session() as session:
                session.add(entry)
                await session.commit()

        logger.info(
            "AUDIT: action=%s actor=%s/%s target=%s/%s result=%s detail=%s",
            action, actor_type, actor_id, target_type, target_id, result,
            (detail or "")[:200],
        )
    except Exception as e:
        # Audit logging must never crash the application
        logger.error("Failed to write audit log: %s", e)
