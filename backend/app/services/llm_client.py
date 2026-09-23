"""Shared OpenAI-compatible chat-completions client (JSON mode).

Used by every LLM-powered module (query understanding now, explanations and
conversation later). Retries transient failures with exponential backoff and
performs one self-repair round-trip when the model's JSON fails schema
validation — no regex parsing of model output, ever.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger("app.llm")

_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 0.5

TModel = TypeVar("TModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the chat endpoint fails for a non-retryable reason."""


class ChatLLMClient:
    """Minimal typed client for POST /chat/completions with JSON mode."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "OPENAI_API_KEY is empty. Set it in backend/.env (or a "
                "compatible provider's key with OPENAI_BASE_URL)."
            )
        self._model = model
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self._client.aclose()

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                await _sleep_backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = LLMError(f"chat endpoint returned {response.status_code}")
                await _sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise LLMError(
                    f"chat endpoint returned {response.status_code}: {response.text[:200]}"
                )

            body: dict[str, Any] = response.json()
            return body

        raise LLMError(
            f"Gave up on chat endpoint after {_MAX_RETRIES} attempts: {last_error}"
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        history: Sequence[Mapping[str, str]] = (),
    ) -> str:
        """Plain-text completion (no JSON mode) for wording-level tasks."""
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(dict(item) for item in history)
        messages.append({"role": "user", "content": user_prompt})

        body = await self._post_with_retry(
            {"model": self._model, "messages": messages, "temperature": 0.0}
        )
        content: str = body["choices"][0]["message"]["content"]
        return content

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[TModel],
        history: Sequence[Mapping[str, str]] = (),
    ) -> TModel:
        """Request a JSON reply validated against ``schema_model``.

        Uses JSON mode (``response_format``) plus one self-repair retry that
        feeds the validation error back to the model.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(dict(item) for item in history)
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        body = await self._post_with_retry(payload)
        content = body["choices"][0]["message"]["content"]
        try:
            return schema_model.model_validate_json(content)
        except ValidationError as first_error:
            logger.warning("LLM JSON failed validation once; requesting repair")
            repair_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "Your JSON did not match the required schema. Error:\n"
                        f"{first_error}\nReturn ONLY corrected JSON."
                    ),
                },
            ]
            repair_payload = {**payload, "messages": repair_messages}
            body = await self._post_with_retry(repair_payload)
            content = body["choices"][0]["message"]["content"]
            try:
                return schema_model.model_validate_json(content)
            except ValidationError as second_error:
                raise LLMError(
                    f"LLM JSON failed schema validation after repair: {second_error}"
                ) from second_error


def create_chat_client() -> ChatLLMClient:
    """Build a ChatLLMClient from application settings (shared by modules)."""
    settings = get_settings()
    return ChatLLMClient(
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        base_url=settings.openai_base_url,
    )


async def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
    if retry_after is not None:
        try:
            await asyncio.sleep(max(0.0, float(retry_after)))
            return
        except ValueError:
            pass
    await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25))
