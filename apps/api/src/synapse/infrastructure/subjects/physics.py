"""Physics plugin: the second subject, at the PARTIAL verifiability tier.

S6 is an architecture test, not a physics tutor: the dialogue kernel, state
machine, aligner, diagnosis gate and card builder must run unchanged. The
plugin supplies physics content and physics wording; it does not decide any
state transition.

Why PARTIAL:

* a solution graph can be generated and probed exactly like math;
* a *student's step* can be checked by units/dimensional analysis or numeric
  substitution, but ``StudentStep`` currently carries free text only, so
  ``verify()`` returns ``unknown`` instead of pretending;
* the math parameter-range claim verifier is deliberately not used here — a
  physics answer carries units, and running the math verifier on it would
  certify something it cannot see.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application.graph import GraphBuildFailed, GraphGenerator
from synapse.application.subject import (
    EvidenceModel,
    ProblemRef,
    StudentStep,
    Verdict,
    VerifiabilityLevel,
)
from synapse.domain.problem.identification import TextProblemIdentifier
from synapse.domain.problem.models import (
    Probe,
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)

SUBJECT = "physics"

# The hypothesis ids are shared with math (the scoring and state machine are
# subject-agnostic); only the labels are physics vocabulary. A physics card
# must not say "恒成立与最值".
PHYSICS_HYPOTHESIS_LABELS: Mapping[str, str] = {
    "H_L1": "概念 / 公式条件不清",
    "H_L2": "物理模型 / 条件转译",
    "H_L4": "执行 / 计算错误",
}


class PhysicsPlugin:
    subject = SUBJECT
    level = VerifiabilityLevel.PARTIAL
    hypothesis_labels = PHYSICS_HYPOTHESIS_LABELS

    def __init__(
        self,
        catalog: Mapping[str, Problem] | None = None,
        *,
        generator: GraphGenerator | None = None,
    ) -> None:
        self._catalog = dict(catalog or {})
        self._identifier = TextProblemIdentifier(self._catalog)
        self._generator = generator

    def identify(self, text: str) -> ProblemRef | None:
        """Only serve an annotated physics problem; otherwise let the resolver
        generate one from the declared subject."""

        problem_id = self._identifier.identify(text)
        problem = self._catalog.get(problem_id) if problem_id is not None else None
        if problem is None or problem.subject != self.subject:
            return None
        return ProblemRef(problem_id=problem.id, subject=self.subject)

    def build_graph(self, problem: Problem | ProblemDraft) -> SolutionGraph:
        if isinstance(problem, Problem):
            return problem.graph
        if self._generator is None:
            raise GraphBuildFailed(
                "disabled",
                detail="物理插件没有接建图器；生成物理图需要 LLMGraphGenerator",
            )
        return self._generator.generate(problem).graph

    def probes_for(self, node: SolutionNode) -> tuple[Probe, ...]:
        return node.probes

    def evidence_model(self, graph: SolutionGraph) -> EvidenceModel:
        """Read the generated graph's weights; never borrow math's seed table."""

        probes = graph.probes()
        if probes and all(probe.evidence for probe in probes):
            return EvidenceModel(
                weights={
                    probe.id: {option: dict(weights) for option, weights in probe.evidence.items()}
                    for probe in probes
                }
            )
        return EvidenceModel(weights={})

    def verify(self, step: StudentStep) -> Verdict:
        del step
        return Verdict(
            status="unknown",
            detail=(
                "物理按 PARTIAL 档接入：量纲/单位与数值回代需要结构化步骤，"
                "当前 StudentStep 只有文本，暂不判对错"
            ),
        )
