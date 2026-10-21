"""Address-based request budgets; never trust caller-supplied bearer identities.

Memory mode is bounded, single-process development protection. Database mode
uses atomic per-minute PostgreSQL counters shared across replicas and fails
closed when storage is unavailable. Keys are HMAC digests, expired counters
are pruned, and tokens/addresses are never logged. A zero limit disables checks.
Only explicitly trusted ingress proxies may supply forwarded client addresses.
"""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import get_sessionmaker

_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Fixed sliding-window counter per client, in process memory."""

    def __init__(self, name: str, limit_per_minute: int) -> None:
        self.name = name
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def _prune(self, key: str, now: float) -> None:
        window = self._hits[key]
        while window and now - window[0] >= _WINDOW_SECONDS:
            window.popleft()

    def check(self, key: str) -> int:
        """Register a hit; return seconds until the next slot (0 = allowed)."""
        if not self.enabled:
            return 0
        now = time.monotonic()
        if len(self._hits) >= 10000:
            for stale in list(self._hits):
                self._prune(stale, now)
                if not self._hits[stale]:
                    del self._hits[stale]
            if key not in self._hits and len(self._hits) >= 10000:
                return 60
        self._prune(key, now)
        window = self._hits[key]
        if len(window) >= self.limit:
            return max(1, int(_WINDOW_SECONDS - (now - window[0])) + 1)
        window.append(now)
        return 0


_limiters: dict[str, RateLimiter] = {}


def reset_all_limiters() -> None:
    """Clear every window (tests and config changes; not for production use)."""
    _limiters.clear()


def _get_limiter(name: str) -> RateLimiter:
    """One limiter instance per route name, created on first use."""
    if name not in _limiters:
        _limiters[name] = RateLimiter(name, 0)
    return _limiters[name]


def _limit_for(name: str) -> int:
    settings = get_settings()
    if name == "chat":
        return settings.chat_rate_limit_per_minute
    return settings.search_rate_limit_per_minute


def _client_key(request: Request) -> str:
    """Use the server-resolved client address, never an arbitrary bearer header.

    Proxy headers must only be accepted from explicitly trusted proxy addresses.
    All accounts on the same address share its budget; token rotation gives no reset.
    """
    host = request.client.host if request.client else "unknown"
    return f"host:{host}"


_cleanup_at = 0.0


async def database_check(name: str, key: str, limit: int) -> int:
    global _cleanup_at
    digest = hmac.new(
        get_settings().jwt_secret.encode(), f"{name}:{key}".encode(), hashlib.sha256
    ).hexdigest()
    async with get_sessionmaker()() as db:
        row = (
            await db.execute(
                text("""
            INSERT INTO rate_limit_buckets (key, bucket, hits)
            VALUES (:key, floor(extract(epoch FROM clock_timestamp()) / 60)::bigint, 1)
            ON CONFLICT (key, bucket) DO UPDATE SET hits = rate_limit_buckets.hits + 1
            WHERE rate_limit_buckets.hits < :limit
            RETURNING hits
        """),
                {"key": digest, "limit": limit},
            )
        ).scalar_one_or_none()
        if time.monotonic() - _cleanup_at > 60:
            await db.execute(
                text("""
                DELETE FROM rate_limit_buckets
                WHERE bucket < floor(extract(epoch FROM clock_timestamp()) / 60)::bigint - 2
            """)
            )
            _cleanup_at = time.monotonic()
        await db.commit()
    return 0 if row is not None else 60


def _limiter_dependency(name: str) -> Callable[..., object]:
    async def dependency(request: Request) -> None:
        limiter = _get_limiter(name)
        limiter.limit = _limit_for(name)  # fresh each request: tests/env live
        if not limiter.enabled:
            return
        try:
            retry_after = (
                await database_check(name, _client_key(request), limiter.limit)
                if get_settings().rate_limit_backend == "database"
                else limiter.check(_client_key(request))
            )
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            raise HTTPException(
                status_code=503,
                detail="Request protection is temporarily unavailable.",
                headers={"Retry-After": "5"},
            ) from exc
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded ({limiter.limit}/min on {limiter.name}). "
                    "Try again shortly."
                ),
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


chat_rate_limit = Annotated[None, Depends(_limiter_dependency("chat"))]
search_rate_limit = Annotated[None, Depends(_limiter_dependency("search"))]
