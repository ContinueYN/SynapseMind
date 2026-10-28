from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient


def _start(client: TestClient, payload: dict[str, object]) -> dict[str, Any]:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_start_returns_one_probe_and_no_answer(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    body = _start(client, sample_payload)
    assert body["state"] == "PROBE"
    assert body["prompt"]["question"].count("？") == 1
    assert body["prompt"]["action"] == "ask"
    assert "solution" not in json.dumps(body, ensure_ascii=False)
    assert "1/e" not in body["prompt"]["question"]


def test_two_answers_produce_l2_card(client: TestClient, sample_payload: dict[str, object]) -> None:
    body = _start(client, sample_payload)
    session_id = body["session_id"]

    first = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "没有零点", "option_id": "A"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["prompt"] is not None
    assert first_body["diagnosis"] is None

    second = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要，a=0 也在 a≤0 这一支里", "option_id": "A"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["state"] == "DIAGNOSE"
    assert second_body["diagnosis"] is not None
    assert second_body["diagnosis"]["card"]["layer"] == "L2"
    assert second_body["diagnosis"]["card"]["confidence"] >= 0.8
    assert second_body["diagnosis"]["card"]["evidence"]
    assert any("第 2 轮" in item for item in second_body["diagnosis"]["card"]["evidence"])
    assert "solution" not in json.dumps(second_body, ensure_ascii=False)


def test_unknown_gets_a_different_hint(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    body = _start(client, sample_payload)
    first_question = body["prompt"]["question"]
    response = client.post(
        f"/api/v1/sessions/{body['session_id']}/turns",
        json={"answer": "不会", "option_id": "unknown"},
    )
    assert response.status_code == 200, response.text
    turn = response.json()
    assert turn["prompt"]["action"] == "hint"
    assert turn["prompt"]["question"] != first_question
    assert turn["history"][0]["is_unknown"] is True


def test_get_replays_current_prompt(client: TestClient, sample_payload: dict[str, object]) -> None:
    body = _start(client, sample_payload)
    response = client.get(f"/api/v1/sessions/{body['session_id']}")
    assert response.status_code == 200
    assert response.json()["prompt"]["question"] == body["prompt"]["question"]


def test_exit_closes_without_card(client: TestClient, sample_payload: dict[str, object]) -> None:
    body = _start(client, sample_payload)
    response = client.post(f"/api/v1/sessions/{body['session_id']}/exit")
    assert response.status_code == 200
    closed = response.json()
    assert closed["state"] == "CLOSED"
    assert closed["diagnosis"] is None
    assert closed["notice"]


def test_unknown_session_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/sessions/S_DOES_NOT_EXIST")
    assert response.status_code == 404


def test_invalid_option_is_422(client: TestClient, sample_payload: dict[str, object]) -> None:
    body = _start(client, sample_payload)
    response = client.post(
        f"/api/v1/sessions/{body['session_id']}/turns",
        json={"answer": "???", "option_id": "Z"},
    )
    assert response.status_code == 422


def test_unsupported_problem_is_not_silently_remapped(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "计算 1+1 的值。"},
            "attempt": {"answer": "2"},
            "mode": "learning",
        },
    )
    assert response.status_code == 422
    assert "seed" in response.json()["detail"]
