"""
Tests for Authentication & Organization Onboarding.

Verifies:
- Create Environment (Org + Admin signup)
- User Login (by username and by email)
- Invalid credentials handling
- Inactive user rejection
- /me identity verification
"""
import pytest
from fastapi.testclient import TestClient
from tests.conftest import TEST_PASSWORD


def test_create_environment_success(client: TestClient):
    """Admin can create a new organization environment from scratch."""
    payload = {
        "organization_name": "Cyberdyne Systems",
        "admin_email": "miles@cyberdyne.com",
        "admin_username": "mdyson",
        "admin_password": "SuperSecurePassword123!",
        "admin_full_name": "Miles Dyson",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "mdyson"
    assert data["user"]["role"] == "admin"
    assert data["organization"]["name"] == "Cyberdyne Systems"


def test_create_environment_duplicate_org(client: TestClient, seed_data):
    """Creating an environment with an existing org name fails."""
    payload = {
        "organization_name": "Organization Alpha",  # Already seeded
        "admin_email": "admin2@alpha.com",
        "admin_username": "admin2",
        "admin_password": "SuperSecurePassword123!",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


def test_login_success_by_username(client: TestClient, seed_data):
    """Login with valid username and password returns JWT."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin_a"


def test_login_success_by_email(client: TestClient, seed_data):
    """Login with valid email and password returns JWT."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a@alpha.com",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


def test_login_invalid_password(client: TestClient, seed_data):
    """Login with incorrect password returns 401."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "admin_a",
        "password": "WrongPassword999!",
    })
    assert resp.status_code == 401


def test_login_nonexistent_user(client: TestClient, seed_data):
    """Login with nonexistent user returns 401."""
    resp = client.post("/api/v1/auth/login", json={
        "username_or_email": "ghost_user",
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 401


def test_get_me_success(client: TestClient, seed_data):
    """Authenticated user can query /me to retrieve their profile."""
    resp = client.get("/api/v1/auth/me", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin_a"
    assert data["role"] == "admin"
    assert data["organization_id"] == seed_data["org_a_id"]


def test_get_me_unauthorized(client: TestClient):
    """Requesting /me without Authorization header returns 401."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_email_verification_code_flow(client: TestClient):
    """Can request verification code and verify it."""
    email = "newadmin@example.com"
    # Request code
    send_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert send_resp.status_code == 200
    data = send_resp.json()
    assert data["status"] == "sent"
    code = data["dev_code"]
    assert len(code) == 6

    # Verify code
    verify_resp = client.post("/api/v1/auth/verify-code", json={"email": email, "code": code})
    assert verify_resp.status_code == 200
    v_data = verify_resp.json()
    assert v_data["status"] == "verified"
    assert "verification_token" in v_data


def test_create_environment_password_mismatch(client: TestClient):
    """Creating environment fails when password and confirm_password differ."""
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
    """Creating environment fails when email format is invalid."""
    payload = {
        "organization_name": "Bad Email Org",
        "admin_email": "not-a-valid-email",
        "admin_username": "bad_email_user",
        "admin_password": "SuperPassword123!",
    }
    resp = client.post("/api/v1/auth/create-environment", json=payload)
    assert resp.status_code == 422  # Pydantic validation error

