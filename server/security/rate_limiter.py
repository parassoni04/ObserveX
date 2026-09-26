"""
Rate Limiter
============

Lightweight in-memory sliding window rate limiter.
No external dependencies (no Redis, no slowapi).
Suitable for single-server deployments.
"""
import time
from collections import defaultdict
from typing import Optional
from fastapi import HTTPException, Request, status
from server.logging import get_logger

logger = get_logger("ratelimit")


class RateLimiter:
    """
    Simple sliding-window rate limiter usable as a FastAPI dependency.

    Usage:
        rate_limit = RateLimiter(max_calls=5, window_seconds=60)

        @router.post("/login")
        async def login(..., _rl=Depends(rate_limit)):
            ...
    """

    def __init__(self, max_calls: int, window_seconds: int, key_func: Optional[str] = "ip"):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.key_func = key_func
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup: float = time.time()

    def _get_key(self, request: Request) -> str:
        """Extract rate limit key from request."""
        if self.key_func == "ip":
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return request.client.host if request.client else "unknown"
        return "global"

    def _cleanup(self):
        """Periodically remove expired entries to prevent memory growth."""
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        cutoff = now - self.window_seconds
        expired_keys = []
        for key, timestamps in self._requests.items():
            self._requests[key] = [t for t in timestamps if t > cutoff]
            if not self._requests[key]:
                expired_keys.append(key)
        for key in expired_keys:
            del self._requests[key]

    async def __call__(self, request: Request):
        """FastAPI dependency — raises 429 if rate limit exceeded."""
        self._cleanup()

        key = self._get_key(request)
        now = time.time()
        cutoff = now - self.window_seconds

        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]

        if len(self._requests[key]) >= self.max_calls:
            logger.warning("Rate limit exceeded: key=%s endpoint=%s", key, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )

        self._requests[key].append(now)


# Pre-configured limiters for common endpoints
login_limiter = RateLimiter(max_calls=10, window_seconds=60)
registration_limiter = RateLimiter(max_calls=5, window_seconds=300)
enrollment_limiter = RateLimiter(max_calls=10, window_seconds=60)
