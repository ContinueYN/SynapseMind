from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.graph import GraphBuildResult
from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.diagnosis.work import WorkFinding
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.problem.models import (
    AlignmentResult,
    Interval,
    Probe,
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
    VerificationClaim,
)
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.snapshots import (
    SnapshotError,
    decode_problem,
    decode_session,
    encode_problem,
    encode_session,
)
from synapse.infrastructure.sqlite_state import (
    SqliteProblemRepository,
    SqliteSessionRepository,
)


class _OneProbeGenerator:
    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        graph = SolutionGraph(
            problem_id=draft.id,
            version="0.1",
            stem=draft.text,
            nodes=(
                SolutionNode(
                    id="n1",
                    type="CONDITION",
                    text="先确认参数分类。",
                    probes=(
                        Probe(
                            id="p1",
                            question="a=0 这个边界要不要单独检查？",
                            options=("要", "不要"),
                            targets=("H_L2", "H_L1"),
                            evidence={"A": {"H_L2": 0.6}, "B": {"H_L1": 0.5}},
                        ),
                    ),
                ),
            ),
            edges=(),
        )
        return GraphBuildResult(graph=graph, fingerprint="fake", attempts=1)


def _card_session(client: TestClient, payload: dict[str, object]) -> tuple[str, DialogueSession]:
    created = client.post("/api/v1/sessions", json=payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    for answer in ("没有零点", "要，a=0 也在 a≤0 这一支里"):
        response = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"answer": answer, "option_id": "A"},
        )
        assert response.status_code == 200, response.text
    container = client.app.state.container
    session = container.sessions.get(session_id)
    assert session is not None
    return session_id, session


def _minimal_session() -> DialogueSession:
    return DialogueSession(
        session_id="S_CORRUPT00001",
        problem_id="P_FUNC_001",
        state=DialogueState.PROBE,
        alignment=AlignmentResult(
            first_divergence="n3",
            matched_node_ids=("n1", "n2"),
            missing_node_ids=("n3",),
            evidence=("n1 已写",),
        ),
        hypotheses=HypothesisSet(),
        max_turns=6,
        created_at=datetime(2026, 10, 31, tzinfo=UTC),
    )


def _generated_problem() -> Problem:
    probe = Probe(
        id="p_gen_1",
        question="先确认哪一步？",
        options=("读题", "求导"),
        targets=("H_L1",),
        evidence={"A": {"H_L1": 0.8}},
        correct_option="A",
    )
    node = SolutionNode(
        id="n1",
        type="READ",
        text="先读清参数范围",
        demand={"V": 0.5},
        common_errors=("漏掉 a≤0",),
        probes=(probe,),
    )
    claim = VerificationClaim(
        kind="parameter_range",
        parameter="a",
        variable="x",
        variable_domain="x>0",
        expression="x-a",
        relation="<=",
        intervals=(Interval(lower="1/E", upper=None, lower_inclusive=True, upper_inclusive=False),),
    )
    graph = SolutionGraph(
        problem_id="P_GEN_TEST0001",
        version="0.1",
        stem="测试用生成题",
        nodes=(node,),
        edges=(),
        claim=claim,
    )
    return Problem(
        id="P_GEN_TEST0001",
        title="测试用生成题",
        text="测试用生成题",
        graph=graph,
        annotated=False,
    )


def test_snapshot_round_trips_a_card_session(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    _, session = _card_session(client, sample_payload)
    assert session.diagnosis is not None
    session.work_findings = (
        WorkFinding(
            kind="identity",
            left="x+1",
            right="2x",
            detail="x=0.1 时左边 1.1、右边 0.2",
            counterexample="x=0.1",
            summary="x=0.1 时左边 1.1、右边 0.2",
        ),
    )

    restored = decode_session(encode_session(session))

    assert restored == session
    assert restored.diagnosis == session.diagnosis
    assert restored.hypotheses.posteriors() == session.hypotheses.posteriors()
    assert restored.history == session.history
    assert restored.work_findings[0].summary == "x=0.1 时左边 1.1、右边 0.2"


def test_sqlite_session_repository_restores_a_session(
    tmp_path: Path, client: TestClient, sample_payload: dict[str, object]
) -> None:
    session_id, session = _card_session(client, sample_payload)
    path = tmp_path / "state.sqlite3"
    SqliteSessionRepository(path).add(session)

    restored = SqliteSessionRepository(path).get(session_id)

    assert restored == session


def test_api_restores_a_session_after_a_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_payload: dict[str, object],
) -> None:
    monkeypatch.setenv("SYNAPSE_SESSION_DB", str(tmp_path / "state.sqlite3"))
    first = TestClient(create_app())
    session_id, _ = _card_session(first, sample_payload)
    before = first.get(f"/api/v1/sessions/{session_id}").json()
    assert before["diagnosis"] is not None

    # A brand-new app/container, the same SQLite file: this is what an API
    # restart looks like to the browser.
    second = TestClient(create_app())
    after = second.get(f"/api/v1/sessions/{session_id}").json()

    assert after == before
    assert after["history"] == before["history"]

    disagreed = second.post(f"/api/v1/sessions/{session_id}/card/disagree")
    assert disagreed.status_code == 200, disagreed.text
    assert disagreed.json()["card"]["disagree"] is True

    third = TestClient(create_app())
    reloaded = third.get(f"/api/v1/sessions/{session_id}").json()
    assert reloaded["diagnosis"]["card"]["disagree"] is True


def test_api_restores_a_generated_problem_after_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNAPSE_SESSION_DB", str(tmp_path / "state.sqlite3"))
    settings = LLMSettings(mode="off")
    first = TestClient(create_app(build_container(settings, generator=_OneProbeGenerator())))
    created = first.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "已知 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的取值范围。"},
            "attempt": {"answer": "a∈(-2,2)", "work": ""},
            "mode": "learning",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    session_id = body["session_id"]
    problem_id = body["problem_id"]
    assert problem_id.startswith("P_GEN_")
    assert body["prompt"] is not None

    second = TestClient(create_app(build_container(settings, generator=_OneProbeGenerator())))
    restored = second.get(f"/api/v1/sessions/{session_id}")

    assert restored.status_code == 200, restored.text
    assert restored.json()["problem_id"] == problem_id
    assert restored.json()["problem_text"] == body["problem_text"]
    assert restored.json()["prompt"]["question"] == body["prompt"]["question"]


def test_seed_problem_round_trips_through_the_codec() -> None:
    assert decode_problem(encode_problem(SAMPLE_PROBLEM)) == SAMPLE_PROBLEM


def test_sqlite_problem_repository_restores_a_generated_problem(tmp_path: Path) -> None:
    problem = _generated_problem()
    path = tmp_path / "state.sqlite3"
    SqliteProblemRepository(path).add(problem)

    repo = SqliteProblemRepository(path)
    restored = repo.get(problem.id)

    assert restored == problem
    assert restored is not None
    assert restored.annotated is False
    assert problem.id not in repo.annotated_ids
    assert repo.get("P_FUNC_001") is not None


def test_corrupt_session_snapshot_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    session = _minimal_session()
    repo.add(session)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE sessions SET snapshot = ? WHERE session_id = ?",
            ("not-json", session.session_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SnapshotError, match="valid JSON"):
        repo.get(session.session_id)


def test_session_repository_rejects_an_in_memory_path() -> None:
    with pytest.raises(ValueError, match="must be a file"):
        SqliteSessionRepository(Path(":memory:"))
