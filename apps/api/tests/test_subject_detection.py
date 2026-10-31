"""Auto subject detection: deterministic first, model only when needed."""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.application.graph import GraphBuildResult
from synapse.application.llm import LLMResponse
from synapse.application.subject_detection import (
    CompositeSubjectDetector,
    DetectedSubject,
    HeuristicSubjectDetector,
)
from synapse.domain.problem.models import ProblemDraft, SolutionGraph, SolutionNode
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.llm.subject_detector import LLMSubjectDetector

MATH = "已知函数 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的取值范围。"
PHYSICS = (
    "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，"
    "动摩擦因数 0.2，求物块的加速度。"
)
CHINESE = "阅读下面的文字，完成题目：文中两次写到“灯”，请结合全文简要分析其作用。"


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
    def __init__(self, result: DetectedSubject) -> None:
        self.result = result
        self.calls = 0

    def detect(self, text: str) -> DetectedSubject:
        del text
        self.calls += 1
        return self.result


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, request: object, *, timeout_s: float) -> LLMResponse:
        del request, timeout_s
        return LLMResponse(text=self.text, model="fake")


def test_three_subjects_are_detected_without_a_model() -> None:
    detector = HeuristicSubjectDetector()

    assert detector.detect(MATH).subject == "math"
    assert detector.detect(PHYSICS).subject == "physics"
    assert detector.detect(CHINESE).subject == "chinese"


def test_ambiguous_stem_is_not_guessed() -> None:
    result = HeuristicSubjectDetector().detect("求一个东西。")

    assert result.subject is None
    assert result.confidence < 0.6


def test_model_is_only_asked_when_the_heuristic_is_not_decisive() -> None:
    first = _FakeDetector(DetectedSubject("math", 1.0))
    fallback = _FakeDetector(DetectedSubject("physics", 0.8))
    detector = CompositeSubjectDetector(first, fallback)

    assert detector.detect(MATH).subject == "math"
    assert fallback.calls == 0

    first.result = DetectedSubject(None, 0.2)
    assert detector.detect("嗯。").subject == "physics"
    assert fallback.calls == 1


def test_model_json_is_validated() -> None:
    detector = LLMSubjectDetector(_FakeLLM('{"subject":"physics","confidence":0.9}'))

    assert detector.detect(PHYSICS).subject == "physics"

    low = LLMSubjectDetector(_FakeLLM('{"subject":"physics","confidence":0.2}'))
    assert low.detect(PHYSICS).subject is None

    broken = LLMSubjectDetector(_FakeLLM("not json"))
    assert broken.detect(PHYSICS).subject is None


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
    assert body["problem_id"].startswith("P_GEN_")


def test_an_ambiguous_stem_is_refused_instead_of_defaulting_to_math() -> None:
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
            "problem": {"text": "求一个东西。"},
            "attempt": {"answer": "不会", "self_report": "no_idea"},
            "mode": "learning",
        },
    )

    assert response.status_code == 422
    assert "无法可靠识别" in response.json()["detail"]
