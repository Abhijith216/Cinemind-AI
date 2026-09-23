"""FastAPI application factory for CineMind."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, ratings, search
from app.core.config import get_settings
from app.core.db import dispose_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Close the DB engine cleanly on shutdown."""
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Build the CineMind FastAPI app."""
    settings = get_settings()
    app = FastAPI(
        title="CineMind API",
        version="0.1.0",
        description="Explainable AI movie discovery platform.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Health check at the root path, plus an /api/health alias.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(ratings.router, prefix="/api")
    return app


app = create_app()
