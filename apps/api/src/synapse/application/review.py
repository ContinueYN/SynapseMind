"""Review queue for cards the student explicitly disagreed with.

The queue stores the card's own conclusion, not the student's work: a reviewer
needs the diagnosis, layer, node and confidence to decide whether the card was
right, and the original text already lives in the session (in memory today).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synapse.domain.diagnosis.models import DiagnosisCard


@dataclass(frozen=True, slots=True)
class ReviewItem:
    session_id: str
    problem_id: str
    layer: str
    label: str
    node_id: str
    one_line: str
    confidence: float
    created_at: str

    @classmethod
    def from_card(cls, card: DiagnosisCard, *, created_at: str) -> ReviewItem:
        return cls(
            session_id=card.session_id,
            problem_id=card.problem_id,
            layer=card.layer,
            label=card.label,
            node_id=card.node_id,
            one_line=card.one_line,
            confidence=card.confidence,
            created_at=created_at,
        )


class ReviewQueue(Protocol):
    def record(self, item: ReviewItem) -> None: ...

    def items(self) -> list[ReviewItem]: ...
