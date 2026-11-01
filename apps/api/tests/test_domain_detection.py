"""Open domain detection: deterministic first, model only when needed.

Phase 0 changed what a non-decisive score means. It is no longer a 422: the
resolver keeps the label as generic mode and the session starts. These tests
cover the detector and its cascade; the HTTP-level entry cases live in
``test_generic_entry.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.application.domain_detection import (
    CascadeDomainDetector,
    DetectedDomain,
    HeuristicDomainDetector,
    declared_domain,
)
from synapse.application.graph import GraphBuildResult
from synapse.application.llm import LLMResponse
from synapse.domain.problem.models import ProblemDraft, SolutionGraph, SolutionNode
from synapse.infrastructure.llm.domain_detector import LLMDomainDetector
from synapse.infrastructure.llm.settings import LLMSettings

MATH = "已知函数 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的取值范围。"
PHYSICS = (
    "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，"
    "动摩擦因数 0.2，求物块的加速度。"
)
CHINESE = "阅读下面的文字，完成题目：文中两次写到“灯”，请结合全文简要分析其作用。"
PROGRAMMING = "我的 Python 脚本报错了：IndexError: list index out of range，列表里明明有元素。"
DECISION = "我应该接受北京的工作机会，还是留在上海陪家人？"
RESEARCH = "这篇论文的样本量够吗？实验设计有没有对照组？"


class _FakeGenerator:
    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        graph = SolutionGraph(
            problem_id=draft.id,
            version="v1",
            stem=draft.text,
            nodes=(SolutionNode(id="n1", type="READ", text="先读题，标出已知量。"),),
            edges=(),
        )
        return GraphBuildResult(graph=graph, fingerprint="fake", attempts=1)


class _FakeDetector:
    def __init__(self, result: DetectedDomain) -> None:
        self.result = result
        self.calls = 0

    def detect(self, text: str) -> DetectedDomain:
        del text
        self.calls += 1
        return self.result


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, request: object, *, timeout_s: float) -> LLMResponse:
        del request, timeout_s
        return LLMResponse(text=self.text, model="fake")


def test_the_three_classic_domains_are_still_detected_without_a_model() -> None:
    detector = HeuristicDomainDetector()

    assert detector.detect(MATH).domain == "math"
    assert detector.detect(PHYSICS).domain == "physics"
    assert detector.detect(CHINESE).domain == "chinese"


def test_open_domains_are_detected_from_their_own_vocabulary() -> None:
    detector = HeuristicDomainDetector()

    assert detector.detect(PROGRAMMING).domain == "programming"
    assert detector.detect(DECISION).domain == "decision"
    assert detector.detect(RESEARCH).domain == "research"


def test_an_unknown_stem_is_not_forced_into_a_domain() -> None:
    result = HeuristicDomainDetector().detect("我最近很烦，不知道该怎么办。")

    assert result.domain is None
    assert result.confidence < 0.6
    assert result.method == "none"


def test_a_mixed_stem_falls_below_the_margin_instead_of_guessing() -> None:
    mixed = "这段 Python 代码里的导数是错的。"

    result = HeuristicDomainDetector().detect(mixed)

    # programming 4 vs math 2: evidence is full but the margin is 0.5, so the
    # stem is not decisive and the resolver keeps the generic label.
    assert result.domain is None
    assert result.confidence < 0.6


def test_a_clarification_can_name_a_domain_without_a_model() -> None:
    assert declared_domain("这更像一个生活决策：我要不要换城市工作。") == "decision"
    assert declared_domain("这是 Python 代码报错。") == "programming"
    assert declared_domain("更像一道数学证明题。") == "math"
    # A structural answer does not get forced into a domain.
    assert declared_domain("我卡在第二步，不知道先做哪个。") is None


def test_model_is_only_asked_when_the_heuristic_is_not_decisive() -> None:
    first = _FakeDetector(DetectedDomain("math", 1.0))
    fallback = _FakeDetector(DetectedDomain("physics", 0.8))
    detector = CascadeDomainDetector(first, fallback)

    assert detector.detect(MATH).domain == "math"
    assert fallback.calls == 0

    first.result = DetectedDomain(None, 0.2)
    assert detector.detect("嗯。").domain == "physics"
    assert fallback.calls == 1


def test_model_json_is_validated_and_labels_stay_open() -> None:
    detector = LLMDomainDetector(_FakeLLM('{"domain":"physics","confidence":0.9}'))
    assert detector.detect(PHYSICS).domain == "physics"

    open_label = LLMDomainDetector(_FakeLLM('{"domain":"rust","confidence":0.9}'))
    assert open_label.detect("borrow checker 又报错了").domain == "rust"

    generic = LLMDomainDetector(_FakeLLM('{"domain":"generic","confidence":0.9}'))
    assert generic.detect("嗯。").domain is None

    low = LLMDomainDetector(_FakeLLM('{"domain":"physics","confidence":0.2}'))
    assert low.detect(PHYSICS).domain is None

    broken = LLMDomainDetector(_FakeLLM("not json"))
    assert broken.detect(PHYSICS).domain is None


def test_a_physics_stem_without_a_declared_subject_reaches_the_physics_plugin() -> None:
    from synapse.api.main import create_app

    app = create_app(
        build_container(
            LLMSettings(mode="off", api_key="test"),
            generator=_FakeGenerator(),  # type: ignore[arg-type]
        )
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": PHYSICS},
            "attempt": {"answer": "5 m/s", "work": "先读题，标出已知量。"},
            "mode": "learning",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subject"] == "physics"
    assert body["domain"]["verification"] == "empirical"
    assert body["problem_id"].startswith("P_GEN_")
