"""A knowledge card is an explanation with a source, not a model answer.

The card is deliberately small: it says what the concept is and where it comes
from. Retrieval never turns a card into a claim about the student's ability, and
the source is carried through the API so the UI can show it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    title: str
    url: str
    license: str


@dataclass(frozen=True, slots=True)
class KnowledgeCard:
    id: str
    subject: str
    title: str
    body: str
    tags: tuple[str, ...]
    source: KnowledgeSource

    def search_text(self) -> str:
        """Text embedded for the card; tags are included on purpose."""

        return f"{self.title}\n{' '.join(self.tags)}\n{self.body}"


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    card: KnowledgeCard
    score: float
