"""
ObserveX Server — Application Entry Point
==========================================

This module defines the FastAPI application factory using the modern
lifespan pattern. It is intentionally thin — all business logic lives
in routers, services, and background tasks.

Responsibilities:
- Configure CORS
- Register all routers
- Mount WebSocket endpoints
- Start background tasks on startup
- Serve the static frontend SPA
- Initialize database and logging on startup

Starting the server:
    uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from server.config import settings
from server.logging import setup_logging, get_logger
from server.database import init_db, close_db

logger = get_logger("main")


# ── Background task handles ──
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    # ── Startup ──
    setup_logging()
    logger.info("ObserveX Server starting...")

    # Validate production safety
    settings.validate_production_safety()

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start background tasks
    from server.tasks.background import (
        cleanup_old_metrics,
        mark_stale_devices_offline,
        evaluate_alert_rules,
    )
    _background_tasks.extend([
        asyncio.create_task(cleanup_old_metrics()),
        asyncio.create_task(mark_stale_devices_offline()),
        asyncio.create_task(evaluate_alert_rules()),
    ])
    logger.info("Background tasks started (%d tasks)", len(_background_tasks))

    logger.info(
        "ObserveX Server ready — http://%s:%s",
        settings.SERVER_HOST, settings.SERVER_PORT,
    )

    yield

    # ── Shutdown ──
    logger.info("ObserveX Server shutting down...")

    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    await close_db()
    logger.info("ObserveX Server stopped.")


# ── Create Application ──

app = FastAPI(
    title="ObserveX",
    description="Enterprise Device Monitoring, Observability & AIOps Platform",
    version="2.0.0",
    lifespan=lifespan,
)


# ── CORS ──

cors_origins = [
    origin.strip()
    for origin in settings.CORS_ORIGINS.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Register Routers ──

from server.routers.auth import router as auth_router
from server.routers.enrollment import router as enrollment_router
from server.routers.admin import router as admin_router
from server.routers.devices import router as devices_router
from server.routers.agents import router as agents_router
from server.routers.alerts import router as alerts_router
from server.routers.assignments import router as assignments_router
from server.routers.commands import router as commands_router
from server.routers.telemetry import router as telemetry_router
from server.routers.aiops import router as aiops_router

app.include_router(auth_router)
app.include_router(enrollment_router)
app.include_router(admin_router)
app.include_router(devices_router)
app.include_router(agents_router)
app.include_router(alerts_router)
app.include_router(assignments_router)
app.include_router(commands_router)
app.include_router(telemetry_router)
app.include_router(aiops_router)


# ── WebSocket Endpoints ──

from server.websockets.agent_handler import agent_websocket_endpoint
from server.websockets.dashboard_handler import dashboard_websocket_endpoint

app.websocket("/ws/v1/agent/{device_id}")(agent_websocket_endpoint)
app.websocket("/ws/v1/dashboard")(dashboard_websocket_endpoint)


# ── Health Check ──

@app.get("/api/v1/health")
async def health_check():
    """Basic health check endpoint."""
    from server.websockets.manager import connection_manager
    return {
        "status": "ok",
        "version": "2.0.0",
        **connection_manager.stats,
    }


# ── Agent Download ──

import os

_project_root = os.path.dirname(os.path.dirname(__file__))
_agent_exe_path = os.path.join(_project_root, "dist", "ObserveXAgent.exe")


@app.get("/api/v1/downloads/agent")
async def download_agent():
    """Download the ObserveX Agent executable."""
    if not os.path.isfile(_agent_exe_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Agent executable not found on server")
    return FileResponse(
        _agent_exe_path,
        media_type="application/octet-stream",
        filename="ObserveXAgent.exe",
    )


# ── Serve Frontend SPA ──

_static_dir = os.path.join(_project_root, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/")
    async def serve_spa():
        """Serve the frontend SPA."""
        index_path = os.path.join(_static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "ObserveX Server v2.0.0 — Frontend not found"}
