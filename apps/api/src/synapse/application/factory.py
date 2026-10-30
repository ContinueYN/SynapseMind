"""Session factory.

Pattern: Factory. It assembles the aggregate from a problem, an attempt and an
alignment strategy. The service never constructs a session by hand.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application.commands import StartSessionCommand
from synapse.application.errors import ProblemNotSupported, UnsupportedMode
from synapse.application.ports import (
    Clock,
    IdGenerator,
    ProblemRepository,
)
from synapse.application.problem_resolver import ProblemResolver
from synapse.application.subject import SubjectRegistry, VerifiabilityLevel
from synapse.domain.diagnosis.hypotheses import (
    EvidenceWeights,
    HypothesisSet,
    layer_for_node_type,
)
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.evidence.models import Evidence
from synapse.domain.problem.alignment import StepAligner
from synapse.domain.problem.models import AlignmentResult, Problem, SolutionGraph, StudentAttempt

# How the seed's hand-written steps support each hypothesis. A generated graph
# has no such table: its node ids carry no reviewed meaning, so it contributes
# only the type-derived prior (M2.5 S5 ②) and the probes do the rest.
_ALIGNMENT_SUPPORT = {
    "n1": ("H_L1",),
    "n2": ("H_L1",),
    "n3": ("H_L2",),
    "n5": ("H_L4",),
    "n6": ("H_L2",),
}

__all__ = ["ProblemNotSupported", "SessionFactory", "UnsupportedMode"]


class SessionFactory:
    def __init__(
        self,
        problems: ProblemRepository,
        aligner: StepAligner,
        ids: IdGenerator,
        clock: Clock,
        *,
        subjects: SubjectRegistry | None = None,
        resolver: ProblemResolver | None = None,
    ) -> None:
        self._problems = problems
        self._aligner = aligner
        self._ids = ids
        self._clock = clock
        self._subjects = subjects
        # Without an explicit resolver the factory still serves the annotated
        # catalog and refuses everything else — generation needs a store to
        # keep the new problem and a plugin that can build graphs.
        self._resolver = resolver or ProblemResolver(problems, subjects)

    def level_for(self, subject: str) -> VerifiabilityLevel:
        """The subject's promise tier (M2.5 S7); used by the service gate.

        Without a registry this is the M1 rule baseline, which is STRONG: the
        annotated catalog is the one subject the product can actually verify.
        An unknown subject must never reach here — the resolver refuses it
        first — but if it does, STRONG keeps the pre-S7 behaviour instead of
        silently downgrading a working path.
        """

        if self._subjects is None:
            return VerifiabilityLevel.STRONG
        plugin = self._subjects.for_subject(subject)
        if plugin is None:
            return VerifiabilityLevel.STRONG
        return plugin.level

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

    def _labels_for(self, subject: str) -> Mapping[str, str] | None:
        """Subject-specific names for the shared hypothesis ids (S6).

        The scoring vocabulary stays H_L1/H_L2/H_L4; only the card wording is
        replaced. A plugin that does not supply labels keeps the math ones, so
        the annotated baseline is unchanged.
        """

        if self._subjects is None:
            return None
        plugin = self._subjects.for_subject(subject)
        if plugin is None:
            return None
        labels = getattr(plugin, "hypothesis_labels", None)
        if isinstance(labels, Mapping):
            return {str(key): str(value) for key, value in labels.items()}
        return None

    def _aligner_for(self, problem: Problem) -> StepAligner:
        """Ask the subject plugin which matcher this problem needs (S8).

        ``self._aligner`` is only the no-registry fallback: with a registry the
        plugin is authoritative, so a NONE-tier subject can use clause-level
        matching while math/physics keep the two-state aligner. No subject name
        is compared here.
        """

        if self._subjects is None:
            return self._aligner
        plugin = self._subjects.for_subject(problem.subject)
        if plugin is None:
            return self._aligner
        return plugin.aligner_for(problem)

    def create(self, command: StartSessionCommand) -> DialogueSession:
        if command.mode != "learning":
            raise UnsupportedMode(command.mode)

        problem = self._resolver.resolve(command.problem_text, command.subject)

        attempt = StudentAttempt(
            answer=command.answer,
            work=command.work,
            stuck_at=command.stuck_at,
            confidence=command.confidence,
            self_report=command.self_report,
        )
        alignment = self._aligner_for(problem).align(problem, attempt)
        focus = self._focus_for(problem, alignment)
        session = DialogueSession(
            session_id=self._ids.new_session_id(),
            problem_id=problem.id,
            state=DialogueState.INGEST,
            alignment=alignment,
            hypotheses=HypothesisSet.from_alignment(
                alignment,
                evidence=self._evidence_for(problem.subject, problem.graph),
                focus=focus,
                labels=self._labels_for(problem.subject),
            ),
            max_turns=6,
            created_at=self._clock.now(),
            mode=command.mode,
        )
        # Explicit pipeline: no shortcut into PROBE without the table.
        session.advance(DialogueEvent.INGESTED)
        session.advance(DialogueEvent.PARSED)
        session.advance(DialogueEvent.ALIGNED)

        supports = (
            () if not problem.annotated else _ALIGNMENT_SUPPORT.get(alignment.first_divergence, ())
        )
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

    @staticmethod
    def _focus_for(problem: Problem, alignment: AlignmentResult) -> str | None:
        """Layer prior from the *type* of the first missing node (S5 ②).

        Only for generated problems: the annotated catalog keeps its
        hand-written node-id profile, which the golden baseline depends on.
        """

        if problem.annotated or alignment.first_divergence == "none":
            return None
        for node in problem.graph.nodes:
            if node.id == alignment.first_divergence:
                return layer_for_node_type(node.type)
        return None
