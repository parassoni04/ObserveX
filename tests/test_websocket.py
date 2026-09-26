"""
ObserveX Real-Time WebSocket Infrastructure Test Suite.

Verifies:
- Agent WebSocket authentication with device API key
- Agent authentication rejection on invalid credential
- Structured message handling: heartbeat -> heartbeat_ack
- Structured message handling: telemetry -> telemetry_ack
- Dashboard WebSocket authentication with JWT
- Dashboard authentication rejection on invalid JWT
- Dashboard device telemetry subscription with tenant/device RBAC
- Cross-tenant subscription denial
"""
import pytest
from fastapi.testclient import TestClient
from tests.conftest import RAW_KEY_A


def test_agent_websocket_auth_success(client: TestClient, seed_data):
    """Agent connects with valid API key -> receives auth_success."""
    device_id = seed_data["device_a1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_id}?token={RAW_KEY_A}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "auth_success"
        assert msg["device_id"] == device_id
        assert msg["organization_id"] == seed_data["org_a_id"]


def test_agent_websocket_auth_failure(client: TestClient, seed_data):
    """Agent connects with invalid API key -> receives error and disconnects."""
    device_id = seed_data["device_a1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_id}?token=invalid-key-999") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "AUTH_FAILED"


def test_agent_websocket_heartbeat(client: TestClient, seed_data):
    """Agent sends heartbeat -> receives heartbeat_ack."""
    device_id = seed_data["device_a1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_id}?token={RAW_KEY_A}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_success"

        ws.send_json({"type": "heartbeat"})
        ack = ws.receive_json()
        assert ack["type"] == "heartbeat_ack"
        assert "timestamp" in ack


def test_agent_websocket_telemetry(client: TestClient, seed_data):
    """Agent streams structured telemetry payload -> receives telemetry_ack."""
    device_id = seed_data["device_a1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_id}?token={RAW_KEY_A}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_success"

        telemetry_msg = {
            "type": "telemetry",
            "payload": {
                "cpu_percent": 24.5,
                "memory_percent": 58.2,
                "disk_usage": {"C:": {"percent": 45.0}},
            },
        }
        ws.send_json(telemetry_msg)
        ack = ws.receive_json()
        assert ack["type"] == "telemetry_ack"


def test_dashboard_websocket_auth_success(client: TestClient, seed_data):
    """Dashboard connects with valid JWT token -> connection accepted."""
    token = seed_data["headers_admin_a"]["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/v1/dashboard?token={token}") as ws:
        # Request online devices
        ws.send_json({"action": "get_online"})
        msg = ws.receive_json()
        assert msg["type"] == "online_devices"
        assert isinstance(msg["device_ids"], list)


def test_dashboard_websocket_auth_failure(client: TestClient):
    """Dashboard connects with invalid JWT -> receives error."""
    with client.websocket_connect("/ws/v1/dashboard?token=invalid.jwt.token") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "invalid" in msg["message"].lower()


def test_dashboard_subscription_rbac(client: TestClient, seed_data):
    """User A1 can subscribe to assigned Device A1, but rejected for unassigned Device A2."""
    token = seed_data["headers_user_a1"]["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/v1/dashboard?token={token}") as ws:
        # 1. Subscribe to assigned device -> success
        ws.send_json({
            "action": "subscribe",
            "device_id": seed_data["device_a1_id"],
        })
        msg1 = ws.receive_json()
        assert msg1["type"] == "subscribed"
        assert msg1["device_id"] == seed_data["device_a1_id"]

        # 2. Subscribe to unassigned device -> access denied
        ws.send_json({
            "action": "subscribe",
            "device_id": seed_data["device_a2_id"],
        })
        msg2 = ws.receive_json()
        assert msg2["type"] == "error"
        assert "access denied" in msg2["message"].lower()


def test_dashboard_cross_org_subscription_denied(client: TestClient, seed_data):
    """Admin A cannot subscribe to Device B from Org B."""
    token = seed_data["headers_admin_a"]["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/v1/dashboard?token={token}") as ws:
        ws.send_json({
            "action": "subscribe",
            "device_id": seed_data["device_b1_id"],
        })
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "access denied" in msg["message"].lower()
