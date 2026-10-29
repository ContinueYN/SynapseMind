"""T3/T4/T6: the composer chain — rewrite, retry, fallback, shadow, canary."""

from __future__ import annotations

import pytest

from synapse.application.composer import (
    CanaryProbeComposer,
    CompositionFailed,
    FallbackProbeComposer,
    GraphProbeComposer,
    LeakSafeProbeComposer,
)
from synapse.application.llm import LLMRequest, LLMResponse, LLMTimeout
from synapse.application.trace import tracing
from synapse.domain.guard.leak import AnswerLeakGuard
from synapse.infrastructure.guards import AnswerStoreLeakGuardFactory
from synapse.infrastructure.in_memory import InMemoryAnswerStore
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.llm.composer import LLMProbeComposer
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM

PROBE = SAMPLE_PROBLEM.graph.probe("p_a0_derivative")
VALID = '{"question": "如果 a 等于 0，导数还会出现零点吗？"}'
INVALID = '{"question": "一个问号？两个问号？"}'


class FakeClient:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        self.calls.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(
            text=reply,
            model="fake-1",
            latency_ms=42,
            prompt_tokens=10,
            completion_tokens=4,
        )


def _settings(**overrides: object) -> LLMSettings:
    values: dict[str, object] = {
        "mode": "on",
        "api_key": "sk-test",
        "max_attempts": 2,
    }
    values.update(overrides)
    return LLMSettings(**values)  # type: ignore[arg-type]


def _composer(client: FakeClient, auditor: InMemoryCallAuditor | None = None) -> LLMProbeComposer:
    return LLMProbeComposer(client, settings=_settings(), auditor=auditor)


def test_rewrite_keeps_options_and_derives_action() -> None:
    auditor = InMemoryCallAuditor()
    prompt = _composer(FakeClient(VALID), auditor).compose(SAMPLE_PROBLEM, PROBE, confidence=0.62)

    assert prompt.question == "如果 a 等于 0，导数还会出现零点吗？"
    assert prompt.options == PROBE.options
    assert prompt.action == "ask"
    assert prompt.hint_level == 0
    assert prompt.reason_code == "DISCRIMINATE_HYPOTHESIS"
    assert prompt.confidence == 0.62

    (entry,) = auditor.entries
    assert entry.kind == "llm_call"
    assert entry.schema_ok is True
    assert entry.model == "fake-1"
    assert entry.latency_ms == 42
    assert entry.prompt_tokens == 10
    assert entry.probe_id == PROBE.id


def test_hint_level_becomes_a_hint() -> None:
    prompt = _composer(FakeClient(VALID)).compose(
        SAMPLE_PROBLEM, PROBE, confidence=0.5, hint_level=2
    )
    assert prompt.action == "hint"
    assert prompt.hint_level == 2


def test_schema_failure_is_retried_once_then_gives_up() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(INVALID, INVALID)
    with pytest.raises(CompositionFailed) as caught:
        _composer(client, auditor).compose(SAMPLE_PROBLEM, PROBE, confidence=0.5)

    assert caught.value.reason == "schema_invalid"
    assert len(client.calls) == 2
    first, second = auditor.entries
    assert first.schema_ok is False and first.retried is False
    assert second.schema_ok is False and second.retried is True
    assert second.fallback_reason == "question_marks"


def test_retry_can_succeed() -> None:
    auditor = InMemoryCallAuditor()
    prompt = _composer(FakeClient(INVALID, VALID), auditor).compose(
        SAMPLE_PROBLEM, PROBE, confidence=0.5
    )
    assert prompt.question == "如果 a 等于 0，导数还会出现零点吗？"
    assert [entry.retried for entry in auditor.entries] == [False, True]


def test_timeout_is_not_retried() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(LLMTimeout("slow"))
    with pytest.raises(CompositionFailed) as caught:
        _composer(client, auditor).compose(SAMPLE_PROBLEM, PROBE, confidence=0.5)

    assert caught.value.reason == "timeout"
    assert len(client.calls) == 1
    (entry,) = auditor.entries
    assert entry.fallback_reason == "timeout"
    assert entry.schema_ok is False


def test_fallback_returns_rule_prompt_and_records_the_degradation() -> None:
    auditor = InMemoryCallAuditor()
    chain = FallbackProbeComposer(
        primary=_composer(FakeClient(LLMTimeout("slow"))),
        fallback=GraphProbeComposer(),
        auditor=auditor,
    )

    with tracing("S_TEST", 3):
        prompt = chain.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)

    assert prompt.question == PROBE.question
    events = [(entry.kind, entry.fallback_reason) for entry in auditor.entries]
    assert ("fallback", "timeout") in events
    fallback_entry = next(entry for entry in auditor.entries if entry.kind == "fallback")
    assert fallback_entry.session_id == "S_TEST"
    assert fallback_entry.turn == 3
    assert fallback_entry.probe_id == PROBE.id


