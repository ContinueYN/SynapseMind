"""Use-case commands."""

from __future__ import annotations

from collections.abc import Mapping
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

    @property
    def knows_nothing(self) -> bool:
        """Mirror ``StudentAttempt.knows_nothing`` before the attempt exists."""

        return self.self_report == "no_idea" or self.answer.strip() in {
            "",
            "不会",
            "不知道",
            "完全不会",
        }


@dataclass(frozen=True, slots=True)
class SubmitAnswerCommand:
    answer: str
    option_id: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyStepCommand:
    """One free-text step; ``data`` is an optional subject-owned payload."""

    text: str
    node_id: str = ""
    data: Mapping[str, object] | None = None
