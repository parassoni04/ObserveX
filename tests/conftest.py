"""
ObserveX Test Fixtures & Shared Setup.

Provides:
- In-memory / isolated SQLite database setup
- FastAPI TestClient
- Pre-seeded Organizations, Users (Admin & Standard), Devices, and JWT tokens
- Pre-hashed passwords and agent keys for instant execution
"""
import os
import sys
import datetime
import bcrypt
import pytest
import asyncio
from fastapi.testclient import TestClient

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_observex.db"

import server.database as db_module
from server.main import app
from server.models import (
    Base, Organization, User, Device, DeviceUserAssignment, EnrollmentCode
)
from server.auth.jwt_handler import create_access_token

# Fast bcrypt hash (rounds=4) for tests
TEST_PASSWORD = "TestPassword123!"
PASSWORD_HASH = bcrypt.hashpw(TEST_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")

RAW_KEY_A = "ox-agent-key-alpha-1234567890"
HASH_KEY_A = bcrypt.hashpw(RAW_KEY_A.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")

RAW_KEY_B = "ox-agent-key-beta-1234567890"
HASH_KEY_B = bcrypt.hashpw(RAW_KEY_B.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")


def _run_async(coro):
    """Run async coroutine synchronously in tests."""
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def client():
    """Session-scoped TestClient maintaining a single consistent event loop."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def init_test_schema():
    """Create schema once for the test session."""
    async def _init():
        await db_module.init_db()
        async with db_module.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    _run_async(_init())


@pytest.fixture(scope="function", autouse=True)
def clean_database():
    """Clean all tables and reset connection manager before each test."""
    from server.websockets.manager import connection_manager
    connection_manager.reset()

    async def _clean():
        async with db_module.engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
    _run_async(_clean())
    yield
    connection_manager.reset()


@pytest.fixture
def seed_data():
    """
    Seeds a two-tenant test world:
    - Org A:
      - admin_a (admin)
      - user_a1 (user)
      - user_a2 (user)
      - device_a1 (assigned to user_a1)
      - device_a2 (unassigned)
    - Org B:
      - admin_b (admin)
      - user_b1 (user)
      - device_b1 (assigned to user_b1)
    """
    async def _seed():
        async with db_module.async_session_factory() as session:
            # Orgs
            org_a = Organization(name="Organization Alpha")
            org_b = Organization(name="Organization Beta")
            session.add_all([org_a, org_b])
            await session.commit()
            await session.refresh(org_a)
            await session.refresh(org_b)

            # Users
            admin_a = User(
                email="admin_a@alpha.com", username="admin_a",
                hashed_password=PASSWORD_HASH, role="admin",
                is_active=True, organization_id=org_a.id,
            )
            user_a1 = User(
                email="user_a1@alpha.com", username="user_a1",
                hashed_password=PASSWORD_HASH, role="user",
                is_active=True, organization_id=org_a.id,
            )
            user_a2 = User(
                email="user_a2@alpha.com", username="user_a2",
                hashed_password=PASSWORD_HASH, role="user",
                is_active=True, organization_id=org_a.id,
            )
            admin_b = User(
                email="admin_b@beta.com", username="admin_b",
                hashed_password=PASSWORD_HASH, role="admin",
                is_active=True, organization_id=org_b.id,
            )
            user_b1 = User(
                email="user_b1@beta.com", username="user_b1",
                hashed_password=PASSWORD_HASH, role="user",
                is_active=True, organization_id=org_b.id,
            )
            session.add_all([admin_a, user_a1, user_a2, admin_b, user_b1])
            await session.commit()
            for u in [admin_a, user_a1, user_a2, admin_b, user_b1]:
                await session.refresh(u)

            # Devices
            now = datetime.datetime.now(datetime.timezone.utc)
            device_a1 = Device(
                hostname="desktop-a1",
                device_uuid="uuid-device-a1",
                api_key_hash=HASH_KEY_A,
                status="active",
                is_online=True,
                organization_id=org_a.id,
                registered_at=now,
                last_seen=now,
            )
            device_a2 = Device(
                hostname="desktop-a2",
                device_uuid="uuid-device-a2",
                api_key_hash=HASH_KEY_A,
                status="active",
                is_online=False,
                organization_id=org_a.id,
                registered_at=now,
                last_seen=now,
            )
            device_b1 = Device(
                hostname="desktop-b1",
                device_uuid="uuid-device-b1",
                api_key_hash=HASH_KEY_B,
                status="active",
                is_online=True,
                organization_id=org_b.id,
                registered_at=now,
                last_seen=now,
            )
            session.add_all([device_a1, device_a2, device_b1])
            await session.commit()
            for d in [device_a1, device_a2, device_b1]:
                await session.refresh(d)

            # Assignments
            assign_a1 = DeviceUserAssignment(
                device_id=device_a1.id,
                user_id=user_a1.id,
                assigned_by=admin_a.id,
            )
            assign_b1 = DeviceUserAssignment(
                device_id=device_b1.id,
                user_id=user_b1.id,
                assigned_by=admin_b.id,
            )
            session.add_all([assign_a1, assign_b1])
            await session.commit()

            # Generate tokens
            token_admin_a = create_access_token({"sub": str(admin_a.id), "role": admin_a.role, "org_id": org_a.id})
            token_user_a1 = create_access_token({"sub": str(user_a1.id), "role": user_a1.role, "org_id": org_a.id})
            token_user_a2 = create_access_token({"sub": str(user_a2.id), "role": user_a2.role, "org_id": org_a.id})
            token_admin_b = create_access_token({"sub": str(admin_b.id), "role": admin_b.role, "org_id": org_b.id})
            token_user_b1 = create_access_token({"sub": str(user_b1.id), "role": user_b1.role, "org_id": org_b.id})

            return {
                "org_a_id": org_a.id,
                "org_b_id": org_b.id,
                "admin_a_id": admin_a.id,
                "user_a1_id": user_a1.id,
                "user_a2_id": user_a2.id,
                "admin_b_id": admin_b.id,
                "user_b1_id": user_b1.id,
                "device_a1_id": device_a1.id,
                "device_a2_id": device_a2.id,
                "device_b1_id": device_b1.id,
                "device_a1_uuid": device_a1.device_uuid,
                "headers_admin_a": {"Authorization": f"Bearer {token_admin_a}"},
                "headers_user_a1": {"Authorization": f"Bearer {token_user_a1}"},
                "headers_user_a2": {"Authorization": f"Bearer {token_user_a2}"},
                "headers_admin_b": {"Authorization": f"Bearer {token_admin_b}"},
                "headers_user_b1": {"Authorization": f"Bearer {token_user_b1}"},
            }

    return _run_async(_seed())
