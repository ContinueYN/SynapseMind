"""Knowledge card search mapper."""

from __future__ import annotations

from synapse.api.schemas.knowledge import (
    KnowledgeHitOut,
    KnowledgeSearchOut,
    KnowledgeSourceOut,
)
from synapse.application.knowledge.service import KnowledgeSearch
from synapse.domain.knowledge.models import KnowledgeHit


def _knowledge_excerpt(body: str, limit: int = 300) -> str:
    if len(body) <= limit:
        return body
    return body[: limit - 1] + "…"


def _knowledge_hit(hit: KnowledgeHit) -> KnowledgeHitOut:
    card = hit.card
    return KnowledgeHitOut(
        card_id=card.id,
        kind=card.kind,
        subject=card.subject,
        verifications=list(card.verifications),
        title=card.title,
        excerpt=_knowledge_excerpt(card.body),
        source=KnowledgeSourceOut(
            title=card.source.title,
            url=card.source.url,
            license=card.source.license,
        ),
        score=round(max(0.0, min(1.0, hit.score)), 4),
    )


def knowledge_search_out(result: KnowledgeSearch) -> KnowledgeSearchOut:
    return KnowledgeSearchOut(
        version="0.2",
        enabled=result.enabled,
        query=result.query,
        hits=[_knowledge_hit(hit) for hit in result.hits],
    )
