"""
Tests for Token Security, Password Storage, and Extended Auth Constraints.
==========================================================================

Verifies:
- JWT expiration, tampering, invalid signature, missing claims
- Inactive / deleted user token revocation check
- Bcrypt hash format and absence of plaintext in database
- Expiration of reset tokens and verification codes
- Max failed OTP attempt lockout
- Registration schema validation for missing fields
"""
import datetime
import time
import secrets
import jwt
import bcrypt
import pytest
from fastapi.testclient import TestClient

import server.database as db_module
from server.config import settings
from server.models import User, Organization
from server.auth.jwt_handler import create_access_token
from tests.conftest import TEST_PASSWORD, PASSWORD_HASH


def test_token_expired_rejected(client: TestClient, seed_data):
    """Token with past expiration timestamp is rejected with 401."""
    past_exp = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
    expired_token = jwt.encode(
        {"sub": str(seed_data["admin_a_id"]), "role": "admin", "org_id": seed_data["org_a_id"], "exp": past_exp},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_token_invalid_signature_rejected(client: TestClient, seed_data):
    """Token signed with an attacker's secret key is rejected with 401."""
    fake_token = jwt.encode(
        {"sub": str(seed_data["admin_a_id"]), "role": "admin", "org_id": seed_data["org_a_id"]},
        "malicious_unauthorized_secret_key_1234567890",
        algorithm="HS256",
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fake_token}"})
    assert resp.status_code == 401
    assert "could not validate credentials" in resp.json()["detail"].lower()


def test_token_tampered_payload_rejected(client: TestClient, seed_data):
    """Token with payload modified in transit without re-signing fails verification."""
    token = seed_data["headers_user_a1"]["Authorization"].split(" ")[1]
    header_b64, payload_b64, signature_b64 = token.split(".")
    # Tamper payload
    tampered_payload_b64 = "eyJzdWIiOiIxMDAwMDAwIiwicm9sZSI6ImFkbWluIn0"  # {"sub":"1000000","role":"admin"}
    tampered_token = f"{header_b64}.{tampered_payload_b64}.{signature_b64}"

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401


def test_token_missing_sub_rejected(client: TestClient, seed_data):
    """Token with missing 'sub' claim is rejected with 401."""
    token = jwt.encode(
        {"role": "admin", "org_id": seed_data["org_a_id"], "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "invalid token payload" in resp.json()["detail"].lower()


def test_token_non_integer_sub_rejected(client: TestClient, seed_data):
    """Token with non-numeric string in 'sub' claim is rejected with 401."""
    token = jwt.encode(
        {"sub": "not_an_int", "role": "admin", "org_id": seed_data["org_a_id"], "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_for_deactivated_user_rejected(client: TestClient, seed_data):
    """Token for an account that was deactivated after issuance is rejected with 401."""
    import asyncio
    async def _deactivate():
        async with db_module.async_session_factory() as session:
            user = await session.get(User, seed_data["user_a1_id"])
            user.is_active = False
            await session.commit()
    asyncio.run(_deactivate())

    resp = client.get("/api/v1/auth/me", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 401
    assert "inactive" in resp.json()["detail"].lower()


def test_password_bcrypt_format_and_no_plaintext(seed_data):
    """Verify that stored password is a valid bcrypt hash and never plaintext."""
    import asyncio
    async def _check():
        async with db_module.async_session_factory() as session:
            user = await session.get(User, seed_data["admin_a_id"])
            assert user.hashed_password is not None
            assert user.hashed_password.startswith("$2")
            assert TEST_PASSWORD not in user.hashed_password
            assert bcrypt.checkpw(TEST_PASSWORD.encode("utf-8"), user.hashed_password.encode("utf-8"))
    asyncio.run(_check())


def test_reset_password_expired_token(client: TestClient):
    """Expired password reset token is rejected with 400."""
    from server.routers.auth import _password_reset_store, _hash_reset_token

    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(raw_token)
    # Put an expired token in store
    _password_reset_store[token_hash] = {
        "user_id": 1,
        "expires_at": datetime.datetime.utcnow() - datetime.timedelta(minutes=10),
        "used": False,
    }

    resp = client.post("/api/v1/auth/reset-password", json={
        "token": raw_token,
        "new_password": "NewSecurePassword123!",
        "confirm_password": "NewSecurePassword123!",
    })
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_verification_code_expired(client: TestClient):
    """Expired verification code is rejected with 400."""
    from server.routers.auth import _verification_store

    email = "expired_code_test@example.com"
    _verification_store[email] = {
        "code": "123456",
        "expires_at": datetime.datetime.utcnow() - datetime.timedelta(minutes=5),
        "attempts": 0,
    }

    resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": "123456"})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_verification_code_max_attempts_lockout(client: TestClient):
    """Verification code is deleted after 5 failed attempts."""
    email = "lockout_test@example.com"
    send_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert send_resp.status_code == 200
    valid_code = send_resp.json()["dev_code"]

    # 4 incorrect attempts
    for _ in range(4):
        resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": "000000"})
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"].lower()

    # 5th incorrect attempt -> triggers lockout message
    resp5 = client.post("/api/v1/auth/verify-code", json={"email": email, "code": "000000"})
    assert resp5.status_code == 400
    assert "too many" in resp5.json()["detail"].lower()

    # Now even valid code fails because store entry was deleted
    resp_valid = client.post("/api/v1/auth/verify-code", json={"email": email, "code": valid_code})
    assert resp_valid.status_code == 400
    assert "no verification code found" in resp_valid.json()["detail"].lower()


def test_create_environment_missing_fields(client: TestClient):
    """Missing required fields in registration returns 422 Unprocessable Entity."""
    # Missing organization_name
    resp = client.post("/api/v1/auth/create-environment", json={
        "admin_email": "valid@email.com",
        "admin_username": "validuser",
        "admin_password": "ValidPassword123!",
    })
    assert resp.status_code == 422

    # Missing admin_username
    resp2 = client.post("/api/v1/auth/create-environment", json={
        "organization_name": "Valid Org",
        "admin_email": "valid@email.com",
        "admin_password": "ValidPassword123!",
    })
    assert resp2.status_code == 422

    # Missing admin_password
    resp3 = client.post("/api/v1/auth/create-environment", json={
        "organization_name": "Valid Org",
        "admin_email": "valid@email.com",
        "admin_username": "validuser",
    })
    assert resp3.status_code == 422
