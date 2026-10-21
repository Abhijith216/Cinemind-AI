"""Check configured AI/TMDb services without displaying any credentials.

Run from backend: python -m app.services.check_integrations
Uses one public sample AI request and one public movie lookup. No DB writes.
"""

import asyncio
import json

from app.core.config import get_settings
from app.services.ingestion import TMDbClient, TMDbError
from app.services.llm_client import LLMError
from app.services.query_understanding import parse_query


async def check() -> bool:
    settings = get_settings()
    passed = True
    if not (settings.openai_api_key and settings.openai_base_url and settings.llm_model):
        print(
            "AI: not configured. Set OPENAI_API_KEY, OPENAI_BASE_URL and LLM_MODEL in backend/.env."
        )
        passed = False
    else:
        try:
            async with asyncio.timeout(45):
                intent = await parse_query("Find a comedy under 90 minutes, no horror.")
            assert intent.runtime_max is not None and intent.runtime_max <= 90
            assert "Comedy" in intent.genres_include
            print("AI: structured intent request succeeded.")
        except (LLMError, TimeoutError, AssertionError) as exc:
            status = getattr(exc, "status_code", None)
            category = next(
                (
                    name
                    for name in ("ConnectError", "ReadTimeout", "ConnectTimeout")
                    if name in str(exc)
                ),
                type(exc).__name__,
            )
            print(
                f"AI: check failed ({category}, HTTP status {status}). "
                "Verify connectivity, model access, key and account limits."
            )
            passed = False
    if not settings.tmdb_api_key:
        print("TMDb: not configured. Set TMDB_API_KEY to an API key or Read Access Token.")
        passed = False
    else:
        try:
            async with TMDbClient(settings.tmdb_api_key, max_retries=2) as client:
                detail = await client.movie_bundle(157336)
            assert detail["id"] == 157336 and detail.get("title")
            print("TMDb: movie details, keywords and poster lookup succeeded.")
        except (TMDbError, AssertionError, KeyError) as exc:
            reason = str(exc) if isinstance(exc, TMDbError) else type(exc).__name__
            print(f"TMDb: check failed ({reason}). Verify connectivity and the read token/API key.")
            passed = False
    print(json.dumps({"all_configured_services_verified": passed}))
    return passed


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(check()) else 1)
