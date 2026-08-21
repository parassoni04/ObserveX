"""
ObserveX Server — Main Application Entry Point.

Central FastAPI server handling:
  - User authentication (JWT)
  - Agent authentication (API key)
  - Device management with RBAC
  - Real-time telemetry via WebSockets
  - AIOps analytics
  - Enrollment code management
  - Device-user assignment management
"""
import asyncio
import datetime
import uvicorn
import bcrypt
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.database import init_db, close_db
from server.routers import devices, metrics, agents, auth, admin, automation, aiops
from server.routers import enrollment, assignments
from server.websockets.hub import connection_manager
from server.tasks import cleanup_old_metrics, mark_stale_devices_offline, evaluate_alert_rules


async def seed_initial_data():
    """Seed default organization and superadmin account if missing."""
    from server.database import async_session_factory
    from server.models import User, Organization
    from server.auth import hash_password
    from sqlalchemy import select

    async with async_session_factory() as session:
        default_org = (await session.execute(select(Organization).limit(1))).scalar_one_or_none()
        if not default_org:
            default_org = Organization(name="ObserveX Enterprise")
            session.add(default_org)
            await session.commit()
            await session.refresh(default_org)

        admin_user = (await session.execute(select(User).where(User.role == "admin").limit(1))).scalar_one_or_none()
        if not admin_user:
            session.add(User(
                email="admin@observex.local", username="admin", full_name="System Administrator",
                hashed_password=hash_password("admin123"), role="admin", is_active=True, organization_id=default_org.id,
            ))
            await session.commit()
            print("[ObserveX Server] Default admin created: admin@observex.local / admin123")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[ObserveX Server] Initializing database...")
    await init_db()
    print("[ObserveX Server] Database ready.")
    await seed_initial_data()
    bg_tasks = [asyncio.create_task(t()) for t in (cleanup_old_metrics, mark_stale_devices_offline, evaluate_alert_rules)]
    yield
    for t in bg_tasks:
        t.cancel()
    await close_db()
    print("[ObserveX Server] Shutdown complete.")


app = FastAPI(title="ObserveX Server", version="3.0.0", description="Centralized monitoring backend for ObserveX agents with RBAC & Auth", lifespan=lifespan)

origins = settings.CORS_ORIGINS.split(",") if settings.CORS_ORIGINS != "*" else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Register all routers
for r in (auth.router, admin.router, devices.router, metrics.router, agents.router,
          automation.router, aiops.router, enrollment.router, assignments.router):
    app.include_router(r)


# ── Agent WebSocket (with authentication) ──

async def _authenticate_agent_ws(device_id: int, websocket: WebSocket) -> bool:
    """
    Authenticate an agent WebSocket connection.
    Checks for API key in query params (?token=...) or Authorization header.
    """
    from server.database import async_session_factory
    from server.models import Device

    # Extract token from query params or headers
    query_string = str(websocket.scope.get("query_string", b""), "utf-8")
    params = parse_qs(query_string)
    token = None

    if "token" in params:
        token = params["token"][0]

    if not token:
        # Check headers
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        # For backward compat: accept unauthenticated if device has no api_key_hash
        async with async_session_factory() as session:
            device = await session.get(Device, device_id)
            if device and not device.api_key_hash and not device.api_key:
                return True  # Legacy device with no credential
        return False

    # Validate token against device
    async with async_session_factory() as session:
        device = await session.get(Device, device_id)
        if not device:
            return False
        if device.status == "revoked":
            return False

        # Try hashed key
        if device.api_key_hash:
            try:
                if bcrypt.checkpw(token.encode("utf-8"), device.api_key_hash.encode("utf-8")):
                    return True
            except Exception:
                pass

        # Legacy fallback
        if device.api_key and device.api_key == token:
            return True

    return False


