"""Ports for throttling the read-only single-step verifier.

The step endpoint is deliberately cheap in state changes but not necessarily
cheap in CPU: math may run SymPy and physics may evaluate a whitelisted AST.
This port keeps the use case independent of the storage mechanism. The
composition root decides whether a limiter exists; ``None`` in
``SessionService`` means "no throttling" (unit tests and embedded callers).
"""

from __future__ import annotations

from typing import Protocol


class StepRateLimiter(Protocol):
    """A per-session token bucket, keyed by the session id."""

    def consume(self, key: str) -> float | None:
        """Consume one token.

        Returns ``None`` when the call is allowed, otherwise the number of
        seconds a caller should wait before retrying.
        """

        ...


class StepRateLimited(Exception):
    """The caller exceeded the step-verification budget."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(0.0, retry_after)
        super().__init__(
            f"step verification rate limit exceeded; retry after {self.retry_after:.1f}s"
        )
