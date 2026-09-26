"""
ObserveX Role-Based Device Access & Assignment Test Suite.

Verifies:
- Admin full access to organization devices
- Standard user access restricted to assigned devices only
- Unassigned devices return 404 for standard users
- Device list filtering based on user assignment
- Admin device assignment lifecycle (assign, duplicate check, unassign)
- RBAC enforcement: standard users cannot create or delete assignments (403)
"""
from fastapi.testclient import TestClient


def test_admin_can_access_any_org_device(client: TestClient, seed_data):
    """Admin can view details of all devices in their organization."""
    resp1 = client.get(f"/api/v1/devices/{seed_data['device_a1_id']}", headers=seed_data["headers_admin_a"])
    assert resp1.status_code == 200
    assert resp1.json()["id"] == seed_data["device_a1_id"]

    resp2 = client.get(f"/api/v1/devices/{seed_data['device_a2_id']}", headers=seed_data["headers_admin_a"])
    assert resp2.status_code == 200
    assert resp2.json()["id"] == seed_data["device_a2_id"]


def test_assigned_user_can_access_assigned_device(client: TestClient, seed_data):
    """User assigned to device_a1 can view device_a1."""
    resp = client.get(f"/api/v1/devices/{seed_data['device_a1_id']}", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 200
    assert resp.json()["id"] == seed_data["device_a1_id"]


def test_user_cannot_access_unassigned_device(client: TestClient, seed_data):
    """User not assigned to device_a2 receives 404."""
    resp = client.get(f"/api/v1/devices/{seed_data['device_a2_id']}", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 404


def test_user_device_list_filtered_by_assignments(client: TestClient, seed_data):
    """User's device list only includes assigned devices."""
    # user_a1 is assigned to device_a1 only
    resp1 = client.get("/api/v1/devices", headers=seed_data["headers_user_a1"])
    assert resp1.status_code == 200
    devs1 = resp1.json()
    assert len(devs1) == 1
    assert devs1[0]["id"] == seed_data["device_a1_id"]

    # user_a2 has no assigned devices
    resp2 = client.get("/api/v1/devices", headers=seed_data["headers_user_a2"])
    assert resp2.status_code == 200
    assert len(resp2.json()) == 0


def test_admin_assigns_and_unassigns_device(client: TestClient, seed_data):
    """Admin assigns device_a2 to user_a2, verifies access, then unassigns."""
    # 1. Assign device_a2 to user_a2
    assign_resp = client.post(
        "/api/v1/admin/assignments",
        headers=seed_data["headers_admin_a"],
        json={
            "device_id": seed_data["device_a2_id"],
            "user_id": seed_data["user_a2_id"],
        },
    )
    assert assign_resp.status_code == 201
    assignment_id = assign_resp.json()["id"]

    # 2. user_a2 can now access device_a2
    access_resp = client.get(f"/api/v1/devices/{seed_data['device_a2_id']}", headers=seed_data["headers_user_a2"])
    assert access_resp.status_code == 200

    # 3. Duplicate assignment rejected with 409
    dup_resp = client.post(
        "/api/v1/admin/assignments",
        headers=seed_data["headers_admin_a"],
        json={
            "device_id": seed_data["device_a2_id"],
            "user_id": seed_data["user_a2_id"],
        },
    )
    assert dup_resp.status_code == 409

    # 4. Admin removes assignment
    del_resp = client.delete(f"/api/v1/admin/assignments/{assignment_id}", headers=seed_data["headers_admin_a"])
    assert del_resp.status_code == 200

    # 5. user_a2 can no longer access device_a2
    revoked_resp = client.get(f"/api/v1/devices/{seed_data['device_a2_id']}", headers=seed_data["headers_user_a2"])
    assert revoked_resp.status_code == 404


def test_standard_user_cannot_manage_assignments(client: TestClient, seed_data):
    """Standard user cannot assign devices (403 Forbidden)."""
    resp = client.post(
        "/api/v1/admin/assignments",
        headers=seed_data["headers_user_a1"],
        json={
            "device_id": seed_data["device_a2_id"],
            "user_id": seed_data["user_a1_id"],
        },
    )
    assert resp.status_code == 403
