"""Per-session throttle for the read-only step verifier."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.rate_limit import TokenBucketStepLimiter


def _start(client: TestClient, payload: dict[str, object]) -> str:
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def test_token_bucket_allows_a_burst_then_refills() -> None:
    now = [100.0]
    limiter = TokenBucketStepLimiter(
        capacity=2,
        window_seconds=10.0,
        clock=lambda: now[0],
    )

    assert limiter.consume("S_A") is None
    assert limiter.consume("S_A") is None
    assert limiter.consume("S_A") == pytest.approx(5.0)

    now[0] += 2.0
    assert limiter.consume("S_A") == pytest.approx(3.0)

    now[0] += 3.0
    assert limiter.consume("S_A") is None

    # The bucket is per session; a different key has its own burst.
    assert limiter.consume("S_B") is None


def test_token_bucket_rejects_bad_configuration_and_throttles_after_one_token() -> None:
    with pytest.raises(ValueError):
        TokenBucketStepLimiter(capacity=0)
    with pytest.raises(ValueError):
        TokenBucketStepLimiter(window_seconds=0)

    limiter = TokenBucketStepLimiter(capacity=1, window_seconds=60.0)
    assert limiter.consume("S_A") is None
    assert limiter.consume("S_A") is not None


def test_step_endpoint_returns_429_without_calling_the_verifier(
    sample_payload: dict[str, object],
) -> None:
    now = [100.0]
    auditor = InMemoryCallAuditor()
    limiter = TokenBucketStepLimiter(
        capacity=1,
        window_seconds=30.0,
        clock=lambda: now[0],
    )
    client = TestClient(
        create_app(
            build_container(
                features=FeatureFlags(equality_check=True),
                auditor=auditor,
                step_limiter=limiter,
            )
        )
    )
    session_id = _start(client, sample_payload)

    first = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x"},
    )
    assert first.status_code == 200, first.text

    limited = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x"},
    )
    assert limited.status_code == 429, limited.text
    assert limited.headers["Retry-After"] == "30"
    assert "太频繁" in limited.json()["detail"]

    # A 429 is not a verdict, so it must not enter the step audit.
    step_rows = [entry for entry in auditor.entries if entry.kind == "step_verify"]
    assert len(step_rows) == 1

    now[0] += 30.0
    refilled = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"text": "x+1=2x"},
    )
    assert refilled.status_code == 200, refilled.text

    # Another session is not punished for this session's burst.
    other_session = _start(client, sample_payload)
    assert (
        client.post(
            f"/api/v1/sessions/{other_session}/steps",
            json={"text": "x+1=2x"},
        ).status_code
        == 200
    )


def test_default_container_limits_a_single_session(
    sample_payload: dict[str, object],
) -> None:
    # Equality checking is off, so each allowed call returns immediately; this
    # test is about the composition root's default limiter, not SymPy.
    client = TestClient(
        create_app(
            build_container(
                features=FeatureFlags(equality_check=False),
                auditor=InMemoryCallAuditor(),
            )
        )
    )
    session_id = _start(client, sample_payload)

    statuses = [
        client.post(
            f"/api/v1/sessions/{session_id}/steps",
            json={"text": "x+1=2x"},
        ).status_code
        for _ in range(31)
    ]

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429
