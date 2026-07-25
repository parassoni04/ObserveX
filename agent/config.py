import platform
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class AgentSettings(BaseSettings):
    """Agent-side configuration loaded from environment / .env file."""

    OBSERVEX_SERVER_URL: str = "http://localhost:8000"
    OBSERVEX_API_KEY: str = "change-me-to-a-secure-key"
    OBSERVEX_DEVICE_NAME: str = ""
    OBSERVEX_STREAM_INTERVAL: float = 1.0

    class Config:
        env_file = str(_env_path)
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def device_name(self) -> str:
        return self.OBSERVEX_DEVICE_NAME or platform.node()

    @property
    def ws_url(self) -> str:
        """Convert HTTP URL to WebSocket URL."""
        base = self.OBSERVEX_SERVER_URL
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1)
        return base.replace("http://", "ws://", 1)


agent_settings = AgentSettings()
