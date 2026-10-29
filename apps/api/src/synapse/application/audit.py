"""Audit records for every model call and every degradation decision.

Chapter 12 §12.7 fixes the field list; ``kind`` is the only addition, so one
JSONL sink can hold calls, fallbacks and shadow diffs without a second file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

AuditKind = Literal["llm_call", "fallback", "shadow"]


@dataclass(frozen=True, slots=True)
class AuditEntry:
    kind: AuditKind
    session_id: str = ""
    turn: int = 0
    model: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retried: bool = False
    fallback_reason: str | None = None
    schema_ok: bool = False
    probe_id: str = ""
    baseline: str = ""
    candidate: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class CallAuditor(Protocol):
    def record(self, entry: AuditEntry) -> None: ...