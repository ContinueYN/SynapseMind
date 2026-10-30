"""M2.5 S6: physics is the second subject, at the PARTIAL tier.

The point of this file is architectural: the dialogue state machine, the
aligner, the diagnosis gate and the card builder are not physics-aware. The
plugin supplies a graph, evidence and labels; everything else is the same code
path the math subject uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.commands import StartSessionCommand
from synapse.application.graph import GraphBuildFailed, GraphBuildResult
from synapse.application.subject import StudentStep, SubjectRegistry, VerifiabilityLevel
from synapse.domain.diagnosis.hypotheses import HYPOTHESES, HypothesisSet
from synapse.domain.problem.alignment import AlignmentResult
from synapse.domain.problem.models import (
    Probe,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.subjects.physics import PhysicsPlugin

PHYSICS_TEXT = (
    "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，"
    "动摩擦因数 0.2，求物块的加速度。"
)

WORK = "先读题，标出已知量。"


class _PhysicsGenerator:
    """A tiny but complete physics graph; counts calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        self.calls.append(draft.id)
        graph = SolutionGraph(
            problem_id=draft.id,
            version="v1",
            stem=draft.text,
            nodes=(
                SolutionNode(
                    id="n1",
                    type="READ",
                    text="读题，标出质量、拉力、角度与动摩擦因数。",
                ),
                SolutionNode(
                    id="n2",
                    type="CONDITION",
                    text="确定研究对象，规定正方向，分解拉力与摩擦力。",
                    probes=(
                        Probe(
                            id="p1",
                            question="受力分析时，先规定正方向再分解，还是直接代公式？",
                            options=("先规定正方向，再分解", "不规定，直接代公式"),
                            targets=("H_L2", "H_L1"),
                            evidence={
                                "A": {"H_L2": 0.9, "H_L1": -0.4},
                                "B": {"H_L1": 0.9, "H_L2": -0.5},
                            },
                        ),
                    ),
                ),
                SolutionNode(
                    id="n3",
                    type="CHECK",
                    text="用单位、量级和极限情况检验加速度。",
                    probes=(
                        Probe(
                            id="p2",
                            question="最后要不要用单位与量级检查结果？",
                            options=("要，先看单位再看量级", "不用，数值算对就行"),
                            targets=("H_L2", "H_L4"),
                            evidence={
                                "A": {"H_L2": 0.9, "H_L4": -0.3},
                                "B": {"H_L4": 0.9, "H_L2": -0.4},
                            },
                        ),
                    ),
                ),
            ),
            edges=(("n1", "n2"), ("n2", "n3")),
        )
        return GraphBuildResult(graph=graph, fingerprint="physics-fake", attempts=1)


def test_physics_is_partial_and_has_its_own_labels() -> None:
    plugin = PhysicsPlugin()

    assert plugin.subject == "physics"
    assert plugin.level is VerifiabilityLevel.PARTIAL
    assert plugin.hypothesis_labels["H_L1"] == "概念 / 公式条件不清"
    assert plugin.hypothesis_labels["H_L2"] == "物理模型 / 条件转译"
    assert plugin.hypothesis_labels["H_L4"] == "执行 / 计算错误"
    # The ids themselves are shared with math; only wording differs.
    assert set(plugin.hypothesis_labels) == set(HYPOTHESES)


def test_physics_identifies_no_annotated_catalog_yet() -> None:
    plugin = PhysicsPlugin()

    assert plugin.identify(PHYSICS_TEXT) is None
    assert SubjectRegistry((plugin,)).for_subject("physics") is plugin


def test_physics_build_without_a_generator_is_an_explicit_refusal() -> None:
    plugin = PhysicsPlugin()

    try:
        plugin.build_graph(ProblemDraft(id="P_PHYS_001", text=PHYSICS_TEXT, subject="physics"))
    except GraphBuildFailed as exc:
        assert exc.reason == "disabled"
        assert "物理插件" in exc.detail
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("physics must not invent a graph without a generator")


def test_physics_evidence_model_reads_generated_weights() -> None:
    plugin = PhysicsPlugin(generator=_PhysicsGenerator())
    graph = plugin.build_graph(ProblemDraft(id="P_PHYS_001", text=PHYSICS_TEXT, subject="physics"))

    model = plugin.evidence_model(graph)

    assert set(model.probe_ids) == {"p1", "p2"}
    assert model.for_probe("p1")["A"] == {"H_L2": 0.9, "H_L1": -0.4}
    assert model.for_probe("p2")["A"] == {"H_L2": 0.9, "H_L4": -0.3}


def test_physics_verify_is_honest_about_partial() -> None:
    verdict = PhysicsPlugin().verify(StudentStep(node_id="n2", text="Fcos30° - μN = ma"))

    assert verdict.status == "unknown"
    assert "PARTIAL" in verdict.detail


def test_labels_change_the_card_wording_not_the_scoring() -> None:
    alignment = AlignmentResult(
        first_divergence="n2",
        matched_node_ids=("n1",),
        missing_node_ids=("n2", "n3"),
        evidence=(),
    )
    labels = PhysicsPlugin.hypothesis_labels

    physics = HypothesisSet.from_alignment(alignment, focus="L2", labels=labels)
    math = HypothesisSet.from_alignment(alignment, focus="L2")

    assert physics.states["H_L2"].hypothesis.label == "物理模型 / 条件转译"
    assert math.states["H_L2"].hypothesis.label == "条件转译 / 参数分类"
    assert physics.posteriors() == math.posteriors()


def _client() -> TestClient:
    generator = _PhysicsGenerator()
    container = build_container(
        LLMSettings(mode="off", api_key="test"),
        generator=generator,  # type: ignore[arg-type]
    )
    assert container.subjects.for_subject("physics") is not None
    return TestClient(create_app(container))


def test_a_physics_stem_runs_the_whole_dialogue_and_gets_a_physics_card() -> None:
    client = _client()
    created = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": PHYSICS_TEXT, "subject": "physics"},
            "attempt": {"answer": "2 m/s^2", "work": WORK},
            "mode": "learning",
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["problem_id"].startswith("P_GEN_")
    assert body["prompt"]["question"].startswith("受力分析时")

    session_id = body["session_id"]
    first = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "先规定正方向，再分解", "option_id": "A"},
    )
    assert first.status_code == 200
    assert first.json()["prompt"]["question"].startswith("最后要不要")

    second = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要，先看单位再看量级", "option_id": "A"},
    )

    assert second.status_code == 200
    diagnosis = second.json()["diagnosis"]
    assert diagnosis is not None
    card = diagnosis["card"]
    # The card is produced by the same builder as math; only the plugin's label
    # makes it read as physics.
    assert card["label"] == "物理模型 / 条件转译"
    assert card["node_id"] in {"n2", "n3"}
    assert "恒成立" not in card["label"]


def test_math_path_still_uses_math_labels() -> None:
    """Both subjects enter through the same command and the same factory."""

    container = build_container(LLMSettings(mode="off", api_key="test"))

    # A math session still starts from the annotated seed; no physics branch is
    # consulted on that path.
    math = container.service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work="定义域 x>0。f'(x)=1/x-a。",
        )
    )
    assert math.session.hypotheses.states["H_L2"].hypothesis.label == "条件转译 / 参数分类"
