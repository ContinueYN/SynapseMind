"""HTTP DTOs.

These are protocol shapes, not domain objects. Keeping them here prevents
FastAPI/Pydantic from leaking into the domain layer.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProblemIn(StrictModel):
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    image_url: str | None = Field(default=None, max_length=2000)
    # Phase 0: an open domain label, not a whitelist. Omit it and the system
    # detects; a label the system does not know still starts a generic session.
    subject: str | None = Field(
        default=None,
        max_length=32,
        description="可选领域标签（开放取值）。省略时自动识别；识别不出进入通用模式，不返回 422。",
    )
    grade: Literal["primary_school", "middle_school", "high_school"] = "high_school"

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

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


class AttributionDimensionOut(StrictModel):
    key: str = Field(min_length=1, max_length=16)
    label: str = Field(min_length=1, max_length=20)
    weight: float = Field(ge=0, le=1)


class AttributionOut(StrictModel):
    dimensions: list[AttributionDimensionOut] = Field(min_length=1, max_length=2)
    all_dimensions: list[AttributionDimensionOut] = Field(
        default_factory=list,
        max_length=7,
        description="Full seven-dimension demand vector; 0 marks a dimension without a tag.",
    )
    note: str = Field(min_length=1, max_length=100)


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
    # Present only when the CHC flag is on and the focus node has demand tags.
    attribution: AttributionOut | None = Field(default=None, exclude_if=lambda value: value is None)


class DiagnosisOut(StrictModel):
    version: Literal["0.1", "0.2"]
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


class ScaffoldStepOut(StrictModel):
    label: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=200)
    node_id: str | None = Field(default=None, pattern=r"^n[0-9]+$")


class ScaffoldOut(StrictModel):
    """A blank-attempt example: at most two steps, never the final answer."""

    steps: list[ScaffoldStepOut] = Field(min_length=1, max_length=2)
    focus_node_id: str | None = Field(default=None, pattern=r"^n[0-9]+$")
    next_step: str = Field(min_length=1, max_length=200)
    disclaimer: str = Field(min_length=1, max_length=300)


class DomainOut(StrictModel):
    """The resolved open domain label (Phase 0).

    ``subject`` remains for compatibility and is the plugin key; this object is
    what a client displays and what decides the verification promise.
    """

    name: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=40)
    verification: Literal["formal", "executable", "empirical", "argumentative"]
    generic: bool
    confidence: float = Field(ge=0, le=1)


class IntakeNodeOut(StrictModel):
    """One structure node shown on the intake card (v0.3)."""

    kind: Literal[
        "goal",
        "given",
        "constraint",
        "assumption",
        "plan",
        "action",
        "evidence",
        "check",
        "decision",
        "risk",
        "next",
    ]
    label: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=120)
    source: Literal["student", "system"]


class IntakeVerificationOut(StrictModel):
    """A formal/empirical verdict; ``unknown`` means it was not checked."""

    kind: Literal["formal", "empirical"]
    status: Literal["pass", "fail", "unknown"]
    detail: str = Field(min_length=1, max_length=400)


class IntakeProbeOut(StrictModel):
    """One bounded structural follow-up; not a diagnostic probe.

    ``answered`` is the number already stored, so the client can show
    ``answered/limit`` without guessing. The question asks for a missing piece
    (goal, constraint, option…), never for an answer or a verdict.
    """

    kind: Literal[
        "goal",
        "given",
        "constraint",
        "assumption",
        "plan",
        "action",
        "evidence",
        "check",
        "decision",
        "risk",
        "next",
    ]
    question: str = Field(min_length=1, max_length=200)
    answered: int = Field(ge=0, le=3)
    limit: int = Field(ge=1, le=3)


class GenericReviewDomainOut(StrictModel):
    """The open domain label plus what the review could be checked against."""

    name: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=40)
    verification: Literal["formal", "executable", "empirical", "argumentative"]


class GenericFindingOut(StrictModel):
    """One "saw / did not see" item; always tied to evidence in the same review."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=40)
    severity: Literal["blocking", "notable"]
    summary: str = Field(min_length=1, max_length=240)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class GenericEvidenceOut(StrictModel):
    """One source behind a finding; ``ref`` points at the source itself."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    source: Literal["student", "graph", "execution", "knowledge"]
    ref: str = Field(min_length=1, max_length=80)
    excerpt: str | None = Field(default=None, min_length=1, max_length=200)


class ReviewOptionOut(StrictModel):
    """One decision option. The contract has no score, rank or recommendation."""

    label: str = Field(min_length=1, max_length=80)
    costs: list[str] = Field(max_length=6)
    risks: list[str] = Field(max_length=6)
    reversible_test: str = Field(max_length=200)


class ReviewExecutionOut(StrictModel):
    """A code reproduction record from an explicit run. ``skipped`` means nothing ran."""

    status: Literal["pass", "fail", "timeout", "rejected", "skipped"]
    first_failure: str | None = Field(default=None, min_length=1, max_length=300)
    stdout_excerpt: str | None = Field(default=None, max_length=400)
    tests_submitted: bool = False


class GenericReviewOut(StrictModel):
    """Generic review contract v0.1: structure, decision or code reproduction.

    Mirrors ``specs/generic-review.schema.json``. The API attaches it to an
    ``intake`` response or returns it from ``review/run``; it is derived, never
    stored, and never a diagnosis.
    """

    version: Literal["0.1"]
    session_id: str = Field(pattern=r"^S_[A-Za-z0-9_]+$", max_length=40)
    problem_id: str = Field(pattern=r"^P_[A-Za-z0-9_]+$", max_length=48)
    kind: Literal["structure", "decision", "execution"]
    domain: GenericReviewDomainOut
    headline: str = Field(min_length=1, max_length=200)
    findings: list[GenericFindingOut] = Field(max_length=12)
    evidence: list[GenericEvidenceOut] = Field(max_length=24)
    not_checked: list[str] = Field(max_length=8)
    next_step: str = Field(min_length=1, max_length=240)
    disclaimer: str = Field(min_length=1, max_length=300)
    options: list[ReviewOptionOut] | None = Field(
        default=None,
        min_length=2,
        max_length=6,
        exclude_if=lambda value: value is None,
    )
    tradeoff_question: str | None = Field(
        default=None,
        max_length=300,
        exclude_if=lambda value: value is None,
    )
    execution: ReviewExecutionOut | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ReviewRunRequest(StrictModel):
    """Explicit code for one reproduction card; ``tests`` is optional.

    The API never extracts code from the problem or the attempt: the caller must
    paste it. A blank ``tests`` string means "no tests submitted", while blank
    code is a validation error.
    """

    code: str = Field(min_length=1, max_length=20000)
    tests: str = Field(default="", max_length=20000)

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be blank")
        return value

    @field_validator("tests")
    @classmethod
    def blank_tests_mean_not_submitted(cls, value: str) -> str:
        return "" if not value.strip() else value


class DomainIntakeOut(StrictModel):
    """The reference-free generic entry: structure, never a diagnosis.

    v0.2 added the answer-aware part: ``observed`` is what the student's own text
    mentions, ``gaps`` is what the mode requires and the text does not mention
    (at most three). v0.3 adds ``origin``/``graph`` (the generated or extracted
    structure, with its source) and ``verifications`` (formal/empirical only).
    v0.4 adds ``probe``: one at-a-time structural follow-up, capped at three.
    v0.5 adds ``review``: the optional v0.1 ``GenericReview`` (structure or
    decision), first composed for ARGUMENTATIVE modes. None of these is a verdict
    on the student's work.
    """

    version: Literal["0.5"]
    domain: DomainOut
    one_line: str = Field(min_length=1, max_length=200)
    checklist: list[str] = Field(min_length=1, max_length=6)
    observed: list[str] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=3)
    origin: Literal["student", "system"] | None = None
    graph: list[IntakeNodeOut] = Field(default_factory=list, max_length=12)
    verifications: list[IntakeVerificationOut] = Field(default_factory=list, max_length=2)
    clarifier: str | None = Field(default=None, max_length=200)
    probe: IntakeProbeOut | None = None
    next_step: str = Field(min_length=1, max_length=300)
    disclaimer: str = Field(min_length=1, max_length=300)
    review: GenericReviewOut | None = None


class SessionOut(StrictModel):
    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    state: str
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    problem_title: str
    problem_text: str
    subject: str = Field(min_length=1, max_length=32)
    domain: DomainOut
    mode: str
    turn: int = Field(ge=0)
    max_turns: int = Field(ge=1)
    prompt: ProbeOut | None = None
    diagnosis: DiagnosisOut | None = None
    hint: HintOut | None = None
    scaffold: ScaffoldOut | None = None
    intake: DomainIntakeOut | None = None
    notice: str | None = None
    # Only populated by an explicit exit-with-reveal request. Learning-mode
    # responses omit the keys entirely (``exclude_if``), so a regression test can
    # keep asserting that no "solution" key exists on a probe turn.
    answer: str | None = Field(default=None, exclude_if=lambda value: value is None)
    solution: str | None = Field(default=None, exclude_if=lambda value: value is None)
    progress: ProgressOut
    history: list[HistoryItemOut] = Field(default_factory=list)


class TurnRequest(StrictModel):
    answer: str = Field(min_length=1, max_length=2000)
    option_id: str | None = Field(default=None, max_length=20)


class ExitRequest(StrictModel):
    """Explicit opt-in to the answer store; the default exit reveals nothing."""

    reveal: bool = False


class ClarifierRequest(StrictModel):
    """One answer to the intake's single clarifying question."""

    answer: str = Field(min_length=1, max_length=500)


