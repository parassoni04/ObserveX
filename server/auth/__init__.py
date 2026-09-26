"""
ObserveX Server — Auth Package.

Provides authentication and authorization infrastructure:
- passwords: bcrypt hashing and verification
- jwt_handler: JWT token creation and decoding
- dependencies: FastAPI dependency injection for auth
- device_auth: Agent/device credential verification
"""
from server.auth.passwords import hash_password, verify_password
from server.auth.jwt_handler import create_access_token, decode_access_token
from server.auth.dependencies import get_current_user, require_role
from server.auth.device_auth import verify_device_credential

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "require_role",
    "verify_device_credential",
]
