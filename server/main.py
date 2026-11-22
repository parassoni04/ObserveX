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

from fastapi import FastAPI, Request
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


# ── Security & Cache Headers Middleware ──

@app.middleware("http")
async def add_security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/app", "/login", "/register"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


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

def _find_agent_path(filename: str) -> str | None:
    """Find agent binary in release dist/ or static/downloads/ directory."""
    candidates = [
        os.path.join(_project_root, "dist", filename),
        os.path.join(_project_root, "static", "downloads", filename),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


@app.get("/api/v1/downloads/agent")
async def download_agent():
    """Download the ObserveX Agent executable."""
    # Support external cloud/CDN or GitHub Release redirect if configured in production
    external_url = os.getenv("AGENT_DOWNLOAD_URL")
    if external_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(external_url, status_code=302)

    exe_path = _find_agent_path("ObserveXAgent.exe")
    if not exe_path:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Agent executable not found on server. Ensure dist/ObserveXAgent.exe is deployed or AGENT_DOWNLOAD_URL is configured."
        )
    return FileResponse(
        exe_path,
        media_type="application/octet-stream",
        filename="ObserveXAgent.exe",
        headers={"Content-Disposition": 'attachment; filename="ObserveXAgent.exe"'},
    )


@app.get("/api/v1/downloads/agent/zip")
async def download_agent_zip():
    """Download the ObserveX Agent bundle as a zip archive."""
    # Support external cloud/CDN or GitHub Release redirect if configured in production
    external_url = os.getenv("AGENT_ZIP_DOWNLOAD_URL")
    if external_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(external_url, status_code=302)

    zip_path = _find_agent_path("ObserveXAgent-Windows.zip")
    if not zip_path:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Agent zip bundle not found on server. Ensure dist/ObserveXAgent-Windows.zip is deployed or AGENT_ZIP_DOWNLOAD_URL is configured."
        )
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="ObserveXAgent-Windows.zip",
        headers={"Content-Disposition": 'attachment; filename="ObserveXAgent-Windows.zip"'},
    )



# ── Serve Frontend SPA & Landing Page ──

_static_dir = os.path.join(_project_root, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/")
    async def serve_landing():
        """Serve the public landing page."""
        landing_path = os.path.join(_static_dir, "landing.html")
        if os.path.exists(landing_path):
            return FileResponse(landing_path)
        index_path = os.path.join(_static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "ObserveX Server v2.0.0 — Frontend not found"}

    @app.get("/app")
    @app.get("/app/{full_path:path}")
    @app.get("/login")
    @app.get("/register")
    async def serve_app(full_path: str = ""):
        """Serve the authenticated frontend SPA."""
        index_path = os.path.join(_static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "ObserveX Server v2.0.0 — Frontend not found"}
