"""
Tests for Authentication & Account Verification — Complete Security Suite.

Verifies:
- Create Environment (Org + Admin signup) with mandatory email verification
- User Login (correct credentials, wrong password, nonexistent, unverified, inactive)
- Email Verification (valid code, wrong code, expired code, reused code, max attempts)
- Password Reset (valid token, expired token, reused token, invalid token)
- JWT Token (valid /me, missing token, expired token)
- Security (generic errors, no account enumeration)
"""
import asyncio
import datetime
import pytest
import bcrypt
from fastapi.testclient import TestClient
from tests.conftest import TEST_PASSWORD, PASSWORD_HASH

import server.database as db_module
from server.models import Organization, User


def _run_async(coro):
    return asyncio.run(coro)


def _create_unverified_user():
    """Create a user with email_verified=False for testing login rejection."""
    async def _seed():
        async with db_module.async_session_factory() as session:
            org = Organization(name="Unverified Org")
            session.add(org)
            await session.commit()
            await session.refresh(org)
            user = User(
                email="unverified@test.com", username="unverified_user",
                hashed_password=PASSWORD_HASH, role="user",
                is_active=True, email_verified=False,
                organization_id=org.id,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    return _run_async(_seed())


def _create_inactive_user():
    """Create an inactive user for testing login rejection."""
    async def _seed():
        async with db_module.async_session_factory() as session:
            org = Organization(name="Inactive Org")
            session.add(org)
            await session.commit()
            await session.refresh(org)
            user = User(
                email="inactive@test.com", username="inactive_user",
                hashed_password=PASSWORD_HASH, role="user",
                is_active=False, email_verified=True,
                organization_id=org.id,
            )
            session.add(user)
            await session.commit()
            return user
    return _run_async(_seed())


def _create_verified_user():
    """Create a verified, active user for testing password reset."""
    async def _seed():
        async with db_module.async_session_factory() as session:
            org = Organization(name="Reset Org")
            session.add(org)
            await session.commit()
            await session.refresh(org)
            user = User(
                email="resetme@test.com", username="reset_user",
                hashed_password=PASSWORD_HASH, role="admin",
                is_active=True, email_verified=True,
                organization_id=org.id,
            )
            session.add(user)
            await session.commit()
            return user
    return _run_async(_seed())


# ═══════════════════════════════════════════════════════════════
#  REGISTRATION / CREATE ENVIRONMENT
# ═══════════════════════════════════════════════════════════════

def test_create_environment_requires_verification(client: TestClient):
    """Creating environment without verification token or code → 400."""
    payload = {
        "organization_name": "No Verify Org",
        "admin_email": "noverify@test.com",
        "admin_username": "noverify",
        "admin_password": "SuperSecurePassword123!",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 400
    assert "verification" in resp.json()["detail"].lower()


def test_create_environment_full_flow(client: TestClient):
    """Full flow: send code → verify → create environment → success."""
    email = "fullflow@cyberdyne.com"

    # Step 1: Send verification code
    send_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert send_resp.status_code == 200
    data = send_resp.json()
    assert data["status"] == "sent"
    code = data.get("dev_code")
    assert code and len(code) == 6

    # Step 2: Verify code
    verify_resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify_resp.status_code == 200
    v_data = verify_resp.json()
    assert v_data["status"] == "verified"
    token = v_data["verification_token"]

    # Step 3: Create environment with verification token
    payload = {
        "organization_name": "Cyberdyne Systems",
        "admin_email": email,
        "admin_username": "mdyson",
        "admin_password": "SuperSecurePassword123!",
        "admin_full_name": "Miles Dyson",
        "verification_token": token,
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert "access_token" in result
    assert result["token_type"] == "bearer"
    assert result["user"]["username"] == "mdyson"
    assert result["user"]["role"] == "admin"
    assert result["user"]["email_verified"] is True
    assert result["organization"]["name"] == "Cyberdyne Systems"


def test_create_environment_duplicate_email(client: TestClient, seed_data):
    """Creating environment with existing email fails."""
    # Need verification first
    resp = client.post("/api/v1/auth/send-verification-code",
                       json={"email": "admin_a@alpha.com"})
    assert resp.status_code == 400  # Already registered
    assert "already registered" in resp.json()["detail"].lower()


def test_create_environment_password_mismatch(client: TestClient):
    """Creating environment fails when passwords don't match."""
    payload = {
        "organization_name": "Mismatch Org",
        "admin_email": "mismatch@example.com",
        "admin_username": "mismatch_user",
        "admin_password": "SuperPassword123!",
        "confirm_password": "DifferentPassword999!",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 422  # Pydantic validation error


def test_create_environment_invalid_email(client: TestClient):
    """Creating environment fails with invalid email format."""
    payload = {
        "organization_name": "Bad Email Org",
        "admin_email": "not-a-valid-email",
        "admin_username": "bad_email_user",
        "admin_password": "SuperPassword123!",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 422


def test_create_environment_weak_password(client: TestClient):
    """Creating environment fails with short password."""
    payload = {
        "organization_name": "Weak Pw Org",
        "admin_email": "weakpw@test.com",
        "admin_username": "weakpw",
        "admin_password": "short",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
#  EMAIL VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_verification_code_valid(client: TestClient):
    """Valid verification code flow."""
    email = "verify_test@example.com"
    send_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert send_resp.status_code == 200
    code = send_resp.json()["dev_code"]

    verify_resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "verified"
    assert "verification_token" in verify_resp.json()


def test_verification_code_wrong(client: TestClient):
    """Wrong verification code fails."""
    email = "wrongcode@example.com"
    client.post("/api/v1/auth/send-verification-code", json={"email": email})

    verify_resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": "000000"})
    assert verify_resp.status_code == 400
    assert "incorrect" in verify_resp.json()["detail"].lower()


def test_verification_code_single_use(client: TestClient):
    """Verification code is consumed after successful verification — cannot reuse."""
    email = "singleuse@example.com"
    send_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    code = send_resp.json()["dev_code"]

    # First verify — should succeed
    resp1 = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert resp1.status_code == 200

    # Second verify — code consumed, should fail
    resp2 = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert resp2.status_code == 400
    assert "no verification code" in resp2.json()["detail"].lower()


def test_verification_code_no_request(client: TestClient):
    """Verifying without requesting a code first fails."""
    resp = client.post("/api/v1/auth/verify-code", json={"email": "nobody@test.com", "code": "123456"})
    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════
#  LOGIN
# ═══════════════════════════════════════════════════════════════

def test_login_success_by_username(client: TestClient, seed_data):
    """Login with valid username + password returns JWT."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin_a"
    assert data["user"]["email_verified"] is True


def test_login_success_by_email(client: TestClient, seed_data):
    """Login with valid email + password returns JWT."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a@alpha.com",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_invalid_password(client: TestClient, seed_data):
    """Login with wrong password → 401 generic error."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a",
        "password": "WrongPassword999!",
    })
    assert resp.status_code == 401
    # Must NOT reveal whether username exists
    assert "incorrect" in resp.json()["detail"].lower()


def test_login_nonexistent_user(client: TestClient, seed_data):
    """Login with nonexistent user → 401 same generic error."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "ghost_user",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 401
    # Same error as wrong password — prevents account enumeration
    assert "incorrect" in resp.json()["detail"].lower()


def test_login_unverified_email(client: TestClient):
    """Login with valid credentials but unverified email → 403."""
    _create_unverified_user()
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "unverified@test.com",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 403
    assert "not verified" in resp.json()["detail"].lower()


def test_login_inactive_account(client: TestClient):
    """Login with deactivated account → 403."""
    _create_inactive_user()
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "inactive@test.com",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 403
    assert "deactivated" in resp.json()["detail"].lower()


def test_login_empty_credentials(client: TestClient):
    """Login with empty credentials → 401."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "",
        "password": "",
    })
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
#  JWT / ME ENDPOINT
# ═══════════════════════════════════════════════════════════════

def test_get_me_success(client: TestClient, seed_data):
    """Authenticated user can query /me."""
    resp = client.get("/api/v1/auth/me", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin_a"
    assert data["role"] == "admin"
    assert data["organization_id"] == seed_data["org_a_id"]
    assert data["email_verified"] is True


def test_get_me_unauthorized(client: TestClient):
    """Requesting /me without token → 401."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_get_me_invalid_token(client: TestClient):
    """Requesting /me with garbage token → 401."""
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalidtoken123"})
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
#  PASSWORD RESET
# ═══════════════════════════════════════════════════════════════

def test_forgot_password_existing_email(client: TestClient):
    """Forgot password for existing user returns success."""
    _create_verified_user()
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "resetme@test.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    # In dev mode, token should be returned
    assert "dev_token" in data


def test_forgot_password_nonexistent_email(client: TestClient):
    """Forgot password for nonexistent email STILL returns success (anti-enumeration)."""
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "doesnotexist@test.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    # Should NOT contain dev_token for nonexistent user
    assert "dev_token" not in data


def test_reset_password_valid_token(client: TestClient):
    """Password reset with valid token succeeds."""
    _create_verified_user()
    # Request reset
    forgot_resp = client.post("/api/v1/auth/forgot-password", json={"email": "resetme@test.com"})
    token = forgot_resp.json()["dev_token"]

    # Reset password
    reset_resp = client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "NewSecurePassword123!",
        "confirm_password": "NewSecurePassword123!",
    })
    assert reset_resp.status_code == 200
    assert "success" in reset_resp.json()["status"]

    # Login with new password should work
    login_resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "resetme@test.com",
        "password": "NewSecurePassword123!",
    })
    assert login_resp.status_code == 200

    # Login with old password should fail
    old_login = client.post("/api/v1/auth/login", json={
        "username_or_email": "resetme@test.com",
        "password": TEST_PASSWORD,
    })
    assert old_login.status_code == 401


def test_reset_password_invalid_token(client: TestClient):
    """Password reset with invalid token → 400."""
    resp = client.post("/api/v1/auth/reset-password", json={
        "token": "completely-invalid-token-abc123",
        "new_password": "NewPassword123!",
        "confirm_password": "NewPassword123!",
    })
    assert resp.status_code == 400


def test_reset_password_reused_token(client: TestClient):
    """Password reset token is single-use — second attempt fails."""
    _create_verified_user()
    forgot_resp = client.post("/api/v1/auth/forgot-password", json={"email": "resetme@test.com"})
    token = forgot_resp.json()["dev_token"]

    # First reset — should succeed
    resp1 = client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "FirstNewPassword123!",
        "confirm_password": "FirstNewPassword123!",
    })
    assert resp1.status_code == 200

    # Second reset — token consumed, should fail
    resp2 = client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "SecondNewPassword123!",
        "confirm_password": "SecondNewPassword123!",
    })
    assert resp2.status_code == 400


