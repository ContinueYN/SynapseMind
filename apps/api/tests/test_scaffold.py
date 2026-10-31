"""Blank-attempt entry: example first, then the normal probe ladder."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from synapse.domain.dialogue.states import DialogueState
from synapse.infrastructure.snapshots import decode_session, encode_session

PROBLEM = "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"


def _blank(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": PROBLEM},
            "attempt": {"answer": "不会", "work": "", "self_report": "no_idea"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_blank_attempt_gets_an_example_not_a_probe(client: TestClient) -> None:
    body = _blank(client)

    assert body["state"] == "SCAFFOLD"
    assert body["prompt"] is None
    assert body["diagnosis"] is None
    assert body["hint"] is None
    assert body["scaffold"]["steps"][0]["text"].startswith("确认定义域")
    assert body["scaffold"]["focus_node_id"] == "n2"
    assert "1/e" not in body["scaffold"]["steps"][0]["text"]
    assert body["scaffold"]["disclaimer"]

    reloaded = client.get(f"/api/v1/sessions/{body['session_id']}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["scaffold"]["steps"][0]["text"] == body["scaffold"]["steps"][0]["text"]


def test_one_written_line_returns_to_the_probe_ladder(client: TestClient) -> None:
    body = _blank(client)
    session_id = body["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "定义域是 x>0"},
    )
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["state"] == "PROBE"
    assert moved["scaffold"] is None
    assert moved["prompt"] is not None
    assert moved["prompt"]["question"].count("？") == 1


def test_a_second_blank_fades_to_two_steps_then_stops(client: TestClient) -> None:
    body = _blank(client)
    session_id = body["session_id"]

    first = client.post(f"/api/v1/sessions/{session_id}/turns", json={"answer": "不知道"})
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "SCAFFOLD"
    assert len(first.json()["scaffold"]["steps"]) == 2

    second = client.post(f"/api/v1/sessions/{session_id}/turns", json={"answer": "还是不知道"})
    assert second.status_code == 200, second.text
    stopped = second.json()
    assert stopped["state"] == "CLOSED"
    assert stopped["diagnosis"] is None
    assert "先写一行" in stopped["notice"]


def test_exit_from_scaffold_does_not_make_a_card(client: TestClient) -> None:
    body = _blank(client)
    response = client.post(f"/api/v1/sessions/{body['session_id']}/exit")
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "CLOSED"
    assert response.json()["diagnosis"] is None


def test_scaffold_progress_survives_a_snapshot(client: TestClient) -> None:
    body = _blank(client)
    session_id = body["session_id"]
    client.post(f"/api/v1/sessions/{session_id}/turns", json={"answer": "不知道"})

    session = client.app.state.container.sessions.get(session_id)
    assert session is not None
    restored = decode_session(encode_session(session))

    assert restored.state is DialogueState.SCAFFOLD
    assert restored.scaffold_level == 2
    assert restored.scaffold_work == "不知道"
