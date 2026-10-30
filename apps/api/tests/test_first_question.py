"""First-question latency: the opening prompt must not wait for a rewrite.

Chapter 12 §12.8 puts one composition inside the 8s first-question budget. A
generated probe was written by the graph model seconds earlier, so a second
model pass only re-words it; the deterministic renderer answers instead. The
hand-written seed probe keeps the rewrite (T3) because its wording is not
model output and its path has no graph build to pay for.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.application.graph import GraphBuildResult
from synapse.application.llm import LLMRequest, LLMResponse
from synapse.domain.problem.models import (
    Probe,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM

UNSEEN = "已知函数 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的取值范围。"
WORK = "对任意 x∈R 成立。"
PREFIX = "换个问法："

ON = LLMSettings(
    mode="on",
    api_key="sk-stub",
    max_attempts=1,
    audit_path="var/audit/unused.jsonl",
)


class _FakeGenerator:
    """A two-probe generated graph, so no model call is needed to build it."""

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        graph = SolutionGraph(
            problem_id=draft.id,
            version="v1",
            stem=draft.text,
            nodes=(
                SolutionNode(id="n1", type="READ", text="确认条件：对所有 x∈R 成立。"),
                SolutionNode(
                    id="n2",
                    type="CONDITION",
                    text="按 a≤0 / a>0 分类讨论。",
                    probes=(
                        Probe(
                            id="p1",
                            question="a=0 这个边界要不要单独检查？",
                            options=("要，a=0 也在 a≤0 这一支里", "不要，a>0 已经覆盖"),
                            targets=("H_L2", "H_L1"),
                            evidence={"A": {"H_L2": 0.6, "H_L1": -0.3}, "B": {"H_L1": 0.6}},
                        ),
                    ),
                ),
                SolutionNode(
                    id="n3",
                    type="CHECK",
                    text="检验端点 a=±2 是否可取。",
                    probes=(
                        Probe(
                            id="p2",
                            question="检验端点时，代入 a=2 得到什么？",
                            options=("左边等于 0，端点不可取", "左边大于 0，端点可取"),
                            targets=("H_L2", "H_L4"),
                            evidence={"A": {"H_L2": 0.7, "H_L4": -0.4}, "B": {"H_L4": 0.7}},
                        ),
                    ),
                ),
            ),
            edges=(("n1", "n2"), ("n2", "n3")),
        )
        return GraphBuildResult(graph=graph, fingerprint="fake", attempts=1)


class RecordingClient:
    """Answers probe rewrites only; a graph request would be a test failure."""

    def __init__(self) -> None:
        self.purposes: list[str] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        self.purposes.append(request.purpose)
        assert request.purpose == "probe_rewrite", "the graph must come from the fake generator"
        original = request.user.split("要改写的问题：", 1)[1].splitlines()[0]
        return LLMResponse(
            text=json.dumps({"question": f"{PREFIX}{original}"}, ensure_ascii=False),
            model="stub-1",
            latency_ms=1,
        )


def _client() -> tuple[TestClient, RecordingClient]:
    stub = RecordingClient()
    container = build_container(ON, llm_client=stub, generator=_FakeGenerator())
    from synapse.api.main import create_app

    return TestClient(create_app(container)), stub


def _start(client: TestClient, text: str) -> dict:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": text},
            "attempt": {"answer": "暂时不确定", "work": WORK},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_generated_problem_skips_the_rewrite_on_the_first_question() -> None:
    client, stub = _client()

    body = _start(client, UNSEEN)

    assert body["problem_id"].startswith("P_GEN_")
    assert body["prompt"]["question"] == "a=0 这个边界要不要单独检查？"
    assert stub.purposes == [], "the opening prompt must not spend a model round trip"


def test_generated_problem_rewrites_from_the_second_question_on() -> None:
    client, stub = _client()
    session_id = _start(client, UNSEEN)["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要，a=0 也在 a≤0 这一支里", "option_id": "A"},
    )

    assert response.status_code == 200
    assert stub.purposes == ["probe_rewrite"]
    assert response.json()["prompt"]["question"].startswith(PREFIX)


def test_annotated_seed_still_rewrites_the_first_question() -> None:
    client, stub = _client()

    body = _start(client, SAMPLE_PROBLEM.text)

    assert body["problem_id"] == SAMPLE_PROBLEM.id
    assert stub.purposes == ["probe_rewrite"]
    assert body["prompt"]["question"].startswith(PREFIX)


def test_the_opening_prompt_is_still_audited_when_rewritten() -> None:
    auditor = InMemoryCallAuditor()
    container = build_container(
        ON,
        llm_client=RecordingClient(),
        auditor=auditor,
        generator=_FakeGenerator(),
    )
    from synapse.api.main import create_app

    TestClient(create_app(container)).post(
        "/api/v1/sessions",
        json={
            "problem": {"text": SAMPLE_PROBLEM.text},
            "attempt": {"answer": "暂时不确定", "work": WORK},
            "mode": "learning",
        },
    )

    assert [entry.kind for entry in auditor.entries] == ["llm_call"]
