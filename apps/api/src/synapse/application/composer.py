"""Prompt composition and the answer-leak decorator.

Pattern: Decorator. ``GraphProbeComposer`` renders the graph probe;
``LeakSafeProbeComposer`` wraps it and replaces a leaking prompt with a safe
fallback. The wrapped composer does not know the guard exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.domain.guard.leak import AnswerLeakGuard
from synapse.domain.problem.models import Probe, Problem

ProbeAction = Literal["ask", "hint", "confirm"]


@dataclass(frozen=True, slots=True)
class ProbePrompt:
    action: ProbeAction
    question: str
    options: tuple[str, ...]
    hint_level: int
    reason_code: str
    confidence: float


class ProbeComposer(Protocol):
    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt: ...


class LeakGuardFactory(Protocol):
    def for_problem(self, problem_id: str) -> AnswerLeakGuard: ...


class GraphProbeComposer:
    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        del problem  # reserved for future context/renderer selection
        return ProbePrompt(
            action="ask" if hint_level == 0 else "hint",
            question=probe.question,
            options=probe.options,
            hint_level=hint_level,
            reason_code="DISCRIMINATE_HYPOTHESIS",
            confidence=round(confidence, 2),
        )


class LeakSafeProbeComposer:
    def __init__(self, inner: ProbeComposer, guards: LeakGuardFactory) -> None:
        self._inner = inner
        self._guards = guards

    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        prompt = self._inner.compose(
            problem,
            probe,
            confidence=confidence,
            hint_level=hint_level,
        )
        guard = self._guards.for_problem(problem.id)
        texts = (prompt.question, *prompt.options)
        if any(guard.find(text) for text in texts):
            return ProbePrompt(
                action="hint",
                question="先不急着算。你能指出题目里最容易被忽略的那个条件吗？",
                options=("定义域/边界条件", "参数范围", "最值条件", "不确定"),
                hint_level=max(1, hint_level),
                reason_code="LEAK_FALLBACK",
                confidence=round(confidence, 2),
            )
        return prompt
