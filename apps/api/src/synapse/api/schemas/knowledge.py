"""Knowledge search DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from synapse.api.schemas.common import StrictModel


class KnowledgeSourceOut(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    license: str = Field(min_length=1, max_length=80)


KnowledgeKindOut = Literal["concept", "pattern", "method", "error", "source"]
KnowledgeVerificationOut = Literal["formal", "executable", "empirical", "argumentative"]


class KnowledgeHitOut(StrictModel):
    card_id: str = Field(pattern=r"^K_[A-Z0-9_]+$")
    kind: KnowledgeKindOut
    subject: str = Field(min_length=1, max_length=40)
    verifications: list[KnowledgeVerificationOut] = Field(min_length=1, max_length=4)
    title: str = Field(min_length=1, max_length=60)
    excerpt: str = Field(min_length=1, max_length=300)
    source: KnowledgeSourceOut
    score: float = Field(ge=0, le=1)


class KnowledgeSearchOut(StrictModel):
    """Read-only knowledge lookup; ``enabled=false`` hides the panel client-side."""

    version: Literal["0.2"]
    enabled: bool
    query: str = Field(max_length=200)
    hits: list[KnowledgeHitOut] = Field(default_factory=list, max_length=5)
