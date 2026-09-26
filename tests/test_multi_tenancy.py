"""
ObserveX Multi-Tenancy & Tenant Isolation Test Suite.

Verifies strict tenant isolation across all resources:
- Devices
- Users
- Overview statistics
- Commands
- Assignments
- Alerts & Alert Rules
- Audit logs

CRITICAL SECURITY PRINCIPLE:
Cross-tenant access attempts MUST return 404 Not Found (not 403 Forbidden),
to prevent leaking information about whether another tenant's resource ID exists.
"""
from fastapi.testclient import TestClient


def test_cross_org_device_access_denied_admin(client: TestClient, seed_data):
    """Admin A cannot access Device B (from Org B) -> 404."""
    device_b_id = seed_data["device_b1_id"]
    resp = client.get(f"/api/v1/devices/{device_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_device_access_denied_user(client: TestClient, seed_data):
    """User A cannot access Device B (from Org B) -> 404."""
    device_b_id = seed_data["device_b1_id"]
    resp = client.get(f"/api/v1/devices/{device_b_id}", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 404


def test_device_list_isolated_by_organization(client: TestClient, seed_data):
    """Admin A only sees Org A devices; Admin B only sees Org B devices."""
    resp_a = client.get("/api/v1/devices", headers=seed_data["headers_admin_a"])
    assert resp_a.status_code == 200
    devices_a = resp_a.json()
    device_ids_a = {d["id"] for d in devices_a}
    assert seed_data["device_a1_id"] in device_ids_a
    assert seed_data["device_a2_id"] in device_ids_a
    assert seed_data["device_b1_id"] not in device_ids_a

    resp_b = client.get("/api/v1/devices", headers=seed_data["headers_admin_b"])
    assert resp_b.status_code == 200
    devices_b = resp_b.json()
    device_ids_b = {d["id"] for d in devices_b}
    assert seed_data["device_b1_id"] in device_ids_b
    assert seed_data["device_a1_id"] not in device_ids_b


def test_cross_org_device_delete_denied(client: TestClient, seed_data):
    """Admin A cannot delete Device B -> 404."""
    device_b_id = seed_data["device_b1_id"]
    resp = client.delete(f"/api/v1/devices/{device_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_user_list_isolated(client: TestClient, seed_data):
    """Admin A only sees Org A users in user management."""
    resp = client.get("/api/v1/admin/users", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 200
    users = resp.json()
    usernames = {u["username"] for u in users}
    assert "admin_a" in usernames
    assert "user_a1" in usernames
    assert "admin_b" not in usernames
    assert "user_b1" not in usernames


def test_cross_org_user_delete_denied(client: TestClient, seed_data):
    """Admin A cannot delete User B -> 404."""
    user_b_id = seed_data["user_b1_id"]
    resp = client.delete(f"/api/v1/admin/users/{user_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_admin_overview_strictly_scoped(client: TestClient, seed_data):
    """Admin overview reflects only its own tenant's counts."""
    resp_a = client.get("/api/v1/admin/overview", headers=seed_data["headers_admin_a"])
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["organization_name"] == "Organization Alpha"
    assert data_a["total_devices"] == 2
    assert data_a["total_users"] == 3  # admin_a, user_a1, user_a2

    resp_b = client.get("/api/v1/admin/overview", headers=seed_data["headers_admin_b"])
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["organization_name"] == "Organization Beta"
    assert data_b["total_devices"] == 1
    assert data_b["total_users"] == 2  # admin_b, user_b1


def test_cross_org_command_dispatch_denied(client: TestClient, seed_data):
    """Admin A cannot dispatch commands to Device B -> 404."""
    payload = {
        "device_id": seed_data["device_b1_id"],
        "command_type": "cleanup_temp",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 404


def test_cross_org_assignment_denied(client: TestClient, seed_data):
    """Admin A cannot assign Org B's device to an Org A user -> 404."""
    payload = {
        "device_id": seed_data["device_b1_id"],
        "user_id": seed_data["user_a1_id"],
    }
    resp = client.post("/api/v1/admin/assignments", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 404


def test_cross_org_audit_log_isolated(client: TestClient, seed_data):
    """Admin A cannot see Org B audit logs."""
    resp = client.get("/api/v1/admin/audit-log", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 200
    logs = resp.json()
    for log in logs:
        assert log["organization_id"] == seed_data["org_a_id"]
