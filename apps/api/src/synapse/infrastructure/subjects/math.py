"""Math plugin: wraps the hand-written seed graph as the first STRONG subject.

S2 scope: behaviour must not change. Identification still uses the same
keywords as M1, the graph is the same object, and evidence weights are the
same domain constant — only the seam is new.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application.subject import (
    EvidenceModel,
    ProblemRef,
    StudentStep,
    Verdict,
    VerifiabilityLevel,
)
from synapse.domain.diagnosis.hypotheses import EVIDENCE
from synapse.domain.problem.models import Probe, Problem, SolutionGraph, SolutionNode

SUBJECT = "math"


class MathPlugin:
    subject = SUBJECT
    level = VerifiabilityLevel.STRONG

    def __init__(self, catalog: Mapping[str, Problem]) -> None:
        self._catalog = dict(catalog)

    def identify(self, text: str) -> ProblemRef | None:
        """Keyword identification, identical to the M1 rule.

        S3 replaces this with a proper identifier; the port already hides the
        mechanism, so the swap will not touch the repository.
        """
        haystack = text.strip().lower()
        if not haystack:
            return None
        for problem in self._catalog.values():
            if any(keyword.lower() in haystack for keyword in problem.keywords):
                return ProblemRef(problem_id=problem.id, subject=self.subject)
        return None

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
