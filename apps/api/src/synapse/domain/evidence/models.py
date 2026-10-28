"""Evidence chain.

Evidence is a first-class value object, not a string glued onto a card. It
records *why* a hypothesis gained or lost support and keeps the source/turn
traceable for review and evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EvidenceSource = Literal["alignment", "probe", "self_report"]


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    source: EvidenceSource
    claim: str
    supports: tuple[str, ...] = ()
    turn: int | None = None


@dataclass
class EvidenceChain:
    items: list[Evidence] = field(default_factory=list)

    def add(self, item: Evidence) -> None:
        if any(existing.id == item.id for existing in self.items):
            return
        self.items.append(item)

    def claims(self, limit: int = 4) -> tuple[str, ...]:
        seen: set[str] = set()
        claims: list[str] = []
        for item in self.items:
            if item.claim in seen:
                continue
            seen.add(item.claim)
            claims.append(item.claim)
            if len(claims) >= limit:
                break
        return tuple(claims)

    def for_hypothesis(self, hypothesis_id: str) -> tuple[Evidence, ...]:
        return tuple(item for item in self.items if hypothesis_id in item.supports)

    def latest(self, source: EvidenceSource, limit: int = 1) -> tuple[str, ...]:
        claims = [item.claim for item in reversed(self.items) if item.source == source]
        return tuple(reversed(claims[:limit]))
