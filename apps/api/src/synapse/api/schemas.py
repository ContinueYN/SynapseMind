"""HTTP DTOs.

These are protocol shapes, not domain objects. Keeping them here prevents
FastAPI/Pydantic from leaking into the domain layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProblemIn(StrictModel):
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    image_url: str | None = Field(default=None, max_length=2000)
    subject: Literal["math", "physics"] = "math"
    grade: Literal["primary_school", "middle_school", "high_school"] = "high_school"

    @model_validator(mode="after")
    def require_text_or_image(self) -> ProblemIn:
        if not self.text and not self.image_url:
            raise ValueError("problem.text or problem.image_url is required")
        return self


class AttemptIn(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    work: str = Field(default="", max_length=8000)
    stuck_at: str = Field(default="", max_length=500)
    confidence: int | None = Field(default=None, ge=1, le=5)
    self_report: Literal["no_idea", "wrong", "unsure", "correct_but_guessed"] | None = None


class CreateSessionRequest(StrictModel):
    problem: ProblemIn
    attempt: AttemptIn
    locale: Literal["zh-CN", "en"] = "zh-CN"
    mode: Literal["learning"] = "learning"


class ProbeOut(StrictModel):
    action: Literal["ask", "hint", "confirm"]
    question: str
    options: list[str] = Field(default_factory=list, max_length=4)
    hint_level: int = Field(ge=0, le=3)
    reason_code: str
    confidence: float = Field(ge=0, le=1)


class ProgressOut(StrictModel):
    turn: int = Field(ge=0)
    max_turns: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    top_hypothesis: str


class HistoryItemOut(StrictModel):
    turn: int
    question: str
    answer: str
    option_id: str | None = None
    action: str
    is_unknown: bool = False


class NextActionOut(StrictModel):
    type: Literal["micro_lesson", "worked_example", "probe_more", "none"]
    concept_id: str | None = None
    duration_min: int | None = Field(default=None, ge=1, le=10)
    task_id: str | None = None


class VerifyOut(StrictModel):
    type: Literal["transfer", "none"]
    due_hours: int = Field(ge=1, le=168)
    item_id: str | None = None


class CardOut(StrictModel):
    layer: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
    label: str = Field(max_length=40)
    node_id: str = Field(pattern=r"^n[0-9]+$")
    one_line: str = Field(max_length=200)
    evidence: list[str] = Field(min_length=1, max_length=4)
    excluded: list[str] = Field(default_factory=list, max_length=4)
    confidence: float = Field(ge=0, le=1)
    confidence_label: Literal["high", "medium", "low"]
    next_action: NextActionOut
    verify: VerifyOut
    disagree: bool = False


class DiagnosisOut(StrictModel):
    version: Literal["0.1"]
    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    card: CardOut


class SessionOut(StrictModel):
    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    state: str
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    problem_title: str
    problem_text: str
    mode: str
    turn: int = Field(ge=0)
    max_turns: int = Field(ge=1)
    prompt: ProbeOut | None = None
    diagnosis: DiagnosisOut | None = None
    notice: str | None = None
    progress: ProgressOut
    history: list[HistoryItemOut] = Field(default_factory=list)


class TurnRequest(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    option_id: str | None = Field(default=None, max_length=20)


class HealthOut(StrictModel):
    status: Literal["ok"] = "ok"
    version: str
