"""Structured-output validation (T4).

The model may only rewrite wording. Options, action and reason code are derived
from the graph, so a wandering model cannot change *what* is asked, only how it
is said. Every rejection has a short reason that lands in the audit log.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

MIN_CHARS = 4
MAX_CHARS = 80


class SchemaRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Rewrite(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    question: str


def parse_rewrite(text: str) -> str:
    """Return the rewritten question, or raise ``SchemaRejected(reason)``."""
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaRejected("not_json") from exc
    if not isinstance(payload, dict):
        raise SchemaRejected("not_object")
    try:
        rewrite = _Rewrite.model_validate(payload)
    except ValidationError as exc:
        raise SchemaRejected("missing_question") from exc

    question = rewrite.question
    if "\n" in question:
        raise SchemaRejected("multi_line")
    if len(question) < MIN_CHARS:
        raise SchemaRejected("too_short")
    if len(question) > MAX_CHARS:
        raise SchemaRejected("too_long")
    if _question_marks(question) != 1:
        # Hard constraint #1: one question per turn.
        raise SchemaRejected("question_marks")
    return question


def _question_marks(text: str) -> int:
    return text.count("？") + text.count("?")
