"""Audit records for every model call and every degradation decision.

Chapter 12 §12.7 fixes the model-call field list. The same JSONL sink also
carries ``graph_build`` and ``step_verify`` rows: the former reuses
``verification_status``/``graph_fingerprint``, the latter adds the
step-verification metadata at the end of this dataclass (never the text).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

AuditKind = Literal["llm_call", "fallback", "shadow", "graph_build", "step_verify"]


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
    graph_fingerprint: str = ""
    # M2.5 S5: "pass" | "fail" | "unknown" for the graph's claim or a single
    # submitted step; "" when the call produced no graph / no verdict.
    verification_status: str = ""
    # Step verification only. The student's text is deliberately not copied
    # into the audit: operators need volume, latency and outcome, not content.
    subject: str = ""
    finding_count: int = 0
    step_chars: int = 0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class CallAuditor(Protocol):
    def record(self, entry: AuditEntry) -> None: ...
