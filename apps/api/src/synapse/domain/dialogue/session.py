"""Dialogue aggregate and turn history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.diagnosis.models import DiagnosisCard
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
