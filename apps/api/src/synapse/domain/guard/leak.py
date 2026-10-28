"""Answer-leak rules.

This is a guard, not a prompt instruction. It is deliberately independent of
the LLM so it can be unit-tested and reused by any probe composer.
"""

from __future__ import annotations

from dataclasses import dataclass

from synapse.domain.problem.alignment import normalize, word_overlap


@dataclass(frozen=True, slots=True)
class LeakHit:
    rule: str
    detail: str


class AnswerLeakGuard:
    def __init__(
        self,
        forbidden: tuple[str, ...],
        reference_solution: str = "",
        *,
        ngram_threshold: float = 0.60,
    ) -> None:
        self._forbidden = tuple(item for item in forbidden if item.strip())
        self._reference = reference_solution
        self._threshold = ngram_threshold

    def find(self, text: str) -> tuple[LeakHit, ...]:
        hits: list[LeakHit] = []
        normalized = normalize(text)
        for token in self._forbidden:
            if normalize(token) and normalize(token) in normalized:
                hits.append(LeakHit(rule="forbidden_token", detail=token))
        if self._reference:
            overlap = word_overlap(text, self._reference)
            if overlap >= self._threshold:
                hits.append(
                    LeakHit(
                        rule="ngram_overlap",
                        detail=f"{overlap:.2f} >= {self._threshold:.2f}",
                    )
                )
        return tuple(hits)

    def is_safe(self, text: str) -> bool:
        return not self.find(text)
