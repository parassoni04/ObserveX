"""
Tests for Multi-Tenancy Isolation, Cross-Tenant Boundaries, and IDOR Defense.
=============================================================================

CRITICAL SECURITY PRINCIPLE:
Cross-tenant and unauthorized resource access attempts MUST return 404 Not Found
(never 403 or 200) to prevent leaking information about resource existence across tenants.
"""
import pytest
from fastapi.testclient import TestClient
import asyncio
import datetime
import server.database as db_module
from server.models import AlertRule, EnrollmentCode, DeviceUserAssignment
from tests.conftest import RAW_KEY_A, RAW_KEY_B


@pytest.fixture
def additional_tenant_data(seed_data):
    """Seed additional tenant-specific resources (alert rules, enrollment codes, assignments)."""
    async def _seed():
        async with db_module.async_session_factory() as session:
            # Org B Alert Rule
            rule_b = AlertRule(
                organization_id=seed_data["org_b_id"],
                name="Org B High CPU",
                metric_name="cpu_percent",
                operator=">",
                threshold_value=90.0,
                severity="critical",
            )
            # Org B Enrollment Code
            code_b = EnrollmentCode(
                organization_id=seed_data["org_b_id"],
                code="OX-BETA-9999",
                created_by_user_id=seed_data["admin_b_id"],
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=24),
                max_uses=1,
            )
            session.add_all([rule_b, code_b])
            await session.commit()
            await session.refresh(rule_b)
            await session.refresh(code_b)

            # Get assignment B1 ID
            from sqlalchemy import select
            assign_b = (await session.execute(
                select(DeviceUserAssignment).where(DeviceUserAssignment.user_id == seed_data["user_b1_id"])
            )).scalar_one()

            return {
                "rule_b_id": rule_b.id,
                "code_b_id": code_b.id,
                "assign_b_id": assign_b.id,
            }

    return asyncio.run(_seed())


def test_cross_org_device_status_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B status -> 404."""
    resp = client.get(f"/api/v1/devices/{seed_data['device_b1_id']}/status", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_device_static_info_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B static info -> 404."""
    resp = client.get(f"/api/v1/devices/{seed_data['device_b1_id']}/static-info", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_device_software_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B software inventory -> 404."""
    resp = client.get(f"/api/v1/devices/{seed_data['device_b1_id']}/software", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_telemetry_live_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B live metrics -> 404."""
    resp = client.get(f"/api/v1/telemetry/{seed_data['device_b1_id']}/live", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_telemetry_processes_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B process list -> 404."""
    resp = client.get(f"/api/v1/telemetry/{seed_data['device_b1_id']}/processes", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_telemetry_events_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B Windows events -> 404."""
    resp = client.get(f"/api/v1/telemetry/{seed_data['device_b1_id']}/events", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_telemetry_history_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B telemetry history -> 404."""
    resp = client.get(f"/api/v1/telemetry/{seed_data['device_b1_id']}/history", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_aiops_anomalies_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B AIOps anomalies -> 404."""
    resp = client.get(f"/api/v1/aiops/{seed_data['device_b1_id']}/anomalies", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_aiops_forecast_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B AIOps forecast -> 404."""
    resp = client.get(f"/api/v1/aiops/{seed_data['device_b1_id']}/forecast", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_aiops_root_cause_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B AIOps root-cause -> 404."""
    resp = client.get(f"/api/v1/aiops/{seed_data['device_b1_id']}/root-cause", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_aiops_insights_denied(client: TestClient, seed_data):
    """Admin A cannot access Device B AIOps insights -> 404."""
    resp = client.get(f"/api/v1/aiops/{seed_data['device_b1_id']}/insights", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_user_patch_denied(client: TestClient, seed_data):
    """Admin A cannot update User B -> 404."""
    resp = client.patch(
        f"/api/v1/admin/users/{seed_data['user_b1_id']}",
        headers=seed_data["headers_admin_a"],
        json={"role": "admin"},
    )
    assert resp.status_code == 404


def test_cross_org_enrollment_code_revoke_denied(client: TestClient, seed_data, additional_tenant_data):
    """Admin A cannot revoke Enrollment Code B -> 404."""
    code_b_id = additional_tenant_data["code_b_id"]
    resp = client.delete(f"/api/v1/enrollment/codes/{code_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_enrollment_code_permanent_delete_denied(client: TestClient, seed_data, additional_tenant_data):
    """Admin A cannot permanently delete Enrollment Code B -> 404."""
    code_b_id = additional_tenant_data["code_b_id"]
    resp = client.delete(f"/api/v1/enrollment/codes/{code_b_id}/permanent", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_alert_rule_update_denied(client: TestClient, seed_data, additional_tenant_data):
    """Admin A cannot modify Alert Rule B -> 404."""
    rule_b_id = additional_tenant_data["rule_b_id"]
    payload = {
        "name": "Tampered Rule",
        "metric_name": "cpu_usage",
        "operator": ">",
        "threshold_value": 95.0,
        "severity": "critical",
    }
    resp = client.patch(
        f"/api/v1/alerts/rules/{rule_b_id}",
        headers=seed_data["headers_admin_a"],
        json=payload,
    )
    assert resp.status_code == 404


def test_cross_org_alert_rule_delete_denied(client: TestClient, seed_data, additional_tenant_data):
    """Admin A cannot delete Alert Rule B -> 404."""
    rule_b_id = additional_tenant_data["rule_b_id"]
    resp = client.delete(f"/api/v1/alerts/rules/{rule_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_cross_org_assignment_delete_denied(client: TestClient, seed_data, additional_tenant_data):
    """Admin A cannot delete Assignment B -> 404."""
    assign_b_id = additional_tenant_data["assign_b_id"]
    resp = client.delete(f"/api/v1/admin/assignments/{assign_b_id}", headers=seed_data["headers_admin_a"])
    assert resp.status_code == 404


def test_unassigned_device_telemetry_denied_user(client: TestClient, seed_data):
    """User A1 cannot access telemetry for unassigned Device A2 (same org) -> 404."""
    resp1 = client.get(f"/api/v1/telemetry/{seed_data['device_a2_id']}/live", headers=seed_data["headers_user_a1"])
    assert resp1.status_code == 404

    resp2 = client.get(f"/api/v1/telemetry/{seed_data['device_a2_id']}/processes", headers=seed_data["headers_user_a1"])
    assert resp2.status_code == 404

    resp3 = client.get(f"/api/v1/telemetry/{seed_data['device_a2_id']}/history", headers=seed_data["headers_user_a1"])
    assert resp3.status_code == 404


def test_agent_endpoint_auth_mismatch_denied(client: TestClient, seed_data):
    """Agent using Device A's key cannot access Device B's heartbeat endpoint -> 403."""
    headers = {"Authorization": f"Bearer {RAW_KEY_A}"}
    resp = client.post(
        "/api/v1/agent/heartbeat",
        headers=headers,
        json={"device_id": seed_data["device_b1_id"]},
    )
    assert resp.status_code == 403
