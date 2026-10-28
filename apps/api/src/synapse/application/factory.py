"""Session factory.

Pattern: Factory. It assembles the aggregate from a problem, an attempt and an
alignment strategy. The service never constructs a session by hand.
"""

from __future__ import annotations

from synapse.application.commands import StartSessionCommand
from synapse.application.ports import (
    Clock,
    IdGenerator,
    ProblemRepository,
)
from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.problem.alignment import StepAligner
from synapse.domain.problem.models import StudentAttempt


class ProblemNotSupported(ValueError):
    """The M1 seed set has no matching problem."""


class UnsupportedMode(ValueError):
    """Only learning mode is available in the walking skeleton."""


class SessionFactory:
    def __init__(
        self,
        problems: ProblemRepository,
        aligner: StepAligner,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._problems = problems
        self._aligner = aligner
        self._ids = ids
        self._clock = clock

    def create(self, command: StartSessionCommand) -> DialogueSession:
        if command.mode != "learning":
            raise UnsupportedMode(command.mode)

        problem = self._problems.find_for(command.problem_text)
        if problem is None:
            raise ProblemNotSupported("M1 only ships the function-derivative seed")

        attempt = StudentAttempt(
            answer=command.answer,
            work=command.work,
            stuck_at=command.stuck_at,
            confidence=command.confidence,
            self_report=command.self_report,
        )
        alignment = self._aligner.align(problem, attempt)
        session = DialogueSession(
            session_id=self._ids.new_session_id(),
            problem_id=problem.id,
            state=DialogueState.INGEST,
            alignment=alignment,
            hypotheses=HypothesisSet.from_alignment(alignment),
            max_turns=6,
            created_at=self._clock.now(),
            mode=command.mode,
        )
        # Explicit pipeline: no shortcut into PROBE without the table.
        session.advance(DialogueEvent.INGESTED)
        session.advance(DialogueEvent.PARSED)
        session.advance(DialogueEvent.ALIGNED)
        return session
