"""Equality-chain findings leave the island (M2.5 S5 ⑥ wiring).

The checker itself is covered by ``test_equalities.py``; this module covers the
*product* wiring: the port adapter, the off-by-default feature flag, and the
fact that a session keeps the finding until the card is built.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.verification.equalities import SympyEqualityChecker

REAL_LIMIT_WORK = "=lim[sinX/(X+sinX/cosX)] =lim[sinX/X +cosX] =1+1 =2，有哪里错了么"
SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "step-verification.schema.json"


def test_the_port_adapter_returns_the_limit_summary() -> None:
    findings = SympyEqualityChecker().findings(REAL_LIMIT_WORK)

    assert len(findings) == 1
    assert findings[0].summary == "x→0 时左边极限 0.5、右边 2"


def test_the_flag_defaults_off_and_rejects_a_typo() -> None:
    assert FeatureFlags.from_env({}).equality_check is False
    assert FeatureFlags.from_env({"SYNAPSE_EQUALITY_CHECK": "on"}).equality_check is True
    assert FeatureFlags.from_env({"SYNAPSE_EQUALITY_CHECK": "off"}).equality_check is False
    with pytest.raises(ValueError):
        FeatureFlags.from_env({"SYNAPSE_EQUALITY_CHECK": "onn"})


def test_flag_off_keeps_the_session_on_the_baseline_path() -> None:
    container = build_container(features=FeatureFlags(equality_check=False))

    view = container.service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work="定义域 x>0。x+1=2x",
        )
    )

    assert view.session.work_findings == ()


def test_flag_on_stores_the_finding_on_the_session() -> None:
    container = build_container(features=FeatureFlags(equality_check=True))

    view = container.service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work="定义域 x>0。x+1=2x",
        )
    )

    assert len(view.session.work_findings) == 1
    finding = view.session.work_findings[0]
    assert finding.kind == "identity"
    assert (finding.left, finding.right) == ("x+1", "2*x")


def test_flag_on_reaches_the_diagnosis_card() -> None:
    container = build_container(features=FeatureFlags(equality_check=True))
    view = container.service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work="定义域 x>0。x+1=2x",
        )
    )
    session_id = view.session.session_id

    for _ in range(view.session.max_turns):
        if view.prompt is None:
            break
        view = container.service.submit(
            session_id,
            SubmitAnswerCommand(answer="A", option_id="A"),
        )
        if view.diagnosis is not None:
            break

    card = view.diagnosis
    assert card is not None
    assert "等号不成立" in card.one_line
    assert any("等式：x+1 = 2*x" in line for line in card.evidence)
    assert len(card.one_line) <= 200


def test_flag_on_does_not_flag_a_correct_limit_chain() -> None:
    checked = SympyEqualityChecker().findings("=lim[sinX/(X+tanX)] =lim[1/(1+1/cosX)] =1/2")

    assert checked == ()


def _start(session_client: TestClient, sample_payload: dict[str, object]) -> str:
    response = session_client.post("/api/v1/sessions", json=sample_payload)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_step_endpoint_is_off_by_default(
    client: TestClient, sample_payload: dict[str, object]
) -> None:
    session_id = _start(client, sample_payload)

    response = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == "0.2"
    assert body["status"] == "unknown"
    assert body["findings"] == []
    assert "未启用" in body["detail"]


def test_step_verification_writes_a_privacy_safe_audit_row(
    sample_payload: dict[str, object],
) -> None:
    auditor = InMemoryCallAuditor()
    on_client = TestClient(
        create_app(
            build_container(
                features=FeatureFlags(equality_check=True),
                auditor=auditor,
            )
        )
    )
    session_id = _start(on_client, sample_payload)

    assert (
        on_client.post(
            f"/api/v1/sessions/{session_id}/steps",
            json={"text": "x+1=2x", "node_id": "n3"},
        ).status_code
        == 200
    )
    assert (
        on_client.post(
            f"/api/v1/sessions/{session_id}/steps",
            json={"text": "x+1=1+x"},
        ).status_code
        == 200
    )

    rows = [entry for entry in auditor.entries if entry.kind == "step_verify"]
    assert len(rows) == 2
    fail, unknown = rows
    assert fail.session_id == session_id
    assert fail.turn == 0
    assert fail.subject == "math"
    assert fail.verification_status == "fail"
    assert fail.finding_count == 1
    assert fail.step_chars == len("x+1=2x")
    assert fail.latency_ms >= 0
    assert unknown.verification_status == "unknown"
    assert unknown.finding_count == 0
    # The audit records volume and outcome, not the student's wording.
    assert "x+1=2x" not in str(fail.as_dict())
    assert "x+1=1+x" not in str(unknown.as_dict())


def test_step_endpoint_returns_a_counterexample_with_the_flag_on(
    sample_payload: dict[str, object],
) -> None:
    on_client = TestClient(create_app(build_container(features=FeatureFlags(equality_check=True))))
    session_id = _start(on_client, sample_payload)
    before = on_client.get(f"/api/v1/sessions/{session_id}").json()
    assert before["subject"] == "math"

    response = on_client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x", "node_id": "n3"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "fail"
    assert body["findings"] == [
        {
            "kind": "identity",
            "left": "x+1",
            "right": "2*x",
            "summary": "x=0.1 时左边 1.1、右边 0.2",
            "counterexample": "x=0.1 时左边 1.1、右边 0.2",
        }
    ]
    assert "x+1 = 2*x" in body["detail"]
    assert "x=0.1 时左边 1.1、右边 0.2" in body["detail"]
    assert "solution" not in str(body)

    # Read-only: asking about a step must not advance the dialogue or build a
    # card. Otherwise a probe answer could be smuggled past the state machine.
    after = on_client.get(f"/api/v1/sessions/{session_id}").json()
    assert after["state"] == before["state"]
    assert after["turn"] == before["turn"]
    assert after["diagnosis"] is None


def test_step_endpoint_does_not_call_an_unreadable_chain_correct(
    sample_payload: dict[str, object],
) -> None:
    on_client = TestClient(create_app(build_container(features=FeatureFlags(equality_check=True))))
    session_id = _start(on_client, sample_payload)

    response = on_client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=1+x"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unknown"
    assert body["findings"] == []
    assert "不等于这一步正确" in body["detail"]


def test_step_endpoint_surfaces_the_limit_chain_counterexample(
    sample_payload: dict[str, object],
) -> None:
    on_client = TestClient(create_app(build_container(features=FeatureFlags(equality_check=True))))
    session_id = _start(on_client, sample_payload)

    response = on_client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": REAL_LIMIT_WORK},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "fail"
    assert body["findings"][0]["kind"] == "limit"
    assert body["findings"][0]["summary"] == "x→0 时左边极限 0.5、右边 2"
    assert "x→0 时左边极限 0.5、右边 2" in body["detail"]


def test_step_endpoint_is_404_for_an_unknown_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions/S_DOES_NOT_EXIST/steps",
        json={"text": "x+1=2x"},
    )

    assert response.status_code == 404


def test_step_verdict_conforms_to_the_public_schema(
    sample_payload: dict[str, object],
) -> None:
    on_client = TestClient(create_app(build_container(features=FeatureFlags(equality_check=True))))
    session_id = _start(on_client, sample_payload)

    body = on_client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x"},
    ).json()

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(spec)
    validator.validate(body)

    unknown = on_client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=1+x"},
    ).json()
    assert unknown["status"] == "unknown"
    validator.validate(unknown)
