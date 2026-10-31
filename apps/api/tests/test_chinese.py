"""M2.5 S7: Chinese is the NONE-tier subject.

The architecture claim is narrow and testable: the same dialogue kernel serves a
third subject, and the tier degrades the *promise* — no probe turn, no diagnosis
card, only the structure hint. Nothing in ``domain/dialogue`` learns about 语文.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.commands import StartSessionCommand
from synapse.application.graph import GraphBuildFailed, GraphBuildResult
from synapse.application.subject import (
    StudentStep,
    SubjectRegistry,
    VerifiabilityLevel,
)
from synapse.domain.problem.alignment import ClauseCueAligner
from synapse.domain.problem.models import (
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.subjects.chinese import ChinesePlugin

CHINESE_TEXT = "阅读下面的文字，完成题目：文中两次写到“灯”，请结合全文简要分析其作用。"
WORK = "先读题干，圈出「结合全文」这个限制语。"


class _ChineseGenerator:
    """A probe-less four-step graph, as the NONE prompt asks for."""

    def __init__(self) -> None:
        self.calls: list[ProblemDraft] = []

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        self.calls.append(draft)
        graph = SolutionGraph(
            problem_id=draft.id,
            version="g1",
            stem=draft.text,
            nodes=(
                SolutionNode(id="n1", type="READ", text="读题干，圈出限制语与分值"),
                SolutionNode(id="n2", type="CONDITION", text="定位原文区间，勾出依据句"),
                SolutionNode(id="n3", type="COMPUTE", text="分点组织答案，写完整句子"),
                SolutionNode(id="n4", type="CHECK", text="检查扣题与分值对应"),
            ),
            edges=(("n1", "n2"), ("n2", "n3"), ("n3", "n4")),
        )
        return GraphBuildResult(graph=graph, fingerprint="chinese-fake", attempts=1)


def test_chinese_is_the_none_tier() -> None:
    plugin = ChinesePlugin()

    assert plugin.subject == "chinese"
    assert plugin.level is VerifiabilityLevel.NONE
    assert SubjectRegistry((plugin,)).for_subject("chinese") is plugin


def test_chinese_never_identifies_on_its_own() -> None:
    """The plugin's hook is catalog-only; generic routing uses the detector."""

    assert ChinesePlugin().identify(CHINESE_TEXT) is None


def test_chinese_uses_clause_level_alignment() -> None:
    """S8: the NONE tier opts into the clause matcher through the plugin port."""

    problem = Problem(
        id="P_CN_TEST",
        title="语文",
        text=CHINESE_TEXT,
        subject="chinese",
        annotated=False,
        graph=SolutionGraph(
            problem_id="P_CN_TEST",
            version="v1",
            stem=CHINESE_TEXT,
            nodes=(SolutionNode(id="n1", type="READ", text="读题干，圈出限制语"),),
            edges=(),
        ),
    )

    assert isinstance(ChinesePlugin().aligner_for(problem), ClauseCueAligner)


def test_chinese_never_returns_a_probe_even_if_a_graph_has_one() -> None:
    from synapse.domain.problem.models import Probe

    node = SolutionNode(
        id="n2",
        type="CONDITION",
        text="定位原文区间",
        probes=(Probe(id="p1", question="先定位还是先概括？", options=("A", "B")),),
    )

    assert ChinesePlugin().probes_for(node) == ()


def test_chinese_has_no_evidence_model() -> None:
    model = ChinesePlugin().evidence_model(
        _ChineseGenerator()
        .generate(ProblemDraft(id="P_CN_001", text=CHINESE_TEXT, subject="chinese"))
        .graph
    )

    assert model.probe_ids == ()


def test_chinese_verify_is_always_unknown_and_says_why() -> None:
    verdict = ChinesePlugin().verify(StudentStep(node_id="n2", text="两次写到灯，形成照应"))

    assert verdict.status == "unknown"
    assert "NONE" in verdict.detail


def test_chinese_build_without_a_generator_is_an_explicit_refusal() -> None:
    try:
        ChinesePlugin().build_graph(
            ProblemDraft(id="P_CN_001", text=CHINESE_TEXT, subject="chinese")
        )
    except GraphBuildFailed as exc:
        assert exc.reason == "disabled"
        assert "语文插件" in exc.detail
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("chinese must not invent a graph without a generator")


