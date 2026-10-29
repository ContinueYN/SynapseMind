"""Problem identification (M2.5 S3).

M1 matched keywords: any text containing ``ln`` was treated as the seed
problem. That is not identification — a different derivative question would be
diagnosed with the seed graph, and its wrong answer would be explained by
nodes that have nothing to do with it.

This module replaces it with a deliberately strict rule: a submission is
accepted only when it *contains* an annotated problem's text, compared after
normalisation (whitespace, punctuation, full-width forms, LaTeX escapes). The
identifier is pure and model-free; chapter 13 §13.7 keeps it behind a port so
S4 can swap in a generated identifier without touching callers.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from synapse.domain.problem.models import Problem

# Whitespace, punctuation and LaTeX scaffolding carry no problem identity.
_DROP = re.compile(r"[\s。．.,，、;；:：!！?？'\"“”‘’()（）\[\]【】{}<>《》$\\]+")

MIN_LENGTH = 12


def normalize_problem_text(text: str) -> str:
    """Fold a text so cosmetic variants compare equal."""
    folded = unicodedata.normalize("NFKC", text).lower()
    return _DROP.sub("", folded)


class TextProblemIdentifier:
    """Identify strictly by containing an annotated problem's normalised text."""

    def __init__(self, catalog: Mapping[str, Problem], *, min_length: int = MIN_LENGTH) -> None:
        self._catalog = {
            problem.id: normalize_problem_text(problem.text) for problem in catalog.values()
        }
        self._min_length = min_length

    def identify(self, text: str) -> str | None:
        needle = normalize_problem_text(text)
        if len(needle) < self._min_length:
            return None

        best_id: str | None = None
        best_length = 0
        for problem_id, haystack in self._catalog.items():
            # Longest match wins: with more annotated problems, a short stem
            # contained in two problems must not shadow the longer one.
            if haystack and haystack in needle and len(haystack) > best_length:
                best_id, best_length = problem_id, len(haystack)
        return best_id
