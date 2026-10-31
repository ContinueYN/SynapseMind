"""In-process vector index for the small checked-in corpus."""

from __future__ import annotations

from collections.abc import Sequence

from synapse.domain.knowledge.models import KnowledgeCard, KnowledgeHit
from synapse.infrastructure.knowledge.embedding import Embedder


class InMemoryKnowledgeIndex:
    """Cosine similarity over normalized vectors.

    The corpus is a few dozen cards, so a linear scan is simpler and faster than
    a vector database connection. The ``KnowledgeRetriever`` port keeps this
    replaceable with pgvector when the corpus and deployment grow.
    """

    def __init__(
        self,
        cards: Sequence[KnowledgeCard],
        embedder: Embedder,
        *,
        min_score: float = 0.0,
    ) -> None:
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score must be between 0 and 1")
        self._cards = tuple(cards)
        self._embedder = embedder
        self._min_score = min_score
        vectors = embedder.embed_passages(tuple(card.search_text() for card in self._cards))
        if len(vectors) != len(self._cards):
            raise ValueError("embedder returned a different number of vectors")
        self._vectors = vectors

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        limit: int = 3,
    ) -> tuple[KnowledgeHit, ...]:
        if limit <= 0 or not self._cards:
            return ()
        query_vector = self._embedder.embed_query(query)
        scored: list[tuple[float, KnowledgeCard]] = []
        for card, vector in zip(self._cards, self._vectors, strict=True):
            if subject is not None and card.subject != subject:
                continue
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            if score >= self._min_score:
                scored.append((score, card))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return tuple(KnowledgeHit(card=card, score=score) for score, card in scored[:limit])
