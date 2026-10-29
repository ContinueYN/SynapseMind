"""Math plugin: wraps the hand-written seed graph as the first STRONG subject.

S3 scope: identification is no longer keyword matching. A submission is only
served when it actually contains the annotated problem; everything else is
refused so the wrong graph is never used to explain a student's work.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application.subject import (
    EvidenceModel,
    ProblemIdentifier,
    ProblemRef,
    StudentStep,
    Verdict,
    VerifiabilityLevel,
)
from synapse.domain.diagnosis.hypotheses import EVIDENCE
from synapse.domain.problem.identification import TextProblemIdentifier
from synapse.domain.problem.models import Probe, Problem, SolutionGraph, SolutionNode

SUBJECT = "math"


class MathPlugin:
    subject = SUBJECT
    level = VerifiabilityLevel.STRONG

    def __init__(
        self,
        catalog: Mapping[str, Problem],
        *,
        identifier: ProblemIdentifier | None = None,
    ) -> None:
        self._catalog = dict(catalog)
        self._identifier = identifier or TextProblemIdentifier(self._catalog)

    def identify(self, text: str) -> ProblemRef | None:
        problem_id = self._identifier.identify(text)
        problem = self._catalog.get(problem_id) if problem_id is not None else None
        if problem is None or problem.subject != self.subject:
            return None
        return ProblemRef(problem_id=problem.id, subject=self.subject)

    def build_graph(self, problem: Problem) -> SolutionGraph:
        # The seed graph is hand-written; S4 will generate it and validate
        # against specs/solution-graph.schema.json before returning.
        return problem.graph

    def probes_for(self, node: SolutionNode) -> tuple[Probe, ...]:
        return node.probes

    def evidence_model(self, graph: SolutionGraph) -> EvidenceModel:
        probe_ids = {probe.id for probe in graph.probes()}
        return EvidenceModel(
            weights={
                probe_id: dict(options)
                for probe_id, options in EVIDENCE.items()
                if probe_id in probe_ids
            }
        )

    def verify(self, step: StudentStep) -> Verdict:
        # A STRONG subject without a verifier must say so, never pretend.
        del step
        return Verdict(
            status="unknown",
            detail="数学验证器在 M2.5 S5 接入（SymPy 子进程）；在此之前不作断言",
        )
