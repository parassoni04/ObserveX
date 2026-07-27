import os
import sys
import asyncio
import datetime
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.database import init_db, close_db
from server.routers import devices, metrics, agents, auth, admin, alerts, reports, automation
from server.websockets.hub import connection_manager
from server.tasks import cleanup_old_metrics, mark_stale_devices_offline, evaluate_alert_rules


async def seed_initial_data():
    """Seed default organization and superadmin account if missing."""
    from server.database import async_session_factory
    from server.models import User, Organization
    from server.auth import hash_password
    from sqlalchemy import select

    async with async_session_factory() as session:
        # Ensure default Organization
        org_res = await session.execute(select(Organization).limit(1))
        default_org = org_res.scalar_one_or_none()
        if not default_org:
            default_org = Organization(name="ObserveX Enterprise")
            session.add(default_org)
            await session.commit()
            await session.refresh(default_org)

        # Ensure default Admin user
        admin_res = await session.execute(select(User).where(User.role == "admin").limit(1))
        admin_user = admin_res.scalar_one_or_none()
        if not admin_user:
            admin_user = User(
                email="admin@observex.local",
                username="admin",
                full_name="System Administrator",
                hashed_password=hash_password("admin123"),
                role="admin",
                is_active=True,
                organization_id=default_org.id
            )
            session.add(admin_user)
            await session.commit()
            print("[ObserveX Server] Default admin created: admin@observex.local / admin123")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # ── Startup ──
    print("[ObserveX Server] Initializing database...")
    await init_db()
    print("[ObserveX Server] Database ready.")

    await seed_initial_data()

    # Launch background tasks
    cleanup_task = asyncio.create_task(cleanup_old_metrics())
    stale_task = asyncio.create_task(mark_stale_devices_offline())
    rule_task = asyncio.create_task(evaluate_alert_rules())

    yield

    # ── Shutdown ──
    cleanup_task.cancel()
    stale_task.cancel()
    rule_task.cancel()
    await close_db()
    print("[ObserveX Server] Shutdown complete.")


app = FastAPI(
    title="ObserveX Server",
    version="3.0.0",
    description="Centralized monitoring backend for ObserveX agents with RBAC & Auth",
    lifespan=lifespan,
)

# ── CORS ──
origins = settings.CORS_ORIGINS.split(",") if settings.CORS_ORIGINS != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST Routers ──
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(devices.router)
app.include_router(metrics.router)
app.include_router(agents.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(automation.router)


# ── WebSocket: Agent → Server ──

@app.websocket("/ws/v1/agent/{device_id}")
async def ws_agent(websocket: WebSocket, device_id: int):
    """Agent streams live metrics over this WebSocket."""
    await connection_manager.connect_agent(device_id, websocket)
    print(f"[WS] Agent connected: device_id={device_id}")

    # Mark device online
    from server.database import async_session_factory
    from server.models import Device
    try:
        async with async_session_factory() as session:
            device = await session.get(Device, device_id)
            if device:
                device.is_online = True
                device.last_seen = datetime.datetime.utcnow()
                await session.commit()
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            await connection_manager.receive_agent_metrics(device_id, data)

            # Update last_seen periodically (every message)
            try:
                async with async_session_factory() as session:
                    device = await session.get(Device, device_id)
                    if device:
                        device.last_seen = datetime.datetime.utcnow()
                        device.is_online = True
                        await session.commit()
            except Exception:
                pass

    except WebSocketDisconnect:
        print(f"[WS] Agent disconnected: device_id={device_id}")
    except Exception as e:
        print(f"[WS] Agent error (device_id={device_id}): {e}")
    finally:
        connection_manager.disconnect_agent(device_id)
        # Mark device offline
        try:
            async with async_session_factory() as session:
                device = await session.get(Device, device_id)
                if device:
                    device.is_online = False
                    await session.commit()
        except Exception:
            pass


# ── WebSocket: Server → Dashboard ──

@app.websocket("/ws/v1/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """Dashboard clients connect here to receive live metrics."""
    await connection_manager.connect_dashboard(websocket)
    print("[WS] Dashboard client connected")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                device_id = data.get("device_id")
                if device_id is not None:
                    connection_manager.subscribe_dashboard(websocket, device_id)
                    # Send cached latest metrics immediately
                    cached = connection_manager.latest_metrics.get(device_id)
                    if cached:
                        await websocket.send_json({
                            "type": "metrics",
                            "device_id": device_id,
                            "data": cached,
                        })

            elif action == "unsubscribe":
                device_id = data.get("device_id")
                if device_id is not None:
                    connection_manager.unsubscribe_dashboard(websocket, device_id)

            elif action == "get_processes":
                device_id = data.get("device_id")
                processes = connection_manager.device_processes.get(device_id, [])
                await websocket.send_json({
                    "type": "processes",
                    "device_id": device_id,
                    "data": processes,
                })

            elif action == "get_events":
                device_id = data.get("device_id")
                events = connection_manager.device_events.get(device_id, [])
                await websocket.send_json({
                    "type": "events",
                    "device_id": device_id,
                    "data": events,
                })

    except WebSocketDisconnect:
        print("[WS] Dashboard client disconnected")
    except Exception as e:
        print(f"[WS] Dashboard error: {e}")
    finally:
        connection_manager.disconnect_dashboard(websocket)


# ── Serve Frontend ──

# Resolve static directory relative to project root
_project_root = Path(__file__).resolve().parent.parent
_static_dir = _project_root / "static"


@app.get("/")
async def serve_index():
    index_path = _static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "ObserveX dashboard not found. Place index.html in the static/ folder."}


# Mount static files (after routes so / isn't shadowed)
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Entry Point ──

if __name__ == "__main__":
    print(f"[ObserveX Server] Starting on {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    print(f"[ObserveX Server] Dashboard UI accessible at: http://localhost:{settings.SERVER_PORT} or http://127.0.0.1:{settings.SERVER_PORT}")
    uvicorn.run(
        "server.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False,
        log_level="info",
    )