class IntakeProbeRequest(StrictModel):
    """One answer to the intake's current structural follow-up."""

    answer: str = Field(min_length=1, max_length=500)


class StepRequest(StrictModel):
    """One step to verify; ``data`` is a subject-owned structured payload.

    The text is enough for math's equality-chain check. Physics needs
    ``data`` (``equation``/``expression``, units, values); its parser owns the
    validation and returns ``unknown`` for keys it cannot read.
    """

    text: str = Field(min_length=1, max_length=8000)
    node_id: str = Field(default="", max_length=64)
    data: dict[str, Any] | None = None


class StepFindingOut(StrictModel):
    """One failed comparison, in a shape the client can lay out (v0.3)."""

    kind: Literal["identity", "limit", "quantity"]
    left: str = Field(min_length=1, max_length=500)
    right: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=300)
    counterexample: str = Field(default="", max_length=300)


class StepVerdictOut(StrictModel):
    version: Literal["0.3"]
    status: Literal["pass", "fail", "unknown"]
    detail: str = Field(default="", max_length=1000)
    findings: list[StepFindingOut] = Field(max_length=3)


class ExecutionRequestIn(StrictModel):
    """Only explicit code; the executor never extracts code from a problem."""

    language: Literal["python"]
    code: str = Field(min_length=1, max_length=20000)
    tests: str = Field(default="", max_length=20000)


