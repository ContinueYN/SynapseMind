"""LLM port.

Pure data and a Protocol: no provider SDK is imported here, which is what lets
``lint-imports`` keep model calls inside ``synapse.infrastructure.llm``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One structured-output call.

    ``json_schema`` is advisory: the provider may only honour ``json_object``,
    so the response is always validated again in ``infrastructure.llm.schema``.
    """

    purpose: str
    system: str
    user: str
    schema_name: str
    json_schema: Mapping[str, object] | None = None
    # A graph is an order of magnitude longer than a rewritten question; the
    # budget belongs to the request, not to the client.
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMTimeout(RuntimeError):
    """The provider did not answer within the per-call budget."""


class LLMCallFailed(RuntimeError):
    """Transport, auth or provider-side failure; never retried on the main path."""


class LLMClient(Protocol):
    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse: ...
