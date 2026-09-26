"""
ObserveX Server — Centralized Configuration.

Loads settings from environment variables / .env file using pydantic-settings.
All server-configurable values are defined here — no magic constants
scattered across the codebase.

Production safety:
- JWT_SECRET_KEY must be explicitly set (no default).
- CORS_ORIGINS must be restrictive in production.
- Server refuses to start in production mode with unsafe defaults.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class ServerSettings(BaseSettings):
    """Centralized server configuration."""

    # ── Database ──
    DATABASE_URL: str = "postgresql+asyncpg://observex:observex_secret@localhost:5432/observex"

    # ── Server ──
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # ── Environment ──
    ENVIRONMENT: str = "development"

    # ── CORS ──
    CORS_ORIGINS: str = "http://localhost:8000,http://localhost:3000"

    # ── JWT ──
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # ── Heartbeat state machine (seconds) ──
    HEARTBEAT_ONLINE_TIMEOUT: int = 30
    HEARTBEAT_STALE_TIMEOUT: int = 120
    HEARTBEAT_CHECK_INTERVAL: int = 15

    # ── Telemetry ──
    METRIC_RETENTION_DAYS: int = 7
    METRIC_DB_WRITE_INTERVAL: int = 5  # Store every N-th metric snapshot

    # ── Enrollment ──
    ENROLLMENT_CODE_TTL_HOURS: int = 24

    # ── WebSocket Protocol ──
    WS_HEARTBEAT_INTERVAL: int = 15      # Seconds between heartbeats
    WS_HEARTBEAT_TIMEOUT: int = 45       # Mark agent dead after this
    WS_MAX_MESSAGE_SIZE: int = 65536     # 64KB max per WS message

    # ── Remediation command allowlist ──
    ALLOWED_REMEDIATION_ACTIONS: str = "restart_service,kill_process,cleanup_temp"

    class Config:
        env_file = str(_env_path)
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def allowed_actions_set(self) -> set[str]:
        return {a.strip() for a in self.ALLOWED_REMEDIATION_ACTIONS.split(",") if a.strip()}

    def validate_production_safety(self):
        """Check for unsafe production configuration. Called at startup."""
        from server.logging import get_logger
        logger = get_logger("config")

        if not self.JWT_SECRET_KEY:
            if self.is_production:
                raise RuntimeError(
                    "JWT_SECRET_KEY is not set! "
                    "Set a strong random secret: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            else:
                # Auto-generate a dev-only secret
                import secrets
                self.JWT_SECRET_KEY = secrets.token_urlsafe(64)
                logger.warning(
                    "JWT_SECRET_KEY not set — generated ephemeral dev secret. "
                    "Set JWT_SECRET_KEY in .env for persistent sessions."
                )

        if self.CORS_ORIGINS == "*" and self.is_production:
            logger.critical(
                "SECURITY WARNING: CORS_ORIGINS is '*' in production! "
                "Configure specific trusted origins."
            )

        if self.is_production:
            logger.info("Running in PRODUCTION mode")
        else:
            logger.info("Running in DEVELOPMENT mode")


settings = ServerSettings()