class ExecutionFindingOut(StrictModel):
    code: Literal[
        "forbidden_import",
        "forbidden_call",
        "forbidden_attribute",
        "syntax_error",
        "too_large",
        "sandbox_unavailable",
    ]
    message: str = Field(min_length=1, max_length=300)


class ExecutionOut(StrictModel):
    version: Literal["0.1"]
    status: Literal["pass", "fail", "timeout", "rejected"]
    detail: str = Field(max_length=1000)
    exit_code: int | None
    duration_ms: int = Field(ge=0, le=60000)
    stdout: str = Field(max_length=32000)
    stderr: str = Field(max_length=32000)
    truncated: bool
    findings: list[ExecutionFindingOut] = Field(max_length=5)


class ReviewItemOut(StrictModel):
    """One disagreed card, as the internal review page sees it.

    It deliberately carries the card's conclusion and location only: the
    student's own work is not copied into the queue (v0.1,
    ``specs/review-queue.schema.json``).
    """

    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    layer: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
    label: str = Field(min_length=1, max_length=40)
    node_id: str = Field(pattern=r"^n[0-9]+$")
    one_line: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
    created_at: str = Field(min_length=1, max_length=40)


class ReviewItemsOut(StrictModel):
    version: Literal["0.1"]
    items: list[ReviewItemOut]


