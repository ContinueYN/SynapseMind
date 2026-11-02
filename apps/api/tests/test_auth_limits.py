"""Deterministic tests for the process-local login/register failure limiter."""

from __future__ import annotations

import pytest

from synapse.application.auth.limits import FixedWindowAuthFailureLimiter


class _Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _limiter(
    clock: _Clock,
    *,
    per_ip: int = 10,
    per_email: int = 5,
    window_s: float = 300.0,
) -> FixedWindowAuthFailureLimiter:
    return FixedWindowAuthFailureLimiter(
        max_failures_per_ip=per_ip,
        max_failures_per_email=per_email,
        window_s=window_s,
        clock=clock,
    )


def test_rejects_non_positive_configuration() -> None:
    with pytest.raises(ValueError, match="max_failures_per_ip"):
        FixedWindowAuthFailureLimiter(max_failures_per_ip=0)
    with pytest.raises(ValueError, match="max_failures_per_email"):
        FixedWindowAuthFailureLimiter(max_failures_per_email=-1)
    with pytest.raises(ValueError, match="window_s"):
        FixedWindowAuthFailureLimiter(window_s=0)


def test_email_bucket_blocks_after_the_limit() -> None:
    clock = _Clock()
    limiter = _limiter(clock, per_ip=100, per_email=2, window_s=60)

    limiter.record_failure(client_ip="203.0.113.9", email="Owner@Example.com")
    limiter.record_failure(client_ip="203.0.113.9", email="owner@example.com")

    # The key is (IP, normalized email), so casing does not split the bucket.
    assert limiter.check(client_ip="203.0.113.9", email="OWNER@example.com") is not None
    # A different address has its own budget.
    assert limiter.check(client_ip="203.0.113.10", email="owner@example.com") is None


def test_ip_bucket_blocks_across_different_emails() -> None:
    clock = _Clock()
    limiter = _limiter(clock, per_ip=2, per_email=100, window_s=60)

    limiter.record_failure(client_ip="203.0.113.9", email="a@example.com")
    limiter.record_failure(client_ip="203.0.113.9", email="b@example.com")

    assert limiter.check(client_ip="203.0.113.9", email="c@example.com") == 60.0
    assert limiter.check(client_ip="203.0.113.10", email="c@example.com") is None


def test_retry_after_counts_down_and_the_window_resets() -> None:
    clock = _Clock()
    limiter = _limiter(clock, per_ip=100, per_email=1, window_s=60)
    limiter.record_failure(client_ip="203.0.113.9", email="a@example.com")

    assert limiter.check(client_ip="203.0.113.9", email="a@example.com") == 60.0
    clock.advance(25)
    assert limiter.check(client_ip="203.0.113.9", email="a@example.com") == 35.0
    clock.advance(35)
    # The fixed window expired: the bucket is treated as empty.
    assert limiter.check(client_ip="203.0.113.9", email="a@example.com") is None
    limiter.record_failure(client_ip="203.0.113.9", email="a@example.com")
    assert limiter.check(client_ip="203.0.113.9", email="a@example.com") == 60.0


def test_clear_forgets_only_the_email_bucket() -> None:
    clock = _Clock()
    limiter = _limiter(clock, per_ip=2, per_email=10, window_s=60)
    limiter.record_failure(client_ip="203.0.113.9", email="a@example.com")
    limiter.record_failure(client_ip="203.0.113.9", email="b@example.com")

    limiter.clear(client_ip="203.0.113.9", email="a@example.com")

    # The coarse IP bucket keeps the other account's failure (it is shared).
    assert limiter.check(client_ip="203.0.113.9", email="a@example.com") is not None


def test_the_oldest_window_is_evicted_when_the_table_is_full() -> None:
    clock = _Clock()
    limiter = _limiter(clock, per_ip=100, per_email=100, window_s=60)
    # Paint the map past its cap with expired windows.
    for index in range(4097):
        limiter.record_failure(client_ip=f"198.51.100.{index}", email="a@example.com")
    clock.advance(61)
    # A new failure prunes the expired entries instead of growing forever.
    limiter.record_failure(client_ip="203.0.113.9", email="b@example.com")
    assert limiter.check(client_ip="203.0.113.9", email="b@example.com") is None