@app.websocket("/ws/v1/agent/{device_id}")
async def ws_agent(websocket: WebSocket, device_id: int):
    """Agent streams live metrics over this WebSocket (authenticated)."""
    # Authenticate before accepting
    if not await _authenticate_agent_ws(device_id, websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        print(f"[WS] Agent auth failed: device_id={device_id}")
        return

    await connection_manager.connect_agent(device_id, websocket)
    print(f"[WS] Agent connected: device_id={device_id}")

    from server.database import async_session_factory
    from server.models import Device
    try:
        async with async_session_factory() as session:
            device = await session.get(Device, device_id)
            if device:
                device.is_online = True
                device.status = "active"
                device.last_seen = datetime.datetime.utcnow()
                await session.commit()
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            await connection_manager.receive_agent_metrics(device_id, data)
            try:
                async with async_session_factory() as session:
                    device = await session.get(Device, device_id)
                    if device:
                        device.last_seen = datetime.datetime.utcnow()
                        device.is_online = True
                        if device.status in ("pending", "offline", "stale"):
                            device.status = "active"
                        await session.commit()
            except Exception:
                pass
    except WebSocketDisconnect:
        print(f"[WS] Agent disconnected: device_id={device_id}")
    except Exception as e:
        print(f"[WS] Agent error (device_id={device_id}): {e}")
    finally:
        connection_manager.disconnect_agent(device_id)
        try:
            async with async_session_factory() as session:
                device = await session.get(Device, device_id)
                if device:
                    device.is_online = False
                    device.status = "offline"
                    await session.commit()
        except Exception:
            pass


# ── Dashboard WebSocket (with JWT authentication) ──

async def _authenticate_dashboard_ws(websocket: WebSocket) -> int | None:
    """
    Authenticate a dashboard WebSocket connection via JWT.
    Returns user_id on success, None on failure.
    """
    import jwt as pyjwt
    from server.database import async_session_factory
    from server.models import User

    # Extract JWT from query params or headers
    query_string = str(websocket.scope.get("query_string", b""), "utf-8")
    params = parse_qs(query_string)
    token = None

    if "token" in params:
        token = params["token"][0]

    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        return None  # Allow unauthenticated for backward compat (will have limited access)

    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload.get("sub", 0))
        if user_id <= 0:
            return None

        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if user and user.is_active:
                return user_id
    except Exception:
        pass

    return None


@app.websocket("/ws/v1/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """Dashboard clients connect here to receive live metrics."""
    user_id = await _authenticate_dashboard_ws(websocket)

    await connection_manager.connect_dashboard(websocket, user_id=user_id)
    print(f"[WS] Dashboard client connected (user_id={user_id})")
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "subscribe":
                device_id = data.get("device_id")
                if device_id is not None:
                    # Authorization check: can this user access this device?
                    if user_id:
                        from server.database import async_session_factory
                        from server.models import User as UserModel
                        async with async_session_factory() as session:
                            user = await session.get(UserModel, user_id)
                            if user:
                                from server.authorization import check_device_access
                                has_access = await check_device_access(user, device_id, session)
                                if not has_access:
                                    await websocket.send_json({"type": "error", "message": "Access denied to this device"})
                                    continue

                    connection_manager.subscribe_dashboard(websocket, device_id)
                    cached = connection_manager.latest_metrics.get(device_id)
                    if cached:
                        await websocket.send_json({"type": "metrics", "device_id": device_id, "data": cached})
            elif action == "unsubscribe":
                device_id = data.get("device_id")
                if device_id is not None:
                    connection_manager.unsubscribe_dashboard(websocket, device_id)
            elif action == "get_processes":
                device_id = data.get("device_id")
                await websocket.send_json({"type": "processes", "device_id": device_id, "data": connection_manager.device_processes.get(device_id, [])})
            elif action == "get_events":
                device_id = data.get("device_id")
                await websocket.send_json({"type": "events", "device_id": device_id, "data": connection_manager.device_events.get(device_id, [])})
            elif action == "set_interval":
                val = max(0.1, min(60.0, float(data.get("value", 1.0))))
                for dev_id in connection_manager.dashboard_connections.get(websocket, {}).get("subscriptions", set()):
                    await connection_manager.send_agent_command(dev_id, {"type": "command", "action": "set_interval", "value": val})
                await websocket.send_json({"type": "ack", "action": "set_interval", "value": val})
    except WebSocketDisconnect:
        print("[WS] Dashboard client disconnected")
    except Exception as e:
        print(f"[WS] Dashboard error: {e}")
    finally:
        connection_manager.disconnect_dashboard(websocket)


_project_root = Path(__file__).resolve().parent.parent
_static_dir = _project_root / "static"


@app.get("/")
async def serve_index():
    index_path = _static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ObserveX dashboard not found. Place index.html in the static/ folder."}


if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

if __name__ == "__main__":
    print(f"[ObserveX Server] Starting on {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    print(f"[ObserveX Server] Dashboard UI accessible at: http://localhost:{settings.SERVER_PORT}")
    uvicorn.run("server.main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=False, log_level="info")