@pytest.mark.parametrize(
    ("replies", "reason"),
    [
        (('{"foo": 1}', '{"foo": 1}'), "schema_invalid"),  # 缺字段（重试一次）
        (('{"question": "问一？问二？"}', '{"question": "问一？问二？"}'), "schema_invalid"),
        ((LLMTimeout("slow"),), "timeout"),
    ],
    ids=["missing_field", "two_question_marks", "timeout"],
)
def test_three_failure_classes_fall_back(
    replies: tuple[str | Exception, ...],
    reason: str,
) -> None:
    """T4 acceptance: 缺字段 / 多问号 / 超时 都回退到规则实现。"""
    auditor = InMemoryCallAuditor()
    chain = FallbackProbeComposer(
        primary=_composer(FakeClient(*replies), auditor),
        fallback=GraphProbeComposer(),
        auditor=auditor,
    )

    prompt = chain.compose(SAMPLE_PROBLEM, PROBE, confidence=0.6)

    assert prompt.question == PROBE.question
    fallback_entries = [entry for entry in auditor.entries if entry.kind == "fallback"]
    assert fallback_entries, "degradation must be audited"
    assert fallback_entries[-1].fallback_reason == reason


def test_shadow_returns_baseline_and_records_diff() -> None:
    from synapse.application.composer import ShadowProbeComposer

    auditor = InMemoryCallAuditor()
    shadow = ShadowProbeComposer(
        baseline=GraphProbeComposer(),
        experiment=_composer(FakeClient(VALID)),
        auditor=auditor,
    )

    prompt = shadow.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)

    assert prompt.question == PROBE.question, "shadow must not change the answer"
    (entry,) = auditor.entries
    assert entry.kind == "shadow"
    assert entry.fallback_reason == "differs"
    assert entry.baseline == PROBE.question
    assert entry.candidate == "如果 a 等于 0，导数还会出现零点吗？"


def test_shadow_survives_an_experiment_failure() -> None:
    from synapse.application.composer import ShadowProbeComposer

    auditor = InMemoryCallAuditor()
    shadow = ShadowProbeComposer(
        baseline=GraphProbeComposer(),
        experiment=_composer(FakeClient(LLMTimeout("slow"))),
        auditor=auditor,
    )

    prompt = shadow.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)

    assert prompt.question == PROBE.question
    (entry,) = auditor.entries
    assert entry.fallback_reason == "timeout"
    assert entry.candidate == ""


def test_canary_routes_by_session() -> None:
    client = FakeClient(VALID)
    chain = CanaryProbeComposer(
        baseline=GraphProbeComposer(),
        candidate=_composer(client),
        use_candidate=lambda sid: sid == "S_ON",
    )

    with tracing("S_OFF", 1):
        off = chain.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)
    with tracing("S_ON", 1):
        on = chain.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)

    assert off.question == PROBE.question
    assert on.question == "如果 a 等于 0，导数还会出现零点吗？"
    assert len(client.calls) == 1


def test_leak_guard_stays_outermost() -> None:
    """The model can try to leak; the decorator replaces the prompt."""
    chain = LeakSafeProbeComposer(
        inner=FallbackProbeComposer(
            primary=_composer(FakeClient('{"question": "所以答案是 a≥1/e 吗？"}')),
            fallback=GraphProbeComposer(),
        ),
        guards=AnswerStoreLeakGuardFactory(InMemoryAnswerStore()),
    )

    prompt = chain.compose(SAMPLE_PROBLEM, PROBE, confidence=0.7)

    assert prompt.reason_code == "LEAK_FALLBACK"
    assert "1/e" not in prompt.question


def test_request_never_carries_the_reference_step() -> None:
    """Answer isolation: node.text/common_errors must not reach the model."""
    client = FakeClient(VALID)
    _composer(client).compose(SAMPLE_PROBLEM, PROBE, confidence=0.6)

    (request,) = client.calls
    node = SAMPLE_PROBLEM.graph.node("n3")
    assert node.text not in request.user
    assert "漏掉 a=0" not in request.user
    assert SAMPLE_PROBLEM.id not in request.user
    for error in node.common_errors:
        assert error not in request.user


def test_missing_key_never_calls_a_model() -> None:
    """`off` and `on`-without-key both resolve to the rule composer."""
    from synapse.api.deps import build_composer

    rule = build_composer(LLMSettings(mode="off"))
    assert isinstance(rule, GraphProbeComposer)

    no_key = build_composer(LLMSettings(mode="on", api_key=None))
    assert isinstance(no_key, GraphProbeComposer)


def test_guard_replacement_is_the_only_leak_path() -> None:
    """A direct guard query: the forbidden tokens cover the sampled answer."""
    guard = AnswerLeakGuard(forbidden=("a∈(-∞,0]∪[1/e,∞)", "1/e"))
    assert guard.find("所以 a≥1/e")
