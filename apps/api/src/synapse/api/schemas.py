"""HTTP DTOs.

These are protocol shapes, not domain objects. Keeping them here prevents
FastAPI/Pydantic from leaking into the domain layer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProblemIn(StrictModel):
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    image_url: str | None = Field(default=None, max_length=2000)
    subject: Literal["math", "physics", "chinese"] = "math"
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


class HintStepOut(StrictModel):
    node_id: str = Field(pattern=r"^n[0-9]+$")
    text: str = Field(min_length=1, max_length=200)
    status: Literal["covered", "partial", "missing"]


class HintOut(StrictModel):
    """NONE-tier output: coverage of the reference structure, not a diagnosis.

    Kept separate from ``DiagnosisOut`` on purpose — it has no layer, no
    confidence and no ``next_action``/``verify``, so a client cannot render it
    as a card by mistake (M2.5 S7; v0.2 since S8,
    ``specs/structure-hint.schema.json``).

    ``status="partial"`` means at least one clause matched but coverage stayed
    below the covered threshold. It never means "wrong", and only the NONE
    tier's clause aligner emits it.
    """

    version: Literal["0.2"]
    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    subject: str = Field(min_length=1, max_length=32)
    level: Literal["none"]
    one_line: str = Field(min_length=1, max_length=200)
    steps: list[HintStepOut] = Field(default_factory=list, max_length=20)
    focus_node_id: str | None = Field(default=None, pattern=r"^n[0-9]+$")
    next_step: str = Field(default="", max_length=200)
    disclaimer: str = Field(min_length=1, max_length=300)


class SessionOut(StrictModel):
    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    state: str
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    problem_title: str
    problem_text: str
    subject: str = Field(min_length=1, max_length=32)
    mode: str
    turn: int = Field(ge=0)
    max_turns: int = Field(ge=1)
    prompt: ProbeOut | None = None
    diagnosis: DiagnosisOut | None = None
    hint: HintOut | None = None
    notice: str | None = None
    progress: ProgressOut
    history: list[HistoryItemOut] = Field(default_factory=list)


class TurnRequest(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    option_id: str | None = Field(default=None, max_length=20)


class StepRequest(StrictModel):
    """One step to verify; ``data`` is a subject-owned structured payload.

    The text is enough for math's equality-chain check. Physics needs
    ``data`` (``equation``/``expression``, units, values); its parser owns the
    validation and returns ``unknown`` for keys it cannot read.
    """

    text: str = Field(min_length=1, max_length=8000)
    node_id: str = Field(default="", max_length=64)
    data: dict[str, Any] | None = None


class StepVerdictOut(StrictModel):
    version: Literal["0.1"]
    status: Literal["pass", "fail", "unknown"]
    detail: str = Field(default="", max_length=1000)


class HealthOut(StrictModel):
    status: Literal["ok"] = "ok"
    version: str
