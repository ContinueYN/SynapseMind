"""In-process token bucket for the single-step verifier.

The API has no Redis and no authentication (see ``AGENTS.md``), so this guard
is intentionally small and process-local: it stops one session from hammering
SymPy/AST verification, and it resets whenever the process restarts. It is not
an edge rate limit and does not defend against many sessions created by the
same client; that belongs to a real deployment layer.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

DEFAULT_CAPACITY = 30
DEFAULT_WINDOW_SECONDS = 60.0


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketStepLimiter:
    """Per-session token bucket with a burst and a steady refill rate."""

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._capacity = float(capacity)
        self._window = float(window_seconds)
        self._rate = self._capacity / self._window
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def consume(self, key: str) -> float | None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._capacity, updated_at=now)
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    self._capacity,
                    bucket.tokens + elapsed * self._rate,
                )
                bucket.updated_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                self._buckets[key] = bucket
                return None

            self._buckets[key] = bucket
            return (1.0 - bucket.tokens) / self._rate

    def _prune(self, now: float) -> None:
        # Keep the common path allocation-free; only sweep once the map is
        # large enough that stale one-off sessions start to matter.
        if len(self._buckets) < 1024:
            return
        cutoff = now - self._window * 2.0
        stale = [key for key, bucket in self._buckets.items() if bucket.updated_at < cutoff]
        for key in stale:
            del self._buckets[key]
