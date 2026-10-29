"""Math plugin: wraps the hand-written seed graph as the first STRONG subject.

S3 scope: identification is no longer keyword matching. A submission is only
served when it actually contains the annotated problem; everything else is
refused so the wrong graph is never used to explain a student's work.

S4 scope: ``build_graph`` also accepts a draft with no annotated graph and
delegates to the LLM generator. The generator is optional so tests and the
``off`` baseline keep the M1 behaviour of wrapping the seed graph.

S5 scope: a generated graph carries its own per-option log-odds weights, so
``evidence_model`` reads them from the graph. The hand-written ``EVIDENCE``
table is only used for the annotated catalog graph; an unknown graph gets an
empty model rather than inheriting the seed problem's weights.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application.graph import GraphBuildFailed, GraphGenerator
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
from synapse.domain.problem.models import (
    Probe,
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)

SUBJECT = "math"


class MathPlugin:
    subject = SUBJECT
    level = VerifiabilityLevel.STRONG

    def __init__(
        self,
        catalog: Mapping[str, Problem],
        *,
        identifier: ProblemIdentifier | None = None,
        generator: GraphGenerator | None = None,
    ) -> None:
        self._catalog = dict(catalog)
        self._identifier = identifier or TextProblemIdentifier(self._catalog)
        self._generator = generator

    def identify(self, text: str) -> ProblemRef | None:
        problem_id = self._identifier.identify(text)
        problem = self._catalog.get(problem_id) if problem_id is not None else None
        if problem is None or problem.subject != self.subject:
            return None
        return ProblemRef(problem_id=problem.id, subject=self.subject)

    def build_graph(self, problem: Problem | ProblemDraft) -> SolutionGraph:
        if isinstance(problem, Problem):
            # Annotated graphs (the seed today, cached generated graphs later)
            # are returned as-is; regeneration is an explicit cache decision.
            return problem.graph
        if self._generator is None:
            raise GraphBuildFailed(
                "disabled",
                detail="当前插件没有接建图器；任意题建图需要 LLMGraphGenerator",
            )
        # S5 wires the generated graph into ALIGN/PROBE; until then the draft
        # path is used by the S4 evaluation harness.
        return self._generator.generate(problem).graph

    def probes_for(self, node: SolutionNode) -> tuple[Probe, ...]:
        return node.probes

    def evidence_model(self, graph: SolutionGraph) -> EvidenceModel:
        """Generated graphs carry their own weights (M2.5 S5).

        Three cases, in order:

        1. every probe has per-option weights -> use them;
        2. the annotated catalog graph (the seed) -> use the hand-written table;
        3. anything else -> empty. A generated graph must never inherit the
           seed problem's weights just because its probe ids look familiar.
        """
        probes = graph.probes()
        if probes and all(probe.evidence for probe in probes):
            return EvidenceModel(
                weights={
                    probe.id: {option: dict(weights) for option, weights in probe.evidence.items()}
                    for probe in probes
                }
            )
        if graph.problem_id in self._catalog:
            probe_ids = {probe.id for probe in probes}
            return EvidenceModel(
                weights={
                    probe_id: dict(options)
                    for probe_id, options in EVIDENCE.items()
                    if probe_id in probe_ids
                }
            )
        return EvidenceModel(weights={})

    def verify(self, step: StudentStep) -> Verdict:
        # A STRONG subject without a step verifier must say so, never pretend.
        # S5's verifier checks the graph's *answer claim*
        # (``infrastructure/verification``); checking a student's free-text
        # step is a different job and has no implementation yet.
        del step
        return Verdict(
            status="unknown",
            detail="学生步骤验证尚未实现；S5 只验证解法图里 claim 声明的答案区间，不对步骤作断言",
        )
