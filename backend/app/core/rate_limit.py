"""Rate limiting for expensive LLM-backed routes.

A minimal in-process sliding-window limiter — enough to protect the
OpenAI/TMDb budget on a single-process deployment. Deliberately NOT a
distributed limiter: when this app runs behind multiple workers, swap
``RateLimiter`` for a Redis-backed implementation behind the same
``chat_rate_limit`` / ``search_rate_limit`` dependency callables.

Limits are settings-driven (``CHAT_RATE_LIMIT_PER_MINUTE``,
``SEARCH_RATE_LIMIT_PER_MINUTE``), re-read on every request so env changes
and tests take effect without a restart. ``0`` disables the limiter
entirely (the demo/offline backend sets 0). Clients are identified by
bearer-token value when authenticated, else by client host — good enough
to stop one browser tab from burning the API budget.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param

from app.core.config import get_settings

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
    """Bearer-token value when present, else the client host."""
    authorization = request.headers.get("Authorization", "")
    scheme, param = get_authorization_scheme_param(authorization)
    if scheme.lower() == "bearer" and param:
        return f"token:{param}"
    host = request.client.host if request.client else "unknown"
    return f"host:{host}"


def _limiter_dependency(name: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        limiter = _get_limiter(name)
        limiter.limit = _limit_for(name)  # fresh each request: tests/env live
        if not limiter.enabled:
            return
        retry_after = limiter.check(_client_key(request))
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
