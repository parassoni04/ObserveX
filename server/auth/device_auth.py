"""
Device/Agent Credential Verification
=====================================

Verifies agent credentials (API keys) against the stored bcrypt hash
in the Device record. Used by both HTTP endpoints and WebSocket
authentication.

Key security decisions:
- Only bcrypt hash comparison is supported. The legacy plaintext
  api_key fallback has been removed entirely from the new architecture.
- Revoked devices are always rejected.
- Returns the Device ORM object on success for the caller to use
  the authenticated identity.
"""
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from server.models import Device
from server.logging import get_logger

logger = get_logger("device_auth")


async def verify_device_credential(
    device_id: int,
    credential: str,
    db: AsyncSession,
) -> Device | None:
    """
    Verify an agent's credential against the device's stored hash.

    Args:
        device_id: The claimed device ID.
        credential: The raw API key sent by the agent.
        db: Database session.

    Returns:
        The authenticated Device on success, None on failure.

    Security:
        - Never raises exceptions for auth failures (returns None).
        - Logs warnings for failed attempts.
        - Rejects revoked devices.
    """
    device = await db.get(Device, device_id)
    if not device:
        logger.warning("Device auth failed: device_id=%s not found", device_id)
        return None

    if device.status == "revoked":
        logger.warning("Device auth failed: device_id=%s is revoked", device_id)
        return None

    if not device.api_key_hash:
        logger.warning("Device auth failed: device_id=%s has no credential hash", device_id)
        return None

    try:
        if bcrypt.checkpw(credential.encode("utf-8"), device.api_key_hash.encode("utf-8")):
            return device
    except Exception as e:
        logger.error("Device auth error: device_id=%s: %s", device_id, e)

    logger.warning("Device auth failed: invalid credential for device_id=%s", device_id)
    return None
