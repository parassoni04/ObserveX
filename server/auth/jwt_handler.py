"""
JWT Token Handler
=================

Creates and decodes JWT access tokens for user authentication.
All JWT operations are centralized here so that algorithm, secret,
and expiration logic are never duplicated.

The token payload contains:
- sub: user ID (as string)
- role: user role
- org_id: organization ID
- exp: expiration timestamp
"""
import datetime
from typing import Optional
import jwt
from server.config import settings


def create_access_token(
    data: dict,
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        data: Payload dict. Must contain at minimum {"sub": str(user_id)}.
        expires_delta: Custom expiration. Defaults to config value.

    Returns:
        Encoded JWT string.
    """
    expire = datetime.datetime.utcnow() + (
        expires_delta or datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {**data, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Returns:
        Decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or invalid.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
