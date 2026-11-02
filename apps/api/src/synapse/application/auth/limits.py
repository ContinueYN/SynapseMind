"""Process-local brute-force throttling for login and registration.

Both account endpoints run Argon2id or create accounts, so they are the only
untrusted endpoints worth a failure counter. The limiter is deliberately not a
storage adapter: it keeps fixed windows in this process and loses them on
restart. Docker runs one API process behind nginx, so there is no shared
counter to synchronise; a multi-replica deployment would need a Redis (or
equivalent) implementation of :class:`AuthFailureLimiter` instead.

Two buckets are checked together:

* every failed attempt counts against the client IP (default 10 / 300 s);
* the same failure also counts against ``(client IP, normalized email)``
  (default 5 / 300 s), which stops one address from rotating accounts.

A request is counted only *after* the attempt failed, and the route checks the
buckets before calling the use case, so a throttled request never spends KDF
CPU. A successful login/register clears the ``(IP, email)`` bucket for that
account. The coarse IP bucket is intentionally kept: one valid login must not
wipe failures other accounts on the same address produced.

The counters are guarded by a lock because FastAPI runs these sync routes in a
threadpool. Stale windows are dropped lazily, and the maps are capped so a
stream of unique keys cannot grow memory without bound.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, TypeVar

from synapse.application.auth.service import normalize_email

# Defaults documented in apps/api/README.md and infra/.env.example.
DEFAULT_MAX_FAILURES_PER_IP = 10
DEFAULT_MAX_FAILURES_PER_EMAIL = 5
DEFAULT_FAILURE_WINDOW_S = 300

# A generous ceiling: the common path never reaches it, but a flood of unique
# IPs/emails cannot make the process retain windows forever.
_MAX_KEYS_PER_TABLE = 4096

_Key = TypeVar("_Key")


class AuthFailureLimiter(Protocol):
    """The two-bucket failure counter the account routes consult."""

    def check(self, *, client_ip: str, email: str) -> float | None:
        """Return ``None`` when allowed, else seconds to wait before retrying."""

        ...

    def record_failure(self, *, client_ip: str, email: str) -> None:
        """Count one failed attempt in both buckets."""

        ...

    def clear(self, *, client_ip: str, email: str) -> None:
        """Forget the ``(IP, email)`` failures after a successful attempt."""

        ...


@dataclass(slots=True)
class _Window:
    started_at: float
    failures: int


class FixedWindowAuthFailureLimiter:
    """A fixed-window counter with an injectable monotonic clock.

    The window starts at the first failure and does not slide; after
    ``window_s`` the bucket is treated as empty again. Fixed windows can allow a
    short burst across a boundary, which is acceptable for a brute-force guard
    whose purpose is to make guessing expensive, not to smooth traffic.
    """

    def __init__(
        self,
        *,
        max_failures_per_ip: int = DEFAULT_MAX_FAILURES_PER_IP,
        max_failures_per_email: int = DEFAULT_MAX_FAILURES_PER_EMAIL,
        window_s: float = DEFAULT_FAILURE_WINDOW_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_failures_per_ip < 1:
            raise ValueError("max_failures_per_ip must be a positive integer")
        if max_failures_per_email < 1:
            raise ValueError("max_failures_per_email must be a positive integer")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._max_per_ip = max_failures_per_ip
        self._max_per_email = max_failures_per_email
        self._window_s = float(window_s)
        self._clock = clock
        self._by_ip: dict[str, _Window] = {}
        self._by_email: dict[tuple[str, str], _Window] = {}
        self._lock = threading.Lock()

    def check(self, *, client_ip: str, email: str) -> float | None:
        now = self._clock()
        email_key = (client_ip, normalize_email(email))
        with self._lock:
            ip_retry = self._retry_after(self._by_ip.get(client_ip), now, self._max_per_ip)
            email_retry = self._retry_after(
                self._by_email.get(email_key),
                now,
                self._max_per_email,
            )
        retry: float | None = None
        for candidate in (ip_retry, email_retry):
            if candidate is not None and (retry is None or candidate > retry):
                retry = candidate
        return retry

    def record_failure(self, *, client_ip: str, email: str) -> None:
        now = self._clock()
        email_key = (client_ip, normalize_email(email))
        with self._lock:
            self._bump(self._by_ip, client_ip, now)
            self._bump(self._by_email, email_key, now)

    def clear(self, *, client_ip: str, email: str) -> None:
        # Only the account key is cleared; see the module docstring for why the
        # coarse IP counter deliberately keeps running.
        with self._lock:
            self._by_email.pop((client_ip, normalize_email(email)), None)

    def _retry_after(self, window: _Window | None, now: float, limit: int) -> float | None:
        if window is None or window.failures < limit:
            return None
        remaining = self._window_s - (now - window.started_at)
        # An expired window is equivalent to no window at all.
        return remaining if remaining > 0 else None

    def _bump(self, table: dict[_Key, _Window], key: _Key, now: float) -> None:
        window = table.get(key)
        if window is None or self._expired(window, now):
            if len(table) >= _MAX_KEYS_PER_TABLE:
                self._shrink(table, now)
            window = _Window(started_at=now, failures=0)
            table[key] = window
        window.failures += 1

    def _expired(self, window: _Window, now: float) -> bool:
        return now - window.started_at >= self._window_s

    def _shrink(self, table: dict[_Key, _Window], now: float) -> None:
        for key in [key for key, window in table.items() if self._expired(window, now)]:
            del table[key]
        # Still full after dropping expired windows: evict the oldest insertion.
        # This is best-effort memory protection, not part of the guarantee.
        while len(table) >= _MAX_KEYS_PER_TABLE:
            del table[next(iter(table))]