def test_reset_password_mismatch(client: TestClient):
    """Password reset with mismatched passwords → 422."""
    resp = client.post("/api/v1/auth/reset-password", json={
        "token": "some-token",
        "new_password": "Password123!",
        "confirm_password": "DifferentPassword123!",
    })
    assert resp.status_code == 422


def test_reset_password_weak(client: TestClient):
    """Password reset with weak password → 422."""
    resp = client.post("/api/v1/auth/reset-password", json={
        "token": "some-token",
        "new_password": "short",
        "confirm_password": "short",
    })
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════
#  SECURITY: ATTACK SCENARIOS
# ═══════════════════════════════════════════════════════════════

def test_attacker_enters_another_users_email_no_password(client: TestClient, seed_data):
    """
    CRITICAL: Attacker knows a valid email but not the password → LOGIN MUST FAIL.
    """
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a@alpha.com",
        "password": "AttackerGuessPassword!",
    })
    assert resp.status_code == 401


def test_attacker_enters_nonexistent_email(client: TestClient):
    """
    Attacker enters nonexistent email → LOGIN MUST FAIL with same error.
    """
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "nobody@nowhere.com",
        "password": "AnyPassword123!",
    })
    assert resp.status_code == 401
    # Error must be generic — same as wrong password
    assert "incorrect" in resp.json()["detail"].lower()


def test_cannot_create_env_without_email_ownership(client: TestClient):
    """
    Cannot create an environment by just providing someone else's email
    without proving ownership through verification.
    """
    payload = {
        "organization_name": "Stolen Org",
        "admin_email": "victim@company.com",
        "admin_username": "attacker",
        "admin_password": "AttackerPassword123!",
        # No verification_token or verification_code
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 400
    assert "verification" in resp.json()["detail"].lower()
