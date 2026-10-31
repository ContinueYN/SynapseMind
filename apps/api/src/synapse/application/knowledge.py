"""Read-only knowledge retrieval.

RAG here means "find a sourced explanation for a concept", not "let a model
write an answer". The retriever is a port so tests can use a deterministic
embedder and the application never imports a model runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synapse.domain.knowledge.models import KnowledgeHit


class KnowledgeUnavailable(RuntimeError):
    """The RAG switch is on but the local embedding runtime is not usable."""


class KnowledgeRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        limit: int = 3,
    ) -> tuple[KnowledgeHit, ...]: ...


@dataclass(frozen=True, slots=True)
class KnowledgeSearch:
    enabled: bool
    query: str
    hits: tuple[KnowledgeHit, ...]


class KnowledgeService:
    """Expose retrieval without leaking the model or corpus into the API layer."""

    def __init__(self, retriever: KnowledgeRetriever | None) -> None:
        self._retriever = retriever

    @property
    def enabled(self) -> bool:
        return self._retriever is not None

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        limit: int = 3,
    ) -> KnowledgeSearch:
        cleaned = query.strip()
        if self._retriever is None or not cleaned:
            return KnowledgeSearch(enabled=False, query=cleaned, hits=())
        return KnowledgeSearch(
            enabled=True,
            query=cleaned,
            hits=self._retriever.search(cleaned, subject=subject, limit=limit),
        )
