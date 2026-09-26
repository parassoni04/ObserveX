"""
Enrollment Service
==================

Business logic for the enrollment flow. Separated from the router
so that the same logic can be called from multiple entry points
(enrollment router, agent router convenience alias, etc.).
"""
import datetime
import secrets
import uuid
from typing import Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import EnrollmentCode, Device, Organization
from server.logging import get_logger

logger = get_logger("enrollment_service")


def generate_enrollment_code() -> str:
    """Generate a human-friendly enrollment code like OX-7F29-A82D."""
    part1 = secrets.token_hex(2).upper()
    part2 = secrets.token_hex(2).upper()
    return f"OX-{part1}-{part2}"


async def validate_enrollment_code(
    code: str, db: AsyncSession
) -> tuple[Optional[EnrollmentCode], Optional[str]]:
    """
    Validate an enrollment code.

    Returns:
        (code_obj, None) on success.
        (None, error_message) on failure.
    """
    result = await db.execute(
        select(EnrollmentCode).where(EnrollmentCode.code == code)
    )
    code_obj = result.scalar_one_or_none()

    if not code_obj:
        return None, "Invalid enrollment code"

    if code_obj.is_revoked:
        return None, "Enrollment code has been revoked"

    if code_obj.is_expired:
        return None, "Enrollment code has expired"

    if code_obj.is_exhausted:
        return None, "Enrollment code has reached maximum uses"

    return code_obj, None


async def create_device_from_enrollment(
    code_obj: EnrollmentCode,
    hostname: str,
    os_name: Optional[str],
    os_version: Optional[str],
    db: AsyncSession,
) -> tuple[Device, str]:
    """
    Create a new device from a validated enrollment code.

    Returns:
        (device, raw_api_key) — the raw API key is returned ONCE and
        must be sent to the agent. The server only stores the hash.
    """
    device_uuid = str(uuid.uuid4())
    raw_api_key = secrets.token_urlsafe(32)
    api_key_hash = bcrypt.hashpw(
        raw_api_key.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    device = Device(
        device_uuid=device_uuid,
        hostname=hostname,
        os_name=os_name,
        os_version=os_version,
        api_key_hash=api_key_hash,
        status="pending",
        organization_id=code_obj.organization_id,
        registered_at=datetime.datetime.utcnow(),
        last_seen=datetime.datetime.utcnow(),
        is_online=False,
    )
    db.add(device)

    # Increment usage count
    code_obj.usage_count += 1

    await db.commit()
    await db.refresh(device)

    logger.info(
        "Device enrolled: id=%s uuid=%s hostname=%s org=%s",
        device.id, device_uuid, hostname, code_obj.organization_id,
    )

    return device, raw_api_key


async def get_org_name(organization_id: int, db: AsyncSession) -> str:
    """Get the organization name for enrollment responses."""
    org = await db.get(Organization, organization_id)
    return org.name if org else "Unknown Organization"
