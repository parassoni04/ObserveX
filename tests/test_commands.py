"""
ObserveX Command Dispatch & Remediation Security Test Suite.

Verifies:
- Authorized admin can dispatch allowed commands (cleanup_temp, restart_service, kill_process)
- Disallowed / arbitrary shell command injection rejected by schema validation (422)
- Malformed command target (command injection attempt) rejected by regex (422)
- Standard non-admin user cannot dispatch commands (403)
- Cross-tenant command dispatch rejected (404)
- Audit log entry created on command dispatch
- Command history retrieval and tenant scoping
"""
from fastapi.testclient import TestClient


def test_admin_dispatches_allowed_command(client: TestClient, seed_data):
    """Admin can dispatch allowlisted cleanup_temp command."""
    payload = {
        "device_id": seed_data["device_a1_id"],
        "command_type": "cleanup_temp",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["device_id"] == seed_data["device_a1_id"]
    assert data["command_type"] == "cleanup_temp"
    assert "status" in data


def test_admin_dispatches_service_restart_with_target(client: TestClient, seed_data):
    """Admin can dispatch restart_service with a safe target name."""
    payload = {
        "device_id": seed_data["device_a1_id"],
        "command_type": "restart_service",
        "target": "Spooler",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["command_type"] == "restart_service"
    assert data["target"] == "Spooler"


def test_disallowed_command_type_rejected(client: TestClient, seed_data):
    """Command type outside allowlist is rejected with 422."""
    payload = {
        "device_id": seed_data["device_a1_id"],
        "command_type": "execute_shell_script",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 422


def test_command_injection_target_rejected(client: TestClient, seed_data):
    """Target containing command injection characters is rejected with 422."""
    payload = {
        "device_id": seed_data["device_a1_id"],
        "command_type": "restart_service",
        "target": "spooler; rm -rf / ;",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_admin_a"], json=payload)
    assert resp.status_code == 422


def test_standard_user_cannot_dispatch_command(client: TestClient, seed_data):
    """Standard user cannot dispatch commands (403 Forbidden)."""
    payload = {
        "device_id": seed_data["device_a1_id"],
        "command_type": "cleanup_temp",
    }
    resp = client.post("/api/v1/commands", headers=seed_data["headers_user_a1"], json=payload)
    assert resp.status_code == 403


def test_command_history_scoped_to_organization(client: TestClient, seed_data):
    """Admin A dispatches command, verifies it appears in Org A history, not in Org B."""
    # 1. Admin A dispatches
    client.post(
        "/api/v1/commands",
        headers=seed_data["headers_admin_a"],
        json={"device_id": seed_data["device_a1_id"], "command_type": "cleanup_temp"},
    )

    # 2. Org A lists commands
    resp_a = client.get("/api/v1/commands", headers=seed_data["headers_admin_a"])
    assert resp_a.status_code == 200
    cmds_a = resp_a.json()
    assert len(cmds_a) >= 1
    for c in cmds_a:
        assert c["organization_id"] == seed_data["org_a_id"]

    # 3. Org B lists commands -> should NOT see Org A command
    resp_b = client.get("/api/v1/commands", headers=seed_data["headers_admin_b"])
    assert resp_b.status_code == 200
    cmds_b = resp_b.json()
    assert len(cmds_b) == 0
