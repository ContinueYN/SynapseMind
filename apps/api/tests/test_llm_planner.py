"""The planner adapter validates, audits and never invents a tool.

The runner-level tests in ``test_agent_trace.py`` cover fallback wiring. These
tests pin the adapter contract: one JSON object, a whitelisted tool or ``null``,
and a loud failure (with an audit row) for anything else.
"""

from __future__ import annotations

import pytest

from synapse.application.diagnosis.agent_planner import (
    AgentPlanningTool,
    PlannerContext,
    PlannerRejected,
)
from synapse.application.shared.audit import AuditEntry
from synapse.application.shared.llm import (
    LLMCallFailed,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.infrastructure.llm.agent_planner import (
    LLMToolPlanner,
    build_request,
    parse_choice,
)
from synapse.infrastructure.llm.settings import LLMSettings

SETTINGS = LLMSettings(mode="on", api_key="test", agent_planner=True)
TOOLS: tuple[AgentPlanningTool, ...] = ("search_sources", "search_patterns")


def _context() -> PlannerContext:
    return PlannerContext(
        domain="research",
        label="科研",
        verification="argumentative",
        framework="argumentative",
        observed=("目标", "证据"),
        gaps=("没看到推理：从证据到结论之间那一步。",),
        tools=TOOLS,
        decision=False,
    )


class _Client:
    def __init__(
        self,
        text: str = "",
        *,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMResponse(text=self.text, model="fake", latency_ms=3)


class _Auditor:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_parse_choice_accepts_a_whitelisted_tool() -> None:
    assert parse_choice('{"tool": "search_patterns"}', TOOLS) == "search_patterns"
    assert parse_choice('{"tool": " SEARCH_SOURCES "}', TOOLS) == "search_sources"


def test_parse_choice_accepts_an_explicit_null() -> None:
    assert parse_choice('{"tool": null}', TOOLS) is None


@pytest.mark.parametrize(
    "text",
    (
        "not json",
        "[]",
        '{"tool": 3}',
    ),
)
def test_parse_choice_rejects_bad_json(text: str) -> None:
    with pytest.raises(PlannerRejected) as caught:
        parse_choice(text, TOOLS)
    assert caught.value.reason == "bad_json"


@pytest.mark.parametrize("tool", ("run_code", "get_answer", "set_state", "search_patterns"))
def test_parse_choice_rejects_tools_outside_the_offered_list(tool: str) -> None:
    offered: tuple[AgentPlanningTool, ...] = (
        ("search_sources",) if tool == "search_patterns" else TOOLS
    )
    with pytest.raises(PlannerRejected) as caught:
        parse_choice(f'{{"tool": "{tool}"}}', offered)
    assert caught.value.reason == "tool_not_allowed"


def test_request_carries_only_system_labels() -> None:
    request = build_request(_context())

    assert request.purpose == "agent_plan"
    assert "search_sources" in request.user
    assert "SECRET_ATTEMPT" not in request.user


def test_repeated_identical_contexts_are_replayed_without_a_second_call() -> None:
    client = _Client('{"tool": "search_sources"}')
    auditor = _Auditor()
    planner = LLMToolPlanner(client, settings=SETTINGS, auditor=auditor)

    first = planner.choose(_context())
    second = planner.choose(_context())

    assert first == second == "search_sources"
    assert len(client.requests) == 1
    assert len(auditor.entries) == 1


def test_timeout_is_not_cached_as_a_choice() -> None:
    client = _Client(error=LLMTimeout("slow"))
    planner = LLMToolPlanner(client, settings=SETTINGS)

    for _ in range(2):
        with pytest.raises(PlannerRejected):
            planner.choose(_context())

    assert len(client.requests) == 2


def test_valid_choice_is_returned_and_audited() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(
        _Client('{"tool": "search_sources", "reason": "需要来源"}'),
        settings=SETTINGS,
        auditor=auditor,
    )

    assert planner.choose(_context()) == "search_sources"
    assert len(auditor.entries) == 1
    entry = auditor.entries[0]
    assert entry.kind == "agent_plan"
    assert entry.schema_ok is True
    assert entry.agent_tool == "search_sources"
    assert entry.fallback_reason is None


def test_null_choice_is_a_fallback_not_a_tool() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(_Client('{"tool": null}'), settings=SETTINGS, auditor=auditor)

    assert planner.choose(_context()) is None
    assert auditor.entries[0].fallback_reason == "no_choice"
    assert auditor.entries[0].agent_tool == ""


def test_timeout_is_rejected_and_audited() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(
        _Client(error=LLMTimeout("slow")),
        settings=SETTINGS,
        auditor=auditor,
    )

    with pytest.raises(PlannerRejected) as caught:
        planner.choose(_context())
    assert caught.value.reason == "timeout"
    assert auditor.entries[0].fallback_reason == "timeout"
    assert auditor.entries[0].schema_ok is False


def test_transport_failure_is_rejected_and_audited() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(
        _Client(error=LLMCallFailed("down")),
        settings=SETTINGS,
        auditor=auditor,
    )

    with pytest.raises(PlannerRejected) as caught:
        planner.choose(_context())
    assert caught.value.reason == "transport"
    assert auditor.entries[0].fallback_reason == "transport"


def test_bad_json_is_rejected_and_audited() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(_Client("not json"), settings=SETTINGS, auditor=auditor)

    with pytest.raises(PlannerRejected) as caught:
        planner.choose(_context())
    assert caught.value.reason == "bad_json"
    assert auditor.entries[0].fallback_reason == "bad_json"
    assert auditor.entries[0].schema_ok is False


def test_illegal_tool_is_rejected_and_audited() -> None:
    auditor = _Auditor()
    planner = LLMToolPlanner(
        _Client('{"tool": "run_code"}'),
        settings=SETTINGS,
        auditor=auditor,
    )

    with pytest.raises(PlannerRejected) as caught:
        planner.choose(_context())
    assert caught.value.reason == "tool_not_allowed"
    assert auditor.entries[0].fallback_reason == "tool_not_allowed"
    assert auditor.entries[0].agent_tool == ""


def test_planner_requires_a_live_model_path() -> None:
    planner = LLMToolPlanner(
        _Client('{"tool": "search_sources"}'),
        settings=LLMSettings(mode="off", api_key="test", agent_planner=True),
    )

    with pytest.raises(PlannerRejected) as caught:
        planner.choose(_context())
    assert caught.value.reason == "unavailable"


def test_planner_settings_default_off_and_parse_strictly() -> None:
    default = LLMSettings.from_env({})
    assert default.agent_planner is False
    assert default.agent_planner_prompt_version == "agent-plan-v1"
    assert default.agent_planner_timeout_s == 2.0

    enabled = LLMSettings.from_env(
        {
            "SYNAPSE_AGENT_PLANNER": "on",
            "SYNAPSE_AGENT_PLANNER_TIMEOUT_S": "1.5",
        }
    )
    assert enabled.agent_planner is True
    assert enabled.agent_planner_timeout_s == 1.5

    with pytest.raises(ValueError):
        LLMSettings.from_env({"SYNAPSE_AGENT_PLANNER": "maybe"})
    with pytest.raises(ValueError):
        LLMSettings.from_env({"SYNAPSE_AGENT_PLANNER_TIMEOUT_S": "30"})
