"""
Tests for Comprehensive RBAC Enforcement Across Admin Endpoints.
================================================================

Verifies that regular employees (role='user') are strictly forbidden (403)
from accessing admin-only endpoints, while admins (role='admin') have
proper operational access.
"""
import pytest
from fastapi.testclient import TestClient
import asyncio
import server.database as db_module
from server.models import AlertRule, EnrollmentCode


def test_standard_user_blocked_from_admin_overview(client: TestClient, seed_data):
    """Standard user accessing admin overview is rejected with 403."""
    resp = client.get("/api/v1/admin/overview", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"].lower()


def test_standard_user_blocked_from_admin_users_list(client: TestClient, seed_data):
    """Standard user accessing user list is rejected with 403."""
    resp = client.get("/api/v1/admin/users", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 403


def test_standard_user_blocked_from_creating_user(client: TestClient, seed_data):
    """Standard user attempting to create another user is rejected with 403."""
    payload = {
        "email": "newbie@alpha.com",
        "username": "newbie",
        "password": "Password123!",
        "role": "user",
    }
    resp = client.post("/api/v1/admin/users", headers=seed_data["headers_user_a1"], json=payload)
    assert resp.status_code == 403


def test_standard_user_blocked_from_updating_user(client: TestClient, seed_data):
    """Standard user attempting to promote or modify a user is rejected with 403."""
    payload = {"role": "admin"}
    resp = client.patch(
        f"/api/v1/admin/users/{seed_data['user_a1_id']}",
        headers=seed_data["headers_user_a1"],
        json=payload,
    )
    assert resp.status_code == 403


def test_standard_user_blocked_from_deleting_user(client: TestClient, seed_data):
    """Standard user attempting to delete a user is rejected with 403."""
    resp = client.delete(
        f"/api/v1/admin/users/{seed_data['user_a2_id']}",
        headers=seed_data["headers_user_a1"],
    )
    assert resp.status_code == 403


def test_standard_user_blocked_from_audit_logs(client: TestClient, seed_data):
    """Standard user attempting to read audit logs is rejected with 403."""
    resp = client.get("/api/v1/admin/audit-log", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 403


def test_standard_user_blocked_from_listing_enrollment_codes(client: TestClient, seed_data):
    """Standard user listing enrollment codes is rejected with 403."""
    resp = client.get("/api/v1/enrollment/codes", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 403


def test_standard_user_blocked_from_revoking_enrollment_code(client: TestClient, seed_data):
    """Standard user revoking an enrollment code is rejected with 403."""
    resp = client.delete("/api/v1/enrollment/codes/1", headers=seed_data["headers_user_a1"])
    assert resp.status_code == 403


def test_standard_user_blocked_from_deleting_device(client: TestClient, seed_data):
    """Standard user attempting to delete a device is rejected with 403."""
    resp = client.delete(
        f"/api/v1/devices/{seed_data['device_a1_id']}",
        headers=seed_data["headers_user_a1"],
    )
    assert resp.status_code == 403


def test_standard_user_blocked_from_alert_rules_crud(client: TestClient, seed_data):
    """Standard user attempting to create, update, or delete alert rules is rejected with 403."""
    # Create rule
    rule_payload = {
        "name": "High CPU",
        "metric_name": "cpu_usage",
        "operator": ">",
        "threshold_value": 90.0,
        "severity": "critical",
    }
    resp1 = client.post("/api/v1/alerts/rules", headers=seed_data["headers_user_a1"], json=rule_payload)
    assert resp1.status_code == 403

    # Update rule
    update_payload = {
        "name": "High CPU Updated",
        "metric_name": "cpu_usage",
        "operator": ">",
        "threshold_value": 95.0,
        "severity": "critical",
    }
    resp2 = client.patch("/api/v1/alerts/rules/1", headers=seed_data["headers_user_a1"], json=update_payload)
    assert resp2.status_code == 403

    # Delete rule
    resp3 = client.delete("/api/v1/alerts/rules/1", headers=seed_data["headers_user_a1"])
    assert resp3.status_code == 403


def test_admin_alert_rules_lifecycle(client: TestClient, seed_data):
    """Admin can create, update, and delete alert rules."""
    rule_payload = {
        "name": "High RAM Rule",
        "metric_name": "ram_usage_percent",
        "operator": ">=",
        "threshold_value": 85.0,
        "severity": "warning",
    }
    create_resp = client.post("/api/v1/alerts/rules", headers=seed_data["headers_admin_a"], json=rule_payload)
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    # Read list
    list_resp = client.get("/api/v1/alerts/rules", headers=seed_data["headers_admin_a"])
    assert list_resp.status_code == 200
    rule_ids = [r["id"] for r in list_resp.json()]
    assert rule_id in rule_ids

    # Update
    update_resp = client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        headers=seed_data["headers_admin_a"],
        json={
            "name": "Updated High RAM Rule",
            "metric_name": "ram_usage_percent",
            "operator": ">=",
            "threshold_value": 90.0,
            "severity": "warning",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["threshold_value"] == 90.0

    # Delete
    del_resp = client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=seed_data["headers_admin_a"])
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"


def test_admin_user_management_lifecycle(client: TestClient, seed_data):
    """Admin can create a user, update their role, and delete them."""
    # 1. Create user
    payload = {
        "email": "lifecycle_user@alpha.com",
        "username": "lifecycle_user",
        "password": "Password123!",
        "role": "user",
        "full_name": "Lifecycle Test User",
    }
    create_resp = client.post("/api/v1/admin/users", headers=seed_data["headers_admin_a"], json=payload)
    assert create_resp.status_code == 201
    user_id = create_resp.json()["id"]
    assert create_resp.json()["organization_id"] == seed_data["org_a_id"]

    # 2. Update user
    update_resp = client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=seed_data["headers_admin_a"],
        json={"role": "admin", "is_active": False},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["role"] == "admin"
    assert update_resp.json()["is_active"] is False

    # 3. Delete user
    del_resp = client.delete(f"/api/v1/admin/users/{user_id}", headers=seed_data["headers_admin_a"])
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"