class KnowledgeSourceOut(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    license: str = Field(min_length=1, max_length=80)


KnowledgeKindOut = Literal["concept", "pattern", "method", "error", "source"]
KnowledgeVerificationOut = Literal["formal", "executable", "empirical", "argumentative"]


class KnowledgeHitOut(StrictModel):
    card_id: str = Field(pattern=r"^K_[A-Z0-9_]+$")
    kind: KnowledgeKindOut
    subject: str = Field(min_length=1, max_length=40)
    verifications: list[KnowledgeVerificationOut] = Field(min_length=1, max_length=4)
    title: str = Field(min_length=1, max_length=60)
    excerpt: str = Field(min_length=1, max_length=300)
    source: KnowledgeSourceOut
    score: float = Field(ge=0, le=1)


class KnowledgeSearchOut(StrictModel):
    """Read-only knowledge lookup; ``enabled=false`` hides the panel client-side."""

    version: Literal["0.2"]
    enabled: bool
    query: str = Field(max_length=200)
    hits: list[KnowledgeHitOut] = Field(default_factory=list, max_length=5)


AgentToolOut = Literal[
    "check_structure",
    "search_patterns",
    "search_sources",
    "compare_options",
    "ask_clarifying",
    "run_code",
    "run_tests",
]
AgentStepStatusOut = Literal["ok", "skipped", "failed"]
AgentSuggestionKindOut = Literal["structure", "source", "experiment", "clarify"]
AgentSuggestionSourceOut = Literal["rule", "knowledge", "execution", "system"]
AgentPlannerStatusOut = Literal["off", "used", "fallback"]
AgentPlanningToolOut = Literal["search_patterns", "search_sources", "compare_options"]


class AgentRunRequest(StrictModel):
    """Explicit code submission for one bounded trace.

    The API never extracts code from the problem or the attempt; the caller
    must paste it. ``tests`` is optional and requires ``code``.
    """

    code: str | None = Field(default=None, min_length=1, max_length=20000)
    tests: str | None = Field(default=None, min_length=1, max_length=20000)

    @model_validator(mode="after")
    def require_code(self) -> AgentRunRequest:
        if self.code is None:
            raise ValueError("code is required")
        if self.tests is not None and not self.tests.strip():
            raise ValueError("tests must not be blank")
        return self


class AgentCitationOut(StrictModel):
    card_id: str = Field(pattern=r"^K_[A-Z0-9_]+$")
    title: str = Field(min_length=1, max_length=60)
    source_title: str = Field(min_length=1, max_length=120)
    source_url: str = Field(pattern=r"^https://")
    license: str = Field(min_length=1, max_length=80)


class AgentStepOut(StrictModel):
    index: int = Field(ge=1, le=3)
    tool: AgentToolOut
    status: AgentStepStatusOut
    input_summary: str = Field(min_length=1, max_length=200)
    output_summary: str = Field(min_length=1, max_length=600)
    duration_ms: float = Field(ge=0, le=60000)
    citations: list[AgentCitationOut] = Field(default_factory=list, max_length=3)


class AgentSuggestionOut(StrictModel):
    kind: AgentSuggestionKindOut
    text: str = Field(min_length=1, max_length=300)
    source: AgentSuggestionSourceOut


class AgentLimitsOut(StrictModel):
    max_steps: int = Field(ge=1, le=3)
    steps_used: int = Field(ge=0, le=3)


class AgentReflectionOut(StrictModel):
    """Two lines of coverage review; neither line is a diagnosis."""

    focus: str = Field(min_length=1, max_length=300)
    next: str = Field(min_length=1, max_length=300)
    boundary: str = Field(min_length=1, max_length=200)


class AgentPlannerOut(StrictModel):
    """Which middle-step tool the optional planner picked, never an outcome."""

    status: AgentPlannerStatusOut
    reason: str = Field(min_length=1, max_length=200)
    tool: AgentPlanningToolOut | None = None

    @model_validator(mode="after")
    def tool_matches_status(self) -> AgentPlannerOut:
        if self.status == "used" and self.tool is None:
            raise ValueError("used planner requires a tool")
        if self.status != "used" and self.tool is not None:
            raise ValueError("only a used planner may carry a tool")
        return self


class AgentTraceOut(StrictModel):
    """A bounded tool trace, not a diagnosis and not a chain of thought."""

    version: Literal["0.3"]
    session_id: str = Field(min_length=1, max_length=64)
    mode: Literal["rules", "llm"]
    planner: AgentPlannerOut
    steps: list[AgentStepOut] = Field(default_factory=list, max_length=3)
    suggestions: list[AgentSuggestionOut] = Field(default_factory=list, max_length=3)
    reflection: AgentReflectionOut
    limits: AgentLimitsOut
    notice: str = Field(min_length=1, max_length=300)


class HealthOut(StrictModel):
    status: Literal["ok"] = "ok"
    version: str


# --- process coach (v0.1) ----------------------------------------------------
#
# The coach is process feedback, not a solution. These DTOs deliberately have no
# ``answer``/``solution``/``score``/``rank`` field: the response model itself is
# part of the boundary, not only the service behind it.

CoachFocusOut = Literal["where_wrong", "how_to_start"]
CoachModeOut = Literal["rules", "llm"]
CoachPointKindOut = Literal[
    "missing_evidence",
    "missing_reasoning",
    "missing_constraint",
    "no_attempt",
    "next_step",
    "process_note",
]


class CoachRequest(StrictModel):
    """The only two things a student can ask the coach for."""

    focus: CoachFocusOut


class CoachPointOut(StrictModel):
    """One process observation; ``basis`` names where it came from."""

    kind: CoachPointKindOut
    text: str = Field(min_length=1, max_length=200)
    basis: str = Field(min_length=1, max_length=64)


class CoachOut(StrictModel):
    """Process feedback with its uncertainty made explicit.

    ``not_claimed`` must be non-empty: the coach has no correctness check, no
    answer store and no score, and the client renders that list rather than
    letting the result read like a verdict.
    """

    version: Literal["0.1"]
    mode: CoachModeOut
    focus: CoachFocusOut
    headline: str = Field(min_length=1, max_length=160)
    points: list[CoachPointOut] = Field(min_length=1, max_length=4)
    next_question: str = Field(min_length=1, max_length=200)
    not_claimed: list[str] = Field(min_length=1, max_length=6)
    disclaimer: str = Field(min_length=1, max_length=320)


# Deliberately simple: the API stores only addresses this pattern accepts, and a
# full RFC 5322 parser would add a dependency without making an address reachable.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL_PATTERN.match(cleaned):
        raise ValueError("email is not a valid address")
    return cleaned


class RegisterRequest(StrictModel):
    """Account creation for a self-hosted owner.

    Only the first registration succeeds unless ``SYNAPSE_AUTH_ALLOW_SIGNUP=on``.
    The password is length-checked here and hashed with Argon2id before it
    reaches any store; it is never logged or echoed back.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def password_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class LoginRequest(StrictModel):
    """Credentials for an existing account.

    The password has no real minimum here beyond being non-empty: rejecting a
    short password at login would tell a caller something about the account.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class AuthUserOut(StrictModel):
    """The public account view; no digest, no session token."""

    id: str = Field(min_length=1, max_length=40)
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=120)
    created_at: datetime


