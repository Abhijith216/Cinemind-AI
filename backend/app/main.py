"""FastAPI application factory for CineMind."""

import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, health, movies, ratings, search, users
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.logging import configure_logging

logger = logging.getLogger("cinemind")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Configure logging on boot; close the DB engine cleanly on shutdown."""
    configure_logging()
    logger.info("cinemind api starting", extra={"version": _app.version})
    yield
    await dispose_engine()
    logger.info("cinemind api stopped")


async def log_requests(request: Request, call_next: object) -> object:
    """Emit one access-log line per request (skips /health noise)."""
    start = time.perf_counter()
    handler = cast(Callable[[Request], Awaitable[object]], call_next)
    response = await handler(request)
    path = request.url.path
    if path not in {"/health", "/api/health"}:
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,  # type: ignore[attr-defined]
                "duration_ms": round(
                    (time.perf_counter() - start) * 1000, 1
                ),
            },
        )
    return response


def create_app() -> FastAPI:
    """Build the CineMind FastAPI app with the full documented API surface."""
    settings = get_settings()
    app = FastAPI(
        title="CineMind API",
        version="0.1.0",
        description=(
            "Explainable AI movie discovery platform. "
            "Interactive docs: /docs (Swagger UI) and /redoc."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(log_requests)
    # Health check at the root path, plus an /api/health alias.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api")
    # Versioned API surface.
    app.include_router(auth.router, prefix="/api")
    app.include_router(movies.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(ratings.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    return app


app = create_app()
