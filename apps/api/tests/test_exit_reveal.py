"""Reveal is an explicit exit action, never a property of a learning turn."""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.graph import GraphBuildResult
from synapse.domain.problem.models import ProblemDraft, SolutionGraph, SolutionNode
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_ANSWER, SAMPLE_PROBLEM

TEXT = "质量 2 kg 的物块在水平面上，求加速度。"


class _FakeGenerator:
    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        return GraphBuildResult(
            graph=SolutionGraph(
                problem_id=draft.id,
                version="v1",
                stem=draft.text,
                nodes=(SolutionNode(id="n1", type="READ", text="先读题。"),),
                edges=(),
            ),
            fingerprint="fake",
            attempts=1,
        )


def _client() -> TestClient:
    return TestClient(create_app(build_container(LLMSettings(mode="off", api_key="test"))))


def _generated_client() -> TestClient:
    return TestClient(
        create_app(
            build_container(
                LLMSettings(mode="off", api_key="test"),
                generator=_FakeGenerator(),  # type: ignore[arg-type]
            )
        )
    )


def _start(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": SAMPLE_PROBLEM.text},
            "attempt": {"answer": "a≥1/e", "work": "定义域 x>0。"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_a_learning_turn_never_contains_the_answer() -> None:
    client = _client()
    body = client.get(f"/api/v1/sessions/{_start(client)}").json()

    assert body.get("answer") is None
    assert body.get("solution") is None


def test_plain_exit_does_not_reveal_the_answer() -> None:
    client = _client()
    session_id = _start(client)

    body = client.post(f"/api/v1/sessions/{session_id}/exit").json()

    assert body["state"] == "CLOSED"
    assert body.get("answer") is None
    assert body.get("solution") is None
    assert "不展示最终答案" in body["notice"]


def test_explicit_exit_with_reveal_returns_the_stored_answer() -> None:
    client = _client()
    session_id = _start(client)

    body = client.post(
        f"/api/v1/sessions/{session_id}/exit",
        json={"reveal": True},
    ).json()

    assert body["state"] == "CLOSED"
    assert body["answer"] == SAMPLE_ANSWER
    assert "定义域" in body["solution"]


def test_a_generated_problem_says_it_has_no_stored_solution() -> None:
    client = _generated_client()
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": TEXT},
            "attempt": {"answer": "a=5", "work": "先读题。"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]

    body = client.post(
        f"/api/v1/sessions/{session_id}/exit",
        json={"reveal": True},
    ).json()

    assert body.get("answer") is None
    assert body.get("solution") is None
    assert "没有存储解法" in body["notice"]
