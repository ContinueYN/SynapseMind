"""Dialogue aggregate and turn history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.diagnosis.work import WorkFinding
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.dialogue.table import next_state
from synapse.domain.evidence.models import EvidenceChain
from synapse.domain.problem.models import AlignmentResult


@dataclass(frozen=True, slots=True)
class TurnRecord:
    turn: int
    probe_id: str
    question: str
    answer: str
    option_id: str | None
    action: str
    is_unknown: bool = False


@dataclass
class DialogueSession:
    session_id: str
    problem_id: str
    state: DialogueState
    alignment: AlignmentResult
    hypotheses: HypothesisSet
    max_turns: int
    created_at: datetime
    mode: str = "learning"
    turn: int = 0
    asked_probe_ids: list[str] = field(default_factory=list)
    history: list[TurnRecord] = field(default_factory=list)
    evidence: EvidenceChain = field(default_factory=EvidenceChain)
    diagnosis: DiagnosisCard | None = None
    # Filled at start, read when the card is built several turns later. Empty
    # unless the equality-check flag is on (see application/work_check.py).
    work_findings: tuple[WorkFinding, ...] = ()
    # Blank-attempt scaffolding: how many example steps have been shown (0
    # means the session never entered SCAFFOLD) and the work accumulated across
    # scaffold submissions. Persisted so a reload can continue the same ladder.
    scaffold_level: int = 0
    scaffold_work: str = ""
    # The answer submitted with the problem, verbatim. The generic intake derives
    # "what the attempt mentions / does not mention" from it on every read, so it
    # has to survive a reload; probe answers were already stored, so this does
    # not widen what the snapshot holds in kind, only what the reference-free
    # path keeps. Empty for sessions created before this field existed.
    initial_answer: str = ""
    # A reference-free session may ask at most one clarifying question. Once the
    # student appends an answer, the derived intake stops asking; the flag is
    # stored so a reload cannot re-open the same question or accept a second
    # answer. False for sessions created before this field existed.
    clarifier_answered: bool = False
    # A clarification such as "这是决策问题" may name a registered domain. The
    # override is stored on the session (the submitted problem stays untouched)
    # so the intake and the displayed domain keep the student's label after a
    # reload. ``None`` means the detector's original label still applies.
    domain_override: str | None = None
    # How many structural follow-up questions the intake has accepted. Capped by
    # ``application/intake.MAX_INTAKE_PROBES``; the answer text itself lives in
    # ``initial_answer`` and nothing here is a diagnosis.
    intake_probe_count: int = 0
    # Optimistic-concurrency token owned by the repository adapter. 0 means
    # "not stored yet"; each successful save increments it. It is internal
    # storage metadata and is never exposed by the HTTP API.
    revision: int = 0

    def advance(self, event: DialogueEvent) -> DialogueState:
        self.state = next_state(self.state, event)
        return self.state

    def record_turn(self, record: TurnRecord) -> None:
        self.history.append(record)
        self.turn = record.turn

    @property
    def current_probe_id(self) -> str | None:
        return self.asked_probe_ids[-1] if self.asked_probe_ids else None

    @property
    def is_terminal(self) -> bool:
        return self.state in {DialogueState.STOP, DialogueState.CLOSED}
