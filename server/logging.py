"""
ObserveX Server — Structured Logging.

Centralized logging configuration with:
- Named loggers for each subsystem (observex.auth, observex.enrollment, etc.)
- Sensitive data filtering — never log passwords, tokens, or API keys
- Console + optional file output
- Consistent formatting across all modules

Usage:
    from server.logging import get_logger
    logger = get_logger("enrollment")
    logger.info("Device enrolled: device_id=%s", device_id)
"""
import logging
import re
import os

# Patterns that should never appear in logs — matches key=value pairs
# where the key looks sensitive and the value is 8+ non-whitespace chars
_SENSITIVE_PATTERNS = re.compile(
    r"(api_key|api[-_]?key|password|secret|token|credential|authorization|bearer)"
    r"\s*[=:]\s*['\"]?([^\s'\",:}{]{8,})",
    re.IGNORECASE,
)


class SensitiveFilter(logging.Filter):
    """Redact sensitive values from log records before output."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_PATTERNS.sub(r"\1=***REDACTED***", record.msg)
        if record.args:
            cleaned = []
            for arg in (record.args if isinstance(record.args, tuple) else (record.args,)):
                if isinstance(arg, str):
                    arg = _SENSITIVE_PATTERNS.sub(r"\1=***REDACTED***", arg)
                cleaned.append(arg)
            record.args = tuple(cleaned)
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the root ObserveX logger. Safe to call multiple times."""
    logger = logging.getLogger("observex")
    if logger.handlers:
        return logger  # Already configured

    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    console.addFilter(SensitiveFilter())
    logger.addHandler(console)

    # Optional file logging
    log_file = os.environ.get("OBSERVEX_LOG_FILE")
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SensitiveFilter())
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the observex namespace."""
    return logging.getLogger(f"observex.{name}")
