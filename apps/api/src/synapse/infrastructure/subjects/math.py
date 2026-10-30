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
from synapse.application.work_check import EqualityChecker
from synapse.domain.diagnosis.hypotheses import EVIDENCE, HYPOTHESES
from synapse.domain.problem.alignment import (
    CompositeAligner,
    RuleBasedAligner,
    StepAligner,
    TypeCueAligner,
)
from synapse.domain.problem.identification import TextProblemIdentifier
from synapse.domain.problem.models import (
    Probe,
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)

SUBJECT = "math"

# Same three hypothesis ids, in the vocabulary the seed's cards already use.
MATH_HYPOTHESIS_LABELS: Mapping[str, str] = {
    hypothesis_id: hypothesis.label for hypothesis_id, hypothesis in HYPOTHESES.items()
}

# The seed's L1 label names its own topic ("恒成立与最值"). A generated graph can
# be any topic, so reusing it verbatim tells a 数列/立体几何 student they have a
# 恒成立 problem — observed on every generated card in the 100-problem run.
GENERATED_HYPOTHESIS_LABELS: Mapping[str, str] = {
    **MATH_HYPOTHESIS_LABELS,
    "H_L1": "概念不清：没抓住这一步的关键条件",
}


class MathPlugin:
    subject = SUBJECT
    level = VerifiabilityLevel.STRONG
    hypothesis_labels = MATH_HYPOTHESIS_LABELS

    def labels_for(self, problem: Problem) -> Mapping[str, str]:
        """Card wording: the seed's topic name only on the seed's own problem.

        ``hypothesis_labels`` stays the annotated vocabulary so the seed card is
        byte-identical; a generated graph gets the topic-neutral L1 wording.
        """

        if problem.annotated:
            return MATH_HYPOTHESIS_LABELS
        return GENERATED_HYPOTHESIS_LABELS

    def __init__(
        self,
        catalog: Mapping[str, Problem],
        *,
        identifier: ProblemIdentifier | None = None,
        generator: GraphGenerator | None = None,
        annotated_aligner: StepAligner | None = None,
        generated_aligner: StepAligner | None = None,
        equality_checker: EqualityChecker | None = None,
    ) -> None:
        self._catalog = dict(catalog)
        self._identifier = identifier or TextProblemIdentifier(self._catalog)
        self._generator = generator
        # Optional and off by default: without the checker ``verify()`` says
        # "not checked" instead of guessing. The composition root installs it
        # only when ``SYNAPSE_EQUALITY_CHECK`` is on.
        self._equality_checker = equality_checker
        # The plugin owns the dispatch (S8). An annotated problem has a
        # hand-written reference and the rule aligner tuned against it; a
        # generated one only has node types and existence cues.
        self._aligner = CompositeAligner(
            annotated=annotated_aligner or RuleBasedAligner(),
            generated=generated_aligner or TypeCueAligner(),
        )

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

    def aligner_for(self, problem: Problem) -> StepAligner:
        """Annotated → hand-tuned rules; generated → type-cue existence (S8)."""

        del problem  # the composite reads ``problem.annotated`` itself
        return self._aligner

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
        """Check the equals signs the student wrote in this step (S5 ⑥).

        The checker is an optional falsifier: it can prove ``A = B`` false with
        a concrete counterexample, but finding nothing does not prove the step
        correct. So the honest outcomes are ``fail`` (with the counterexample)
        and ``unknown`` (disabled, unreadable, or no broken equality found).
        ``pass`` is never returned here; that would overclaim.
        """

        if self._equality_checker is None:
            return Verdict(
                status="unknown",
                detail="等式链校验未启用（SYNAPSE_EQUALITY_CHECK=off）；没有对这一步作断言。",
            )
        text = step.text.strip()
        if not text:
            return Verdict(
                status="unknown",
                detail="这一步没有可读的式子，未作断言。",
            )
        findings = self._equality_checker.findings(text)
        if not findings:
            return Verdict(
                status="unknown",
                detail="没有找到可机器证明的等号错误；这不等于这一步正确（读不懂的式子会被跳过）。",
            )
        parts: list[str] = []
        for finding in findings[:3]:
            formula = f"{finding.left} = {finding.right}"
            summary = finding.summary or finding.counterexample or finding.detail
            parts.append(f"「{formula}」{summary}" if summary else f"「{formula}」")
        detail = "这个等号不成立：" + "；".join(parts)
        if len(detail) > 900:
            detail = detail[:899] + "…"
        return Verdict(status="fail", detail=detail)
