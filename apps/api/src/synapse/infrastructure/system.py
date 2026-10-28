"""System clock and session id adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidSessionIdGenerator:
    def new_session_id(self) -> str:
        return "S_" + uuid4().hex[:12].upper()
