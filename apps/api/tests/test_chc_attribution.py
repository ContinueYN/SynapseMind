"""The CHC block is an opt-in problem-side tag, not a student ability score."""

from __future__ import annotations

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.snapshots import SnapshotError, _card_from_json, _card_to_json


def _client(*, chc: bool) -> TestClient:
    return TestClient(
        create_app(
            build_container(
                LLMSettings(mode="off", api_key="test"),
                features=FeatureFlags(chc_attribution=chc),
            )
        )
    )


def _diagnosis(client: TestClient, sample_payload: dict[str, object]) -> dict[str, object]:
    start = client.post("/api/v1/sessions", json=sample_payload)
    assert start.status_code == 201, start.text
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "没有检查", "option_id": "A"},
    )
    second = client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要的，a=0 也要查", "option_id": "A"},
    )
    assert second.status_code == 200, second.text
    diagnosis = second.json()["diagnosis"]
    assert diagnosis is not None
    return diagnosis


def test_attribution_is_absent_when_the_flag_is_off(
    sample_payload: dict[str, object],
) -> None:
    diagnosis = _diagnosis(_client(chc=False), sample_payload)

    assert diagnosis["version"] == "0.1"
    assert "attribution" not in diagnosis["card"]


def test_attribution_carries_the_focus_nodes_top_two_demands(
    sample_payload: dict[str, object],
) -> None:
    diagnosis = _diagnosis(_client(chc=True), sample_payload)

    assert diagnosis["version"] == "0.2"
    attribution = diagnosis["card"]["attribution"]
    assert [item["key"] for item in attribution["dimensions"]] == ["Gf", "WM"]
    assert attribution["dimensions"][0]["label"] == "流体推理"
    assert attribution["dimensions"][0]["weight"] == 0.7
    assert attribution["note"] == "题目需求标签，不是能力测评；单题不足以断言。"


def test_attribution_survives_a_sqlite_reload(
    tmp_path, monkeypatch, sample_payload: dict[str, object]
) -> None:
    monkeypatch.setenv("SYNAPSE_SESSION_DB", str(tmp_path / "state.sqlite3"))
    client = _client(chc=True)
    start = client.post("/api/v1/sessions", json=sample_payload)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "没有检查", "option_id": "A"},
    )
    client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要的，a=0 也要查", "option_id": "A"},
    )

    reloaded = client.get(f"/api/v1/sessions/{session_id}").json()

    assert reloaded["diagnosis"]["version"] == "0.2"
    assert reloaded["diagnosis"]["card"]["attribution"]["dimensions"][0]["key"] == "Gf"


def test_snapshot_rejects_v02_without_attribution() -> None:
    card = {
        "version": "0.2",
        "session_id": "S_TEST",
        "problem_id": "P_TEST",
        "layer": "L2",
        "label": "概念不清",
        "node_id": "n1",
        "one_line": "一句话。",
        "evidence": ["证据"],
        "excluded": [],
        "confidence": 0.8,
        "confidence_label": "high",
        "next_action": {"type": "micro_lesson"},
        "verify": {"type": "transfer", "due_hours": 24},
        "disagree": False,
    }

    try:
        _card_from_json(card, "card")
    except SnapshotError as exc:
        assert "requires attribution" in str(exc)
    else:
        raise AssertionError("expected SnapshotError")


def test_snapshot_round_trip_keeps_attribution() -> None:
    card = _card_from_json(
        {
            "version": "0.2",
            "session_id": "S_TEST",
            "problem_id": "P_TEST",
            "layer": "L2",
            "label": "概念不清",
            "node_id": "n1",
            "one_line": "一句话。",
            "evidence": ["证据"],
            "excluded": [],
            "confidence": 0.8,
            "confidence_label": "high",
            "next_action": {"type": "micro_lesson"},
            "verify": {"type": "transfer", "due_hours": 24},
            "disagree": False,
            "attribution": {
                "dimensions": [{"key": "Gf", "label": "流体推理", "weight": 0.7}],
                "note": "题目需求标签，不是能力测评；单题不足以断言。",
            },
        },
        "card",
    )

    payload = _card_to_json(card)

    assert payload["version"] == "0.2"
    assert payload["attribution"]["dimensions"][0]["key"] == "Gf"
