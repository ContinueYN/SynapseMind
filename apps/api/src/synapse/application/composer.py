"""Prompt composition and the answer-leak decorator.

Pattern: Decorator. ``GraphProbeComposer`` renders the graph probe;
``LeakSafeProbeComposer`` wraps it and replaces a leaking prompt with a safe
fallback. The wrapped composer does not know the guard exists.

M2 adds three decorators on the same seam: ``FallbackProbeComposer`` (T4),
``ShadowProbeComposer`` (T6) and ``CanaryProbeComposer`` (``on:10``). None of
them may change state: the state machine is driven by ``SessionService``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.application import trace
from synapse.application.audit import AuditEntry, CallAuditor
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


class CompositionFailed(RuntimeError):
    """The model path could not produce a valid ``ProbePrompt``.

    Raised by ``LLMProbeComposer``; the decorators below turn it into a
    degradation instead of an error the student can see.
    """

    def __init__(self, reason: str, *, schema_ok: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.schema_ok = schema_ok


def _audit(
    auditor: CallAuditor | None,
    *,
    kind: Literal["fallback", "shadow"],
    probe: Probe,
    fallback_reason: str | None = None,
    schema_ok: bool = False,
    baseline: str = "",
    candidate: str = "",
) -> None:
    if auditor is None:
        return
    context = trace.current()
    auditor.record(
        AuditEntry(
            kind=kind,
            session_id=context.session_id if context else "",
            turn=context.turn if context else 0,
            probe_id=probe.id,
            fallback_reason=fallback_reason,
            schema_ok=schema_ok,
            baseline=baseline,
            candidate=candidate,
        )
    )


class FallbackProbeComposer:
    """T4: try the model, fall back to the rule implementation on any failure.

    Timeouts are not retried here (a retry would eat the 8s first-question
    budget); schema failures are already retried once inside the adapter.
    """

    def __init__(
        self,
        primary: ProbeComposer,
        fallback: ProbeComposer,
        *,
        auditor: CallAuditor | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._auditor = auditor

    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        try:
            return self._primary.compose(
                problem,
                probe,
                confidence=confidence,
                hint_level=hint_level,
            )
        except CompositionFailed as exc:
            _audit(
                self._auditor,
                kind="fallback",
                probe=probe,
                fallback_reason=exc.reason,
                schema_ok=exc.schema_ok,
            )
            return self._fallback.compose(
                problem,
                probe,
                confidence=confidence,
                hint_level=hint_level,
            )


class ShadowProbeComposer:
    """T6: run both implementations, return the baseline, record the difference.

    A shadow failure must never reach the student, so it is recorded and
    swallowed. The comparison is question text only: options and action are
    derived, not generated.
    """

    def __init__(
        self,
        baseline: ProbeComposer,
        experiment: ProbeComposer,
        *,
        auditor: CallAuditor | None = None,
    ) -> None:
        self._baseline = baseline
        self._experiment = experiment
        self._auditor = auditor

    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        prompt = self._baseline.compose(
            problem,
            probe,
            confidence=confidence,
            hint_level=hint_level,
        )
        try:
            candidate = self._experiment.compose(
                problem,
                probe,
                confidence=confidence,
                hint_level=hint_level,
            )
        except CompositionFailed as exc:
            _audit(
                self._auditor,
                kind="shadow",
                probe=probe,
                fallback_reason=exc.reason,
                baseline=prompt.question,
            )
            return prompt

        _audit(
            self._auditor,
            kind="shadow",
            probe=probe,
            schema_ok=True,
            baseline=prompt.question,
            candidate=candidate.question,
            fallback_reason=None if candidate.question == prompt.question else "differs",
        )
        return prompt


class CanaryProbeComposer:
    """``on:10``: route by session id; no trace means the safe baseline."""

    def __init__(
        self,
        baseline: ProbeComposer,
        candidate: ProbeComposer,
        *,
        use_candidate: Callable[[str], bool],
    ) -> None:
        self._baseline = baseline
        self._candidate = candidate
        self._use_candidate = use_candidate

    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        context = trace.current()
        if context is None or not self._use_candidate(context.session_id):
            return self._baseline.compose(
                problem,
                probe,
                confidence=confidence,
                hint_level=hint_level,
            )
        return self._candidate.compose(
            problem,
            probe,
            confidence=confidence,
            hint_level=hint_level,
        )
