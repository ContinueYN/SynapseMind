from __future__ import annotations

from synapse.application.composer import (
    GraphProbeComposer,
    LeakSafeProbeComposer,
    ProbePrompt,
)
from synapse.domain.guard.leak import AnswerLeakGuard
from synapse.domain.problem.models import Probe
from synapse.infrastructure.seed import SAMPLE_PROBLEM


class _GuardFactory:
    def for_problem(self, problem_id: str) -> AnswerLeakGuard:
        assert problem_id == SAMPLE_PROBLEM.id
        return AnswerLeakGuard(forbidden=("1/e",))


def _probe(question: str) -> Probe:
    return Probe(
        id="p_test",
        question=question,
        options=("是", "否", "不确定"),
        targets=("H_L2",),
        correct_option="A",
    )


def test_decorator_replaces_leaking_prompt() -> None:
    composer = LeakSafeProbeComposer(GraphProbeComposer(), _GuardFactory())
    prompt = composer.compose(
        SAMPLE_PROBLEM,
        _probe("所以答案是不是 1/e？"),
        confidence=0.7,
    )
    assert prompt.reason_code == "LEAK_FALLBACK"
    assert prompt.action == "hint"
    assert "1/e" not in prompt.question
    assert "1/e" not in " ".join(prompt.options)


def test_decorator_preserves_safe_prompt() -> None:
    composer = LeakSafeProbeComposer(GraphProbeComposer(), _GuardFactory())
    original = _probe("a=0 时，f'(x)=1/x 有零点吗？")
    prompt = composer.compose(SAMPLE_PROBLEM, original, confidence=0.7)
    assert isinstance(prompt, ProbePrompt)
    assert prompt.reason_code == "DISCRIMINATE_HYPOTHESIS"
    assert prompt.question == original.question
