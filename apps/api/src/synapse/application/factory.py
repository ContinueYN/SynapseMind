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
from synapse.application.subject import SubjectRegistry
from synapse.domain.diagnosis.hypotheses import EvidenceWeights, HypothesisSet
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.evidence.models import Evidence
from synapse.domain.problem.alignment import StepAligner
from synapse.domain.problem.models import SolutionGraph, StudentAttempt

_ALIGNMENT_SUPPORT = {
    "n1": ("H_L1",),
    "n2": ("H_L1",),
    "n3": ("H_L2",),
    "n5": ("H_L4",),
    "n6": ("H_L2",),
}


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
        *,
        subjects: SubjectRegistry | None = None,
    ) -> None:
        self._problems = problems
        self._aligner = aligner
        self._ids = ids
        self._clock = clock
        self._subjects = subjects

    def _evidence_for(self, subject: str, graph: SolutionGraph) -> EvidenceWeights | None:
        """Ask the subject plugin for its evidence model; ``None`` = M1 default.

        An empty mapping is different from ``None``: it means the plugin says
        "no probe in this graph carries evidence", so a generated graph cannot
        silently reuse the seed problem's weights.
        """
        if self._subjects is None:
            return None
        plugin = self._subjects.for_subject(subject)
        if plugin is None:
            return None
        return plugin.evidence_model(graph).weights

    def create(self, command: StartSessionCommand) -> DialogueSession:
        if command.mode != "learning":
            raise UnsupportedMode(command.mode)

        problem = self._problems.find_for(command.problem_text)
        if problem is None:
            raise ProblemNotSupported(
                "could not identify this problem; only the sample problem "
                "(function and derivative) is annotated"
            )
        if command.subject is not None and command.subject != problem.subject:
            # A declared subject we cannot serve is an explicit boundary, not a
            # silently ignored field (M2.5 S1 widened the enum; S6 adds physics).
            raise ProblemNotSupported(f"subject {command.subject!r} has no annotated problem yet")

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
            hypotheses=HypothesisSet.from_alignment(
                alignment,
                evidence=self._evidence_for(problem.subject, problem.graph),
            ),
            max_turns=6,
            created_at=self._clock.now(),
            mode=command.mode,
        )
        # Explicit pipeline: no shortcut into PROBE without the table.
        session.advance(DialogueEvent.INGESTED)
        session.advance(DialogueEvent.PARSED)
        session.advance(DialogueEvent.ALIGNED)

        supports = _ALIGNMENT_SUPPORT.get(alignment.first_divergence, ())
        for index, claim in enumerate(alignment.evidence):
            session.evidence.add(
                Evidence(
                    id=f"alignment:{index}",
                    source="alignment",
                    claim=claim,
                    supports=supports,
                )
            )
        return session
