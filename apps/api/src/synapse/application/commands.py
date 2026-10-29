"""Use-case commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartSessionCommand:
    problem_text: str
    answer: str
    work: str = ""
    stuck_at: str = ""
    confidence: int | None = None
    self_report: str | None = None
    mode: str = "learning"
    # Declared by the student; None means "let the identifier decide".
    subject: str | None = None


@dataclass(frozen=True, slots=True)
class SubmitAnswerCommand:
    answer: str
    option_id: str | None = None
