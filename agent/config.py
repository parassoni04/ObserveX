"""
ObserveX Agent Configuration System.

Loads configuration from (in priority order):
  1. Environment variables  (OBSERVEX_SERVER_URL, etc.)
  2. YAML config file       (config.yaml)
  3. Built-in defaults

After enrollment, device identity is persisted back to the YAML file.
"""
import os
import platform
import copy
import sys
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# ── Config file resolution ─────────────────────────────────────────────────
# Priority: OBSERVEX_CONFIG_PATH env → exe dir (if frozen) → cwd → ProgramData → local agent/config.yaml

def _resolve_config_path(for_writing: bool = False) -> Path:
    """Find the config file, checking env var, executable dir, cwd, system-wide, and local paths."""
    env_path = os.environ.get("OBSERVEX_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    # If running as a frozen PyInstaller executable
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        exe_config = exe_dir / "config.yaml"
        if for_writing:
            if os.name == "nt":
                prog_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ObserveX" / "config.yaml"
                if prog_data.exists():
                    return prog_data
            return exe_config

        if exe_config.exists():
            return exe_config
        if os.name == "nt":
            prog_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ObserveX" / "config.yaml"
            if prog_data.exists():
                return prog_data
        cwd_config = Path.cwd() / "config.yaml"
        if cwd_config.exists():
            return cwd_config
        bundled = Path(__file__).resolve().parent / "config.yaml"
        if bundled.exists():
            return bundled
        return exe_config

    # Non-frozen (running from source):
    # Check current working directory first if config.yaml exists here
    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    # System-wide location (Windows: ProgramData, Linux/Mac: /etc)
    if os.name == "nt":
        system_path = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ObserveX" / "config.yaml"
    else:
        system_path = Path("/etc/observex/config.yaml")
    if system_path.exists():
        return system_path

    # Local fallback (next to this file)
    local_path = Path(__file__).resolve().parent / "config.yaml"
    return local_path


# ── Pydantic Config Models ─────────────────────────────────────────────────

class ServerConfig(BaseModel):
    url: str = "http://localhost:8000"
    websocket_url: Optional[str] = None

    @property
    def ws_url(self) -> str:
        """Derive WebSocket URL from HTTP URL if not explicitly set."""
        if self.websocket_url:
            return self.websocket_url
        base = self.url
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1)
        return base.replace("http://", "ws://", 1)


class DeviceConfig(BaseModel):
    device_id: Optional[int] = None
    device_uuid: Optional[str] = None
    credential: Optional[str] = None
    name: Optional[str] = None

    @property
    def resolved_name(self) -> str:
        """Return configured name or fall back to system hostname."""
        return self.name or platform.node()


class AgentConfig(BaseModel):
    metrics_interval: float = Field(default=1.0, ge=0.1, le=60.0)
    heartbeat_interval: float = Field(default=10.0, ge=1.0, le=300.0)
    version: str = "2.1.0"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: Optional[str] = None

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"Invalid log level '{v}'. Must be one of {allowed}")
        return v_upper


class NetworkConfig(BaseModel):
    verify_ssl: bool = True
    connect_timeout: float = Field(default=10.0, ge=1.0, le=120.0)
    max_reconnect_backoff: float = Field(default=30.0, ge=1.0, le=300.0)


class ObserveXAgentSettings(BaseModel):
    """Top-level agent configuration container."""
    server: ServerConfig = ServerConfig()
    device: DeviceConfig = DeviceConfig()
    agent: AgentConfig = AgentConfig()
    logging: LoggingConfig = LoggingConfig()
    network: NetworkConfig = NetworkConfig()

    @property
    def is_enrolled(self) -> bool:
        """True if the agent has a device identity and credential from enrollment."""
        return bool(self.device.device_uuid and self.device.credential)


# ── Loader ──────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_overrides() -> dict:
    """Collect OBSERVEX_* environment variables and map them to config keys."""
    mapping = {
        "OBSERVEX_SERVER_URL": ("server", "url"),
        "OBSERVEX_WEBSOCKET_URL": ("server", "websocket_url"),
        "OBSERVEX_DEVICE_ID": ("device", "device_id"),
        "OBSERVEX_DEVICE_UUID": ("device", "device_uuid"),
        "OBSERVEX_DEVICE_CREDENTIAL": ("device", "credential"),
        "OBSERVEX_DEVICE_NAME": ("device", "name"),
        "OBSERVEX_METRICS_INTERVAL": ("agent", "metrics_interval"),
        "OBSERVEX_HEARTBEAT_INTERVAL": ("agent", "heartbeat_interval"),
        "OBSERVEX_LOG_LEVEL": ("logging", "level"),
        "OBSERVEX_LOG_FILE": ("logging", "file"),
        "OBSERVEX_VERIFY_SSL": ("network", "verify_ssl"),
        "OBSERVEX_CONNECT_TIMEOUT": ("network", "connect_timeout"),
        "OBSERVEX_STREAM_INTERVAL": ("agent", "metrics_interval"),  # backward compat
        "OBSERVEX_API_KEY": ("device", "credential"),  # backward compat
    }
    overrides: dict = {}
    for env_key, (section, field) in mapping.items():
        val = os.environ.get(env_key)
        if val is not None:
            overrides.setdefault(section, {})[field] = val
    return overrides


def load_config(config_path: Optional[Path] = None) -> ObserveXAgentSettings:
    """Load agent configuration from YAML + env overrides, validate with Pydantic."""
    path = config_path or _resolve_config_path()
    raw: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[Config] Warning: Failed to read {path}: {e}")

    # Merge env overrides on top of file values
    env = _env_overrides()
    if env:
        raw = _deep_merge(raw, env)

    return ObserveXAgentSettings(**raw)


# ── Persistence ─────────────────────────────────────────────────────────────

def save_config(settings: ObserveXAgentSettings, config_path: Optional[Path] = None) -> Path:
    """Persist current configuration to YAML file (used after enrollment)."""
    path = config_path or _resolve_config_path(for_writing=True)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build a clean dict, preserving only meaningful values
    data = settings.model_dump(mode="python")

    # Remove None values for cleaner YAML output
    def _clean(d: dict) -> dict:
        return {k: _clean(v) if isinstance(v, dict) else v for k, v in d.items() if v is not None}

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(_clean(data), f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return path


# ── Module-level singleton ──────────────────────────────────────────────────
# Backward-compatible: other modules can `from agent.config import agent_settings`

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

agent_settings = load_config()
