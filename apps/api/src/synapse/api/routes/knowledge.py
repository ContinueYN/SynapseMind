"""Knowledge card search route."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from synapse.api.deps import get_knowledge_service
from synapse.api.mappers.knowledge import knowledge_search_out
from synapse.api.schemas.knowledge import KnowledgeSearchOut
from synapse.application.knowledge.service import KnowledgeService, KnowledgeUnavailable

router = APIRouter()


@router.get("/knowledge/search", response_model=KnowledgeSearchOut)
def search_knowledge(
    q: str = Query(min_length=2, max_length=200),
    subject: str | None = Query(default=None, min_length=1, max_length=40),
    verification: Literal["formal", "executable", "empirical", "argumentative"] | None = Query(
        default=None
    ),
    limit: int = Query(default=3, ge=1, le=5),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSearchOut:
    """Find sourced knowledge cards for a concept label.

    The query is a label, not the student's answer or work: callers must not
    send prose from the attempt. Retrieval is read-only and never advances a
    session or changes a diagnosis.
    """

    try:
        result = knowledge.search(
            q,
            subject=subject,
            verification=verification,
            limit=limit,
        )
    except KnowledgeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return knowledge_search_out(result)