class LogoutOut(StrictModel):
    status: Literal["ok"] = "ok"


# ---------------------------------------------------------------------------
# Per-user model settings (BYOK). ``api_key`` is write-only: it appears in a
# request body, never in a response, and field-level ``repr=False`` keeps it out
# of accidental object dumps. No example values are declared on purpose.
# ---------------------------------------------------------------------------


class ModelCredentialIn(StrictModel):
    """A full save from the settings form; the key is required on save."""

    provider: str = Field(min_length=1, max_length=32)
    base_url: str = Field(default="", max_length=300)
    model: str = Field(default="", max_length=120)
    api_key: str = Field(min_length=8, max_length=4096, repr=False)


class ModelCredentialTestIn(StrictModel):
    """Test a candidate credential; omitted fields fall back to the saved row."""

    provider: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, min_length=8, max_length=4096, repr=False)


class ModelCredentialOut(StrictModel):
    """The masked credential view; the key itself is never part of it."""

    configured: bool
    provider: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    key_last4: str | None = Field(default=None, max_length=4)
    last_verified_at: datetime | None = None
    encryption_ready: bool
    warning: str | None = None


class ModelTestOut(StrictModel):
    """Result of one provider probe; ``message`` never contains the key."""

    ok: bool
    latency_ms: int = Field(ge=0)
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