def test_chinese_build_delegates_to_the_generator() -> None:
    generator = _ChineseGenerator()
    plugin = ChinesePlugin(generator=generator)

    graph = plugin.build_graph(ProblemDraft(id="P_CN_001", text=CHINESE_TEXT, subject="chinese"))

    assert graph.problem_id == "P_CN_001"
    assert [node.id for node in graph.nodes] == ["n1", "n2", "n3", "n4"]
    assert generator.calls[0].subject == "chinese"


def _client() -> tuple[TestClient, _ChineseGenerator]:
    generator = _ChineseGenerator()
    container = build_container(
        LLMSettings(mode="off", api_key="test"),
        generator=generator,  # type: ignore[arg-type]
    )
    return TestClient(create_app(container)), generator


def test_a_chinese_stem_gets_a_structure_hint_instead_of_a_card() -> None:
    client, generator = _client()
    created = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": CHINESE_TEXT, "subject": "chinese"},
            "attempt": {"answer": "答：形成照应。", "work": WORK},
            "mode": "learning",
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert generator.calls and generator.calls[0].subject == "chinese"
    assert body["state"] == "CLOSED"
    assert body["prompt"] is None
    assert body["diagnosis"] is None
    assert "结构提示" in (body["notice"] or "")

    hint = body["hint"]
    assert hint["level"] == "none"
    assert hint["subject"] == "chinese"
    assert [(step["node_id"], step["status"]) for step in hint["steps"]] == [
        ("n1", "covered"),
        ("n2", "missing"),
        ("n3", "missing"),
        ("n4", "missing"),
    ]
    assert hint["focus_node_id"] == "n2"
    assert hint["disclaimer"]

    # Reloading must show the same hint: it is derived, not stored.
    reloaded = client.get(f"/api/v1/sessions/{body['session_id']}")
    assert reloaded.status_code == 200
    assert reloaded.json()["hint"]["one_line"] == hint["one_line"]

    # Answering is refused, and the hint is still there for the client.
    turn = client.post(
        f"/api/v1/sessions/{body['session_id']}/turns",
        json={"answer": "A", "option_id": "A"},
    )
    assert turn.status_code == 200
    assert turn.json()["notice"] == "会话已结束，不再接受新的回答。"
    assert turn.json()["hint"]["level"] == "none"


def test_a_half_written_step_is_reported_as_partial() -> None:
    """S8 end to end: the hint can say "只写到一部分" without calling it wrong."""

    client, _ = _client()
    created = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": CHINESE_TEXT, "subject": "chinese"},
            "attempt": {
                "answer": "答：先定位再概括。",
                "work": "读题干，定位原文区间。",
            },
            "mode": "learning",
        },
    )

    assert created.status_code == 201, created.text
    hint = created.json()["hint"]
    assert hint["version"] == "0.2"
    assert [(step["node_id"], step["status"]) for step in hint["steps"]] == [
        ("n1", "covered"),
        ("n2", "partial"),
        ("n3", "missing"),
        ("n4", "missing"),
    ]
    assert hint["focus_node_id"] == "n2"
    assert "只写到了" in hint["one_line"]
    assert "一部分" in hint["one_line"]
    assert "卡" not in hint["one_line"] + hint["next_step"]


def test_a_chinese_subject_without_a_generator_stays_an_explicit_422(
    client: TestClient,
) -> None:
    """No key / mode off: the honest answer is still "cannot serve", not a hint."""

    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": CHINESE_TEXT, "subject": "chinese"},
            "attempt": {"answer": "答：形成照应。", "work": WORK},
            "mode": "learning",
        },
    )

    assert response.status_code == 422
    assert "建图" in response.json()["detail"]


def test_the_math_path_never_reaches_the_hint() -> None:
    """Regression guard: the tier gate must not touch STRONG subjects."""

    container = build_container(LLMSettings(mode="off", api_key="test"))

    view = container.service.start(
        StartSessionCommand(
            problem_text=(
                "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"
            ),
            answer="a≥1/e",
            work="定义域 x>0。f'(x)=1/x-a。",
        )
    )

    assert view.hint is None
    assert view.prompt is not None
