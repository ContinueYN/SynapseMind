"""Deterministic client for CI and shadow replays (ADR-0001: ReplayBrain).

Recorded responses are keyed by a hash of the request, so a prompt edit turns
into a visible "replay miss" instead of a silently different result.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from synapse.application.llm import LLMCallFailed, LLMRequest, LLMResponse


def request_key(request: LLMRequest) -> str:
    material = "\x1f".join(
        (request.purpose, request.schema_name, request.system, request.user)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ReplayLLMClient:
    def __init__(
        self,
        responses: Mapping[str, str],
        *,
        model: str = "replay-v1",
    ) -> None:
        self._responses = dict(responses)
        self._model = model

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        key = request_key(request)
        text = self._responses.get(key)
        if text is None:
            raise LLMCallFailed(f"replay miss for {request.purpose}/{request.schema_name}")
        return LLMResponse(text=text, model=self._model, latency_ms=0)