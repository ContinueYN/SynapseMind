from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.main import create_app
from synapse.application.review import ReviewItem
from synapse.infrastructure.review import SqliteReviewQueue

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "review-queue.schema.json"


def _item(session_id: str = "S_ABC123456789") -> ReviewItem:
    return ReviewItem(
        session_id=session_id,
        problem_id="P_PUB_002",
        layer="L2",
        label="概念不清：恒成立与最值",
        node_id="n3",
        one_line="漏掉了 a≤0 这一支。",
        confidence=0.86,
        created_at="2026-10-31T08:00:00+00:00",
    )


def test_sqlite_queue_round_trips_and_replaces(tmp_path: Path) -> None:
    queue = SqliteReviewQueue(tmp_path / "review.sqlite3")
    queue.record(_item())
    queue.record(_item("S_DEF987654321"))

    items = queue.items()
    assert {item.session_id for item in items} == {"S_ABC123456789", "S_DEF987654321"}

    queue.record(_item())
    assert len(queue.items()) == 2


def test_disagreement_is_written_to_the_review_queue(
    tmp_path: Path,
    monkeypatch,
    sample_payload: dict[str, object],
) -> None:
    db_path = tmp_path / "review.sqlite3"
    monkeypatch.setenv("SYNAPSE_REVIEW_DB", str(db_path))
    client = TestClient(create_app())

    body = client.post("/api/v1/sessions", json=sample_payload).json()
    session_id = body["session_id"]
    for answer in ("没有零点", "要，a=0 也在 a≤0 这一支里"):
        response = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"answer": answer, "option_id": "A"},
        )
        assert response.status_code == 200, response.text

    response = client.post(f"/api/v1/sessions/{session_id}/card/disagree")
    assert response.status_code == 200, response.text

    items = SqliteReviewQueue(db_path).items()
    assert len(items) == 1
    item = items[0]
    assert item.session_id == session_id
    assert item.node_id == "n3"
    assert item.layer == "L2"
    assert item.one_line

    # A repeated request is idempotent: one session, one review row.
    again = client.post(f"/api/v1/sessions/{session_id}/card/disagree")
    assert again.status_code == 200, again.text
    assert len(SqliteReviewQueue(db_path).items()) == 1


def test_review_listing_is_empty_when_nothing_was_disagreed(client: TestClient) -> None:
    response = client.get("/api/v1/review/items")

    assert response.status_code == 200, response.text
    assert response.json() == {"version": "0.1", "items": []}


def test_review_listing_carries_the_card_but_not_the_student_work(
    client: TestClient,
    sample_payload: dict[str, object],
) -> None:
    attempt = sample_payload["attempt"]
    assert isinstance(attempt, dict)
    work = str(attempt["work"])
    body = client.post("/api/v1/sessions", json=sample_payload).json()
    session_id = body["session_id"]
    for answer in ("没有零点", "要，a=0 也在 a≤0 这一支里"):
        response = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"answer": answer, "option_id": "A"},
        )
        assert response.status_code == 200, response.text

    card = client.post(f"/api/v1/sessions/{session_id}/card/disagree").json()["card"]
    response = client.get("/api/v1/review/items")
    assert response.status_code == 200, response.text
    listing = response.json()

    Draft202012Validator(json.loads(SPEC_PATH.read_text(encoding="utf-8"))).validate(listing)
    assert listing["version"] == "0.1"
    assert len(listing["items"]) == 1

    item = listing["items"][0]
    assert item == {
        "session_id": session_id,
        "problem_id": body["problem_id"],
        "layer": card["layer"],
        "label": card["label"],
        "node_id": card["node_id"],
        "one_line": card["one_line"],
        "confidence": card["confidence"],
        "created_at": item["created_at"],
    }
    # The queue is a card summary, not a transcript.
    assert set(item) == {
        "session_id",
        "problem_id",
        "layer",
        "label",
        "node_id",
        "one_line",
        "confidence",
        "created_at",
    }
    assert work not in response.text

    # Listing is read-only: asking twice does not append a second row.
    again = client.get("/api/v1/review/items").json()
    assert again["items"] == listing["items"]


def test_queue_lists_the_newest_disagreement_first(tmp_path: Path) -> None:
    queue = SqliteReviewQueue(tmp_path / "review.sqlite3")
    queue.record(
        ReviewItem(
            session_id="S_OLD0000000001",
            problem_id="P_PUB_002",
            layer="L2",
            label="概念不清：恒成立与最值",
            node_id="n3",
            one_line="漏掉了 a≤0 这一支。",
            confidence=0.86,
            created_at="2026-10-30T08:00:00+00:00",
        )
    )
    queue.record(
        ReviewItem(
            session_id="S_NEW0000000002",
            problem_id="P_PUB_003",
            layer="L1",
            label="概念不清：没有抓住关键条件",
            node_id="n2",
            one_line="只讨论了 a>0。",
            confidence=0.74,
            created_at="2026-10-31T08:00:00+00:00",
        )
    )

    assert [item.session_id for item in queue.items()] == [
        "S_NEW0000000002",
        "S_OLD0000000001",
    ]
