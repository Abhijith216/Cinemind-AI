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
import time
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger("app.llm")

_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 0.5

TModel = TypeVar("TModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the chat endpoint fails for a non-retryable reason."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def category(self) -> str:
        if self.status_code in (401, 403):
            return "authentication"
        if self.status_code == 402:
            return "credits"
        if self.status_code == 429:
            return "rate_limit"
        if self.status_code is not None and self.status_code >= 500:
            return "provider_server"
        return "provider_request" if self.status_code else "network_or_response"


class ChatLLMClient:
    """Minimal typed client for POST /chat/completions with JSON mode."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float = 15.0,
        structured_outputs: bool = False,
        disable_reasoning: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "OPENAI_API_KEY is empty. Set it in backend/.env (or a "
                "compatible provider's key with OPENAI_BASE_URL)."
            )
        if not model.strip() or not base_url.strip():
            raise LLMError("Configure the chat provider endpoint and model")
        self._model = model
        self._structured_outputs = structured_outputs
        self._disable_reasoning = disable_reasoning
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
        if self._disable_reasoning:
            payload = {**payload, "reasoning": {"enabled": False}}
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            started = time.perf_counter()
            try:
                response = await self._client.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Chat provider attempt=%d category=network duration_ms=%d",
                    attempt + 1,
                    (time.perf_counter() - started) * 1000,
                )
                last_error = LLMError(type(exc).__name__)
                await _sleep_backoff(attempt)
                continue

            logger.info(
                "Chat provider attempt=%d status=%d category=%s duration_ms=%d",
                attempt + 1,
                response.status_code,
                "success"
                if response.status_code < 400
                else LLMError("Provider failure", status_code=response.status_code).category,
                (time.perf_counter() - started) * 1000,
            )

            if response.status_code == 429 or response.status_code >= 500:
                last_error = LLMError(
                    f"chat endpoint returned {response.status_code}",
                    status_code=response.status_code,
                )
                await _sleep_backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise LLMError(
                    f"chat endpoint returned {response.status_code}",
                    status_code=response.status_code,
                )

            try:
                body: dict[str, Any] = response.json()
            except ValueError as exc:
                raise LLMError("Chat provider returned invalid JSON") from exc
            if not isinstance(body, dict):
                raise LLMError("Chat provider returned an invalid response")
            return body

        raise LLMError(
            f"Gave up on chat endpoint after {_MAX_RETRIES} attempts: {last_error}",
            status_code=getattr(last_error, "status_code", None),
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
            {"model": self._model, "messages": messages, "temperature": 0.0, "max_tokens": 1024}
        )
        return _completion_content(body)

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
            "max_tokens": 1024,
        }
        if self._structured_outputs:
            schema = schema_model.model_json_schema()
            _require_schema_fields(schema)
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_model.__name__, "strict": True, "schema": schema},
            }

        body = await self._post_with_retry(payload)
        content = _completion_content(body)
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
            content = _completion_content(body)
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
        structured_outputs=settings.llm_structured_outputs,
        disable_reasoning=settings.llm_disable_reasoning,
    )


def _require_schema_fields(schema: dict[str, Any]) -> None:
    """Strict providers require all object fields, with null for optional values."""
    if "properties" in schema:
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
    schema.pop("default", None)
    for value in schema.values():
        if isinstance(value, dict):
            _require_schema_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _require_schema_fields(item)


def _completion_content(body: dict[str, Any]) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("Chat provider returned no completion") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Chat provider returned no usable completion")
    return content


async def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
    if retry_after is not None:
        try:
            await asyncio.sleep(min(2.0, max(0.0, float(retry_after))))
            return
        except ValueError:
            pass
    await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25))
