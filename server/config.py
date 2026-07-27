import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class ServerSettings(BaseSettings):
    """Centralized server configuration loaded from environment / .env file."""

    DATABASE_URL: str = "postgresql+asyncpg://observex:observex_secret@localhost:5432/observex"
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000
    METRIC_RETENTION_DAYS: int = 7
    CORS_ORIGINS: str = "*"
    JWT_SECRET_KEY: str = "change-me-to-a-secure-jwt-secret-key-12345"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    class Config:
        env_file = str(_env_path)
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = ServerSettings()
