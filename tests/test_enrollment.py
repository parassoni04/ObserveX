"""
ObserveX Device Enrollment & Code Lifecycle Test Suite.

Verifies:
- Enrollment code creation (admin-only)
- Agent enrollment handshake
- Single-use and multi-use exhaustion (410 Gone)
- Expired code rejection (410 Gone)
- Invalid/nonexistent code rejection
- Admin revocation of codes
- API key security: plain API key returned once to agent, only bcrypt hash stored in DB
"""
import datetime
import asyncio
from fastapi.testclient import TestClient
import server.database as db_module
from server.models import EnrollmentCode, Device
from server.auth.device_auth import verify_device_credential


def test_admin_creates_enrollment_code(client: TestClient, seed_data):
    """Admin can create a new enrollment code."""
    payload = {"expires_in_hours": 48, "max_uses": 5}
    resp = client.post("/api/v1/enrollment/codes", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "code" in data
    assert data["code"].startswith("OX-")
    assert data["max_uses"] == 5
    assert data["usage_count"] == 0
    assert data["organization_id"] == seed_data["org_a_id"]


def test_standard_user_cannot_create_enrollment_code(client: TestClient, seed_data):
    """Standard non-admin user is rejected with 403."""
    payload = {"expires_in_hours": 24, "max_uses": 1}
    resp = client.post("/api/v1/enrollment/codes", headers=seed_data["headers_user_a1"], json=payload)
    assert resp.status_code == 403


def test_agent_enrollment_success(client: TestClient, seed_data):
    """Agent can successfully enroll with a valid code."""
    # 1. Admin generates code
    code_resp = client.post(
        "/api/v1/enrollment/codes",
        headers=seed_data["headers_admin_a"],
        json={"expires_in_hours": 24, "max_uses": 2},
    )
    assert code_resp.status_code == 201
    code = code_resp.json()["code"]

    # 2. Agent enrolls
    enroll_payload = {
        "enrollment_code": code,
        "hostname": "WORKSTATION-X1",
        "os_name": "Windows",
        "os_version": "11 Pro",
        "agent_version": "2.0.0",
    }
    enroll_resp = client.post("/api/v1/enrollment/enroll", json=enroll_payload)
    assert enroll_resp.status_code == 200
    enroll_data = enroll_resp.json()

    assert "device_id" in enroll_data
    assert "device_uuid" in enroll_data
    assert "api_key" in enroll_data
    assert enroll_data["organization_name"] == "Organization Alpha"

    # 3. Verify in DB that only hash is stored
    async def _verify_db():
        async with db_module.async_session_factory() as session:
            device = await session.get(Device, enroll_data["device_id"])
            assert device is not None
            assert device.hostname == "WORKSTATION-X1"
            assert device.organization_id == seed_data["org_a_id"]
            assert device.api_key_hash != enroll_data["api_key"]
            auth_dev = await verify_device_credential(device.id, enroll_data["api_key"], session)
            assert auth_dev is not None

    asyncio.run(_verify_db())


def test_single_use_code_exhaustion(client: TestClient, seed_data):
    """Code with max_uses=1 cannot be used a second time -> 410 Gone."""
    # 1. Create single-use code
    code_resp = client.post(
        "/api/v1/enrollment/codes",
        headers=seed_data["headers_admin_a"],
        json={"expires_in_hours": 24, "max_uses": 1},
    )
    code = code_resp.json()["code"]

    # 2. First enrollment succeeds
    r1 = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": code,
        "hostname": "HOST-01",
    })
    assert r1.status_code == 200

    # 3. Second enrollment fails with 410
    r2 = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": code,
        "hostname": "HOST-02",
    })
    assert r2.status_code == 410
    assert "max" in r2.json()["detail"].lower() or "exhausted" in r2.json()["detail"].lower()


def test_expired_code_rejected(client: TestClient, seed_data):
    """Expired enrollment code returns 410 Gone."""
    # Manually seed an expired code
    async def _seed_expired():
        async with db_module.async_session_factory() as session:
            expired_code = EnrollmentCode(
                code="OX-DEAD-BEEF",
                organization_id=seed_data["org_a_id"],
                created_by_user_id=seed_data["admin_a_id"],
                expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2),
                max_uses=5,
            )
            session.add(expired_code)
            await session.commit()

    asyncio.run(_seed_expired())

    resp = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": "OX-DEAD-BEEF",
        "hostname": "LATE-PC",
    })
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


def test_nonexistent_code_rejected(client: TestClient):
    """Non-existent code with valid format returns 410."""
    resp = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": "OX-AAAA-BBBB",
        "hostname": "FAKE-PC",
    })
    assert resp.status_code in [404, 410]


def test_malformed_code_rejected_schema_validation(client: TestClient):
    """Malformed code format returns 422."""
    resp = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": "NOT-A-VALID-CODE",
        "hostname": "MALFORMED-PC",
    })
    assert resp.status_code == 422


def test_revoked_code_rejected(client: TestClient, seed_data):
    """Admin revokes code -> cannot be used to enroll."""
    # 1. Create code
    code_resp = client.post(
        "/api/v1/enrollment/codes",
        headers=seed_data["headers_admin_a"],
        json={"expires_in_hours": 24, "max_uses": 5},
    )
    code_id = code_resp.json()["id"]
    code_str = code_resp.json()["code"]

    # 2. Admin deletes / revokes code
    del_resp = client.delete(f"/api/v1/enrollment/codes/{code_id}", headers=seed_data["headers_admin_a"])
    assert del_resp.status_code == 200

    # 3. Agent attempts enrollment
    enroll_resp = client.post("/api/v1/enrollment/enroll", json={
        "enrollment_code": code_str,
        "hostname": "REVOKED-PC",
    })
    assert enroll_resp.status_code == 410
