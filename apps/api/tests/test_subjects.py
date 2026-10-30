"""M2.5 S2: the math plugin wraps the seed content without changing behaviour.

Acceptance from chapter 13 §13.7: "数学插件包装现有种子题，行为不变".
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.application.commands import StartSessionCommand
from synapse.application.factory import SessionFactory
from synapse.application.subject import (
    EvidenceModel,
    StudentStep,
    SubjectRegistry,
    VerifiabilityLevel,
)
from synapse.domain.diagnosis.hypotheses import HYPOTHESES
from synapse.domain.problem.alignment import RuleBasedAligner
from synapse.domain.problem.models import AlignmentResult, Problem, StudentAttempt
from synapse.infrastructure.in_memory import InMemoryProblemRepository
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.subjects.math import MathPlugin
from synapse.infrastructure.system import SystemClock, UuidSessionIdGenerator

CATALOG = {SAMPLE_PROBLEM.id: SAMPLE_PROBLEM}
PLUGIN = MathPlugin(CATALOG)


def test_math_is_a_strong_subject() -> None:
    assert PLUGIN.subject == "math"
    assert PLUGIN.level is VerifiabilityLevel.STRONG


def test_identify_recognises_the_seed_text() -> None:
    ref = PLUGIN.identify(SAMPLE_PROBLEM.text)
    assert ref is not None
    assert (ref.problem_id, ref.subject) == (SAMPLE_PROBLEM.id, "math")


def test_identify_rejects_what_it_cannot_serve() -> None:
    assert PLUGIN.identify("") is None
    assert PLUGIN.identify("   ") is None
    assert PLUGIN.identify("阅读下面的文字，完成后面的题目。") is None
    assert PLUGIN.identify("斜面上一质量为 m 的物块，求加速度。") is None
    # Same topic, different problem: the seed graph must not be reused for it.
    assert PLUGIN.identify("已知函数 f(x)=ln x - a x，求 f(x) 的单调区间。") is None


def test_a_different_math_problem_is_refused_end_to_end(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "已知函数 f(x)=ln x - a x，求 f(x) 的单调区间。"},
            "attempt": {"answer": "a≥1/e"},
            "mode": "learning",
        },
    )

    assert response.status_code == 422
    assert "没有标注解法图" in response.json()["detail"]


def test_graph_probes_and_evidence_come_from_the_seed() -> None:
    graph = PLUGIN.build_graph(SAMPLE_PROBLEM)
    assert graph is SAMPLE_PROBLEM.graph

    node = graph.node("n3")
    assert PLUGIN.probes_for(node) == node.probes
    assert len(node.probes) == 2

    model = PLUGIN.evidence_model(graph)
    assert set(model.probe_ids) == {
        "p_a0_derivative",
        "p_boundary_check",
        "p_max_value",
        "p_union",
    }
    assert model.for_probe("p_a0_derivative")["A"]["H_L2"] == 0.30
    assert model.for_probe("p_union")["B"]["H_L2"] > 0
    assert model.for_probe("p_union")["C"]["H_L2"] < 0


def test_every_seed_probe_option_has_evidence() -> None:
    """No probe may waste a turn: every option maps to at least one hypothesis."""
    model = PLUGIN.evidence_model(SAMPLE_PROBLEM.graph)

    for probe in SAMPLE_PROBLEM.graph.probes():
        table = model.for_probe(probe.id)
        for index in range(len(probe.options)):
            option = chr(ord("A") + index)
            assert option in table, f"{probe.id} option {option} has no weights"
            assert set(table[option]) <= set(HYPOTHESES), probe.id
            assert table[option], f"{probe.id} option {option} is empty"


def test_verify_admits_it_has_no_verifier_yet() -> None:
    verdict = PLUGIN.verify(StudentStep(node_id="n3", text="a>0 时成立"))
    assert verdict.status == "unknown"
    assert verdict.detail


def test_registry_routes_by_subject() -> None:
    registry = SubjectRegistry((PLUGIN,))
    assert registry.for_subject("math") is PLUGIN
    assert registry.for_subject("physics") is None
    hit = registry.identify(SAMPLE_PROBLEM.text)
    assert hit is not None
    assert hit[0] is PLUGIN and hit[1].problem_id == SAMPLE_PROBLEM.id
    assert registry.identify("今天天气不错") is None


def test_repository_delegates_identification_to_the_plugin() -> None:
    repo = InMemoryProblemRepository()
    assert repo.find_for(SAMPLE_PROBLEM.text) == SAMPLE_PROBLEM
    assert repo.find_for("一道物理题：光滑斜面") is None
    assert repo.plugins.for_subject("math") is not None


class _FlipEvidencePlugin:
    """A plugin whose evidence model deliberately disagrees with M1."""

    subject = "math"
    level = VerifiabilityLevel.STRONG

    def aligner_for(self, problem: object) -> RuleBasedAligner:
        del problem
        return RuleBasedAligner()

    def evidence_model(self, graph: object) -> EvidenceModel:
        del graph
        return EvidenceModel(weights={"p_a0_derivative": {"A": {"H_L1": 1.2}}})


def test_factory_uses_the_plugins_evidence_model() -> None:
    command = StartSessionCommand(
        problem_text=SAMPLE_PROBLEM.text,
        answer="a≥1/e",
        work="定义域 x>0。f'(x)=1/x-a，a>0 时最大值为 -ln a-1。",
    )
    factory = SessionFactory(
        problems=InMemoryProblemRepository(),
        aligner=RuleBasedAligner(),
        ids=UuidSessionIdGenerator(),
        clock=SystemClock(),
        subjects=SubjectRegistry((_FlipEvidencePlugin(),)),  # type: ignore[arg-type]
    )

    session = factory.create(command)

    assert session.hypotheses.evidence == {"p_a0_derivative": {"A": {"H_L1": 1.2}}}


class _SpyAligner:
    """Records that the factory asked the plugin, then returns no gap."""

    def __init__(self) -> None:
        self.calls = 0

    def align(self, problem: Problem, attempt: StudentAttempt) -> AlignmentResult:
        del attempt
        self.calls += 1
        return AlignmentResult(
            first_divergence="none",
            matched_node_ids=tuple(node.id for node in problem.graph.nodes),
            missing_node_ids=(),
            evidence=("spy aligner",),
            excluded=(),
        )


def test_factory_asks_the_subject_plugin_for_its_aligner() -> None:
    """S8: alignment strategy is a plugin capability, not a factory default."""

    spy = _SpyAligner()
    plugin = MathPlugin(CATALOG, annotated_aligner=spy)
    factory = SessionFactory(
        problems=InMemoryProblemRepository(),
        aligner=RuleBasedAligner(),
        ids=UuidSessionIdGenerator(),
        clock=SystemClock(),
        subjects=SubjectRegistry((plugin,)),
    )

    session = factory.create(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work="定义域 x>0。",
        )
    )

    assert spy.calls == 1
    assert session.alignment.first_divergence == "none"


def test_container_exposes_the_registry() -> None:
    container = build_container()
    assert container.subjects.for_subject("math") is not None


def test_physics_is_accepted_by_the_dto_but_still_422(
    client: TestClient,
    sample_payload: dict[str, object],
) -> None:
    """S1 widened the enum; a subject we cannot serve is still an explicit 422."""
    payload = copy.deepcopy(sample_payload)
    problem = payload["problem"]
    assert isinstance(problem, dict)
    problem["subject"] = "physics"

    response = client.post("/api/v1/sessions", json=payload)

    assert response.status_code == 422
    assert "no annotated problem" in response.json()["detail"]
