"""Phase 1b API path: an open domain gets a generated structure graph.

With the model switched on, the reference-free session now returns a *content*
graph instead of only a checklist. The product boundary is unchanged: the graph
is labelled as system-organised, no card is produced, and a generation failure
falls back to the Phase 0 intake instead of a 422.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.generic_graph import (
    GenericGraphBuildFailed,
    GenericGraphBuildResult,
    GenericGraphDraft,
)
from synapse.domain.problem.generic import GenericGraph, GenericNode, NodeKind
from synapse.infrastructure.llm.replay import ReplayLLMClient
from synapse.infrastructure.llm.settings import LLMSettings

ON = LLMSettings(mode="on", api_key="test")
TEXT = "我应该接受北京的工作机会，还是留在上海陪家人？"
ANSWER = "我想去北京，但不想两地分居；要么接受，要么留下。"


class _FakeGenericGenerator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.drafts: list[GenericGraphDraft] = []

    def generate(self, draft: GenericGraphDraft) -> GenericGraphBuildResult:
        self.drafts.append(draft)
        if self.fail:
            raise GenericGraphBuildFailed("timeout", detail="模型没返回")
        return GenericGraphBuildResult(
            graph=GenericGraph(
                problem_id=draft.id,
                version="g2",
                nodes=(
                    GenericNode(id="g1", kind=NodeKind.GOAL, text="决定工作地点", source="system"),
                    GenericNode(
                        id="g2",
                        kind=NodeKind.CONSTRAINT,
                        text="不想长期两地分居",
                        source="system",
                    ),
                    GenericNode(id="g3", kind=NodeKind.DECISION, text="接受北京", source="system"),
                    GenericNode(id="g4", kind=NodeKind.DECISION, text="留在上海", source="system"),
                    GenericNode(
                        id="g5",
                        kind=NodeKind.RISK,
                        text="换城市后收入可能下降",
                        source="system",
                    ),
                ),
            )
        )


def _client(generator: _FakeGenericGenerator) -> tuple[TestClient, object]:
    container = build_container(
        ON,
        llm_client=ReplayLLMClient({}),
        generic_generator=generator,
    )
    return TestClient(create_app(container)), container


def _start(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": TEXT, "subject": "decision"},
            "attempt": {"answer": ANSWER, "work": "", "self_report": "unsure"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_generated_graph_is_shown_as_system_structure_not_a_card() -> None:
    generator = _FakeGenericGenerator()
    client, container = _client(generator)

    body = _start(client)

    assert body["state"] == "CLOSED"
    assert body["diagnosis"] is None
    assert body["prompt"] is None
    intake = body["intake"]
    assert intake["version"] == "0.5"
    assert intake["origin"] == "system"
    assert [node["kind"] for node in intake["graph"]] == [
        "goal",
        "constraint",
        "decision",
        "decision",
        "risk",
    ]
    assert all(node["source"] == "system" for node in intake["graph"])
    assert intake["verifications"] == []
    assert "结构图由模型整理" in intake["disclaimer"]
    # The graph is system output; the student's words are still read separately.
    assert "目标" in intake["observed"]
    # It really was persisted beside the problem, not rebuilt on every read.
    stored = container.problems.get(body["problem_id"])  # type: ignore[attr-defined]
    assert stored is not None and stored.generic is not None


def test_the_generated_structure_survives_a_reload() -> None:
    generator = _FakeGenericGenerator()
    client, _ = _client(generator)
    created = _start(client)

    reloaded = client.get(f"/api/v1/sessions/{created['session_id']}")

    assert reloaded.status_code == 200, reloaded.text
    body = reloaded.json()
    assert body["intake"]["origin"] == "system"
    assert body["intake"]["graph"] == created["intake"]["graph"]
    assert generator.drafts and generator.drafts[0].answer == ANSWER


def test_a_failed_generation_falls_back_to_the_phase_zero_intake() -> None:
    generator = _FakeGenericGenerator(fail=True)
    client, _ = _client(generator)

    body = _start(client)

    assert body["state"] == "CLOSED"
    assert body["problem_id"].startswith("P_GEN_")
    intake = body["intake"]
    assert intake["graph"], "the Phase 1a cue extraction is still the floor"
    assert all(node["source"] == "student" for node in intake["graph"])
    assert intake["origin"] == "student"
    assert generator.drafts, "the resolver must have tried the generator"
