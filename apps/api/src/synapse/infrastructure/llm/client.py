"""OpenAI-compatible chat client (DeepSeek by default).

DeepSeek, Qwen and GLM all expose the same shape, so switching provider is a
base URL and a model name, not a code change. JSON mode is requested but never
trusted: ``schema.py`` validates every response.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from synapse.application.llm import LLMCallFailed, LLMRequest, LLMResponse, LLMTimeout
from synapse.infrastructure.llm.settings import LLMSettings

MAX_TOKENS = 300


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self._client = httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.timeout_s,
            transport=transport,
            headers=headers,
        )

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        started = time.perf_counter()
        try:
            response = self._client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"{request.purpose}: timeout after {timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise LLMCallFailed(f"{request.purpose}: transport error: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code >= 400:
            raise LLMCallFailed(
                f"{request.purpose}: HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMCallFailed(f"{request.purpose}: malformed provider response") from exc
        if not isinstance(text, str) or not text.strip():
            raise LLMCallFailed(f"{request.purpose}: empty completion")

        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(body.get("model", self._settings.model)),
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    def close(self) -> None:
        self._client.close()