"""T6: shadow mode replays every golden without changing a single outcome.

The stub client rewrites the question deterministically, so this test proves
the plumbing (dual run + diff recording + untouched result), not model quality.
Real comparisons run against DeepSeek with ``SYNAPSE_LLM_MODE=shadow``.
"""

from __future__ import annotations

import json
from pathlib import Path

from synapse.api.deps import build_container
from synapse.application.llm import LLMRequest, LLMResponse
from synapse.application.replay import load_cases, replay_case
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.llm.settings import LLMSettings

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden" / "golden-v0.1.jsonl"

SHADOW = LLMSettings(
    mode="shadow",
    api_key="sk-stub",
    max_attempts=1,
    audit_path="var/audit/unused.jsonl",
)

MARKER = "要改写的问题："


class StubClient:
    """Prefixes the original question, keeping exactly one question mark."""

    def __init__(self, prefix: str = "换个问法：") -> None:
        self._prefix = prefix

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        original = request.user.split(MARKER, 1)[1].splitlines()[0]
        return LLMResponse(
            text=json.dumps({"question": f"{self._prefix}{original}"}, ensure_ascii=False),
            model="stub-1",
            latency_ms=1,
        )


class BrokenJSONClient:
    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del request, timeout_s
        return LLMResponse(text="not json", model="stub-1")


def _replay(settings: LLMSettings | None, auditor: InMemoryCallAuditor | None) -> list:
    container = build_container(settings, llm_client=StubClient(), auditor=auditor)
    return [replay_case(container.service, case) for case in load_cases(GOLDEN_PATH)]


def test_shadow_produces_a_diff_report_for_all_cases() -> None:
    auditor = InMemoryCallAuditor()
    results = _replay(SHADOW, auditor)

    assert len(results) == 10
    shadow_entries = [entry for entry in auditor.entries if entry.kind == "shadow"]
    assert len(shadow_entries) >= 10, "every composed question should be compared"
    assert all(entry.baseline for entry in shadow_entries)
    assert all(entry.candidate.startswith("换个问法：") for entry in shadow_entries)
    assert all(entry.fallback_reason == "differs" for entry in shadow_entries)


def test_shadow_does_not_change_outcomes() -> None:
    def fingerprint(results: list) -> list[tuple[str, tuple[str, ...], int]]:
        return [(r.outcome, tuple(row.top1 for row in r.turns), r.last_turn) for r in results]

    assert fingerprint(_replay(SHADOW, InMemoryCallAuditor())) == fingerprint(_replay(None, None))


def test_shadow_failure_is_recorded_not_raised() -> None:
    auditor = InMemoryCallAuditor()
    container = build_container(SHADOW, llm_client=BrokenJSONClient(), auditor=auditor)
    case = load_cases(GOLDEN_PATH)[0]

    result = replay_case(container.service, case)

    assert result.outcome in {"diagnose", "stop", "no_gap"}
    assert any(entry.fallback_reason == "schema_invalid" for entry in auditor.entries)
    assert any(entry.kind == "shadow" and entry.candidate == "" for entry in auditor.entries)
