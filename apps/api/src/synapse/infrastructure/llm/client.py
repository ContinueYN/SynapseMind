"""OpenAI-compatible chat client (DeepSeek by default).

DeepSeek, Qwen and GLM all expose the same shape, so switching provider is a
base URL and a model name, not a code change. JSON mode is requested but never
trusted: ``schema.py`` validates every response.

``OpenAICompatibleClient`` binds one process-wide configuration; the BYOK runtime
uses ``CredentialAwareLLMClient`` instead, which builds a short-lived client per
call so one user's key is never reused for another user's request.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from synapse.application.context import current_owner_id
from synapse.application.credentials import (
    CredentialError,
    CredentialService,
    SecretCredential,
)
from synapse.application.llm import LLMCallFailed, LLMRequest, LLMResponse, LLMTimeout
from synapse.infrastructure.llm.settings import LLMSettings

MAX_TOKENS = 300


def _complete_with(
    client: httpx.Client,
    *,
    model: str,
    request: LLMRequest,
    timeout_s: float,
) -> LLMResponse:
    """One POST to ``/chat/completions``; the caller owns the httpx client."""

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
        "temperature": 0.0,
        "max_tokens": request.max_tokens or MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    started = time.perf_counter()
    try:
        response = client.post(
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
        model=str(body.get("model", model)),
        latency_ms=latency_ms,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
    )


class OpenAICompatibleClient:
    """A client bound to one fixed configuration (server key or a test fake)."""

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
        return _complete_with(
            self._client,
            model=self._settings.model,
            request=request,
            timeout_s=timeout_s,
        )

    def close(self) -> None:
        self._client.close()


class CredentialAwareLLMClient:
    """Resolve the caller's own model key on every ``complete`` call.

    Every model path built in ``api/deps.py`` shares this one client. When BYOK is
    on and the request is bound to a user with a saved credential, the call uses
    that credential's base URL/model/key; otherwise it uses the server-wide key;
    otherwise it raises :class:`LLMCallFailed`, which the existing adapters
    already turn into their rule fallback (coach → rules, composer → rules,
    graph → fallback/None). A decrypt failure is treated as "no credential" for
    the same reason: a broken saved key must not 500 a diagnosis.

    A short-lived ``httpx.Client`` is built per call and closed in a ``with``
    block, so a key cannot leak into a pooled connection shared with another
    user's request.
    """

    def __init__(
        self,
        settings: LLMSettings,
        *,
        credentials: CredentialService | None,
        transport_factory: Callable[[], httpx.BaseTransport | None] | None = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._transport_factory = transport_factory

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        credential = self._credential()
        transport = self._transport_factory() if self._transport_factory is not None else None
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {credential.api_key}",
        }
        with httpx.Client(
            base_url=credential.base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers=headers,
        ) as client:
            return _complete_with(
                client,
                model=credential.model,
                request=request,
                timeout_s=timeout_s,
            )

    def _credential(self) -> SecretCredential:
        if self._settings.byok and self._credentials is not None:
            user_id = current_owner_id()
            if user_id:
                try:
                    saved = self._credentials.resolve(user_id)
                except CredentialError:
                    # A saved key that cannot be decrypted is not a reason to
                    # fail the request; fall through to the server key.
                    saved = None
                if saved is not None:
                    return saved
        if self._settings.api_key:
            return SecretCredential(
                provider=self._settings.provider,
                base_url=self._settings.base_url,
                model=self._settings.model,
                api_key=self._settings.api_key,
            )
        raise LLMCallFailed(
            "no model credential available: no saved user key and no server-side key"
        )
