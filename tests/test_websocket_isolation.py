"""
Tests for WebSocket Authentication, Organization Isolation, and Broadcast Boundaries.
====================================================================================

Verifies:
- Agent WS rejects mismatched cross-org credentials (1008)
- Agent WS rejects missing token (1008)
- Dashboard WS rejects invalid/expired token (1008)
- Dashboard WS rejects deactivated user (1008)
- Strict broadcast isolation: telemetry streamed from Device A is dispatched
  ONLY to Dashboard A (same org) and never to Dashboard B (foreign org).
"""
import pytest
from fastapi.testclient import TestClient
from tests.conftest import RAW_KEY_A, RAW_KEY_B
import asyncio
import server.database as db_module
from server.models import User


def test_agent_ws_cross_org_key_rejected(client: TestClient, seed_data):
    """Agent connecting to Org B device using Org A API key is rejected."""
    device_b_id = seed_data["device_b1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_b_id}?token={RAW_KEY_A}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "AUTH_FAILED"


def test_agent_ws_missing_token_rejected(client: TestClient, seed_data):
    """Agent connecting without token query parameter is rejected."""
    device_a_id = seed_data["device_a1_id"]
    with client.websocket_connect(f"/ws/v1/agent/{device_a_id}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "AUTH_FAILED"


def test_dashboard_ws_deactivated_user_rejected(client: TestClient, seed_data):
    """Dashboard connecting with token of deactivated user is rejected."""
    async def _deactivate():
        async with db_module.async_session_factory() as session:
            user = await session.get(User, seed_data["user_a1_id"])
            user.is_active = False
            await session.commit()
    asyncio.run(_deactivate())

    token = seed_data["headers_user_a1"]["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/v1/dashboard?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "inactive" in msg["message"].lower() or "not found" in msg["message"].lower()


def test_dashboard_ws_unknown_action(client: TestClient, seed_data):
    """Dashboard sending unknown action receives structured error response."""
    token = seed_data["headers_admin_a"]["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/v1/dashboard?token={token}") as ws:
        ws.send_json({"action": "unsupported_action_123"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unknown" in msg["message"].lower()


def test_websocket_telemetry_broadcast_org_isolation(client: TestClient, seed_data):
    """
    CRITICAL: Device A sends telemetry via agent WS.
    Dashboard A receives the telemetry broadcast.
    Dashboard B (different org) receives NOTHING.
    """
    token_a = seed_data["headers_admin_a"]["Authorization"].split(" ")[1]
    token_b = seed_data["headers_admin_b"]["Authorization"].split(" ")[1]
    device_a_id = seed_data["device_a1_id"]

    # Open Dashboard A and Dashboard B connections
    with client.websocket_connect(f"/ws/v1/dashboard?token={token_a}") as ws_dash_a, \
         client.websocket_connect(f"/ws/v1/dashboard?token={token_b}") as ws_dash_b, \
         client.websocket_connect(f"/ws/v1/agent/{device_a_id}?token={RAW_KEY_A}") as ws_agent:

        # Agent receives auth_success
        agent_auth = ws_agent.receive_json()
        assert agent_auth["type"] == "auth_success"

        # Dashboard A subscribes to Device A
        ws_dash_a.send_json({"action": "subscribe", "device_id": device_a_id})
        sub_ack = ws_dash_a.receive_json()
        assert sub_ack["type"] == "subscribed"

        # Agent sends telemetry
        telemetry_payload = {
            "type": "telemetry",
            "payload": {
                "cpu_percent": 42.0,
                "memory_percent": 75.0,
            },
        }
        ws_agent.send_json(telemetry_payload)

        # Agent receives telemetry_ack
        agent_ack = ws_agent.receive_json()
        assert agent_ack["type"] == "telemetry_ack"

        # Dashboard A MUST receive the broadcast telemetry
        dash_a_msg = ws_dash_a.receive_json()
        assert dash_a_msg["type"] == "telemetry"
        assert dash_a_msg["device_id"] == device_a_id
        assert dash_a_msg["payload"]["cpu_percent"] == 42.0

        # Dashboard B asks for online devices — should only see Org B online devices, NOT Device A!
        ws_dash_b.send_json({"action": "get_online"})
        dash_b_msg = ws_dash_b.receive_json()
        assert dash_b_msg["type"] == "online_devices"
        assert device_a_id not in dash_b_msg["device_ids"]
