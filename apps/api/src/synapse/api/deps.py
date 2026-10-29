"""Composition root.

FastAPI's dependency injection reads the container from ``app.state``; tests
can build a fresh app/container without touching globals.

The composer chain is chosen here and nowhere else (chapter 12 §12.7):

    off     rule only
    shadow  rule result returned, LLM run beside it for diffing
    on:10   per-session canary by hash, LLM result with rule fallback
    on      the same chain with every session routed to the model
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import Request

from synapse.application.audit import CallAuditor
from synapse.application.composer import (
    CanaryProbeComposer,
    FallbackProbeComposer,
    GraphProbeComposer,
    LeakSafeProbeComposer,
    ProbeComposer,
    ShadowProbeComposer,
)
from synapse.application.factory import SessionFactory
from synapse.application.llm import LLMClient
from synapse.application.planner import HypothesisTargetedPlanner
from synapse.application.ports import AnswerStore, ProblemRepository, SessionRepository
from synapse.application.service import SessionService
from synapse.domain.problem.alignment import RuleBasedAligner
from synapse.infrastructure.guards import AnswerStoreLeakGuardFactory
from synapse.infrastructure.in_memory import (
    InMemoryAnswerStore,
    InMemoryProblemRepository,
    InMemorySessionRepository,
)
from synapse.infrastructure.llm.audit import JsonlCallAuditor
from synapse.infrastructure.llm.client import OpenAICompatibleClient
from synapse.infrastructure.llm.composer import LLMProbeComposer
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.system import SystemClock, UuidSessionIdGenerator


@dataclass(frozen=True, slots=True)
class Container:
    sessions: SessionRepository
    problems: ProblemRepository
    answers: AnswerStore
    service: SessionService
    settings: LLMSettings


def build_container(
    settings: LLMSettings | None = None,
    *,
    llm_client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
) -> Container:
    resolved = settings or LLMSettings.from_env()
    sessions = InMemorySessionRepository()
    problems = InMemoryProblemRepository()
    answers = InMemoryAnswerStore()
    factory = SessionFactory(
        problems=problems,
        aligner=RuleBasedAligner(),
        ids=UuidSessionIdGenerator(),
        clock=SystemClock(),
    )
    planner = HypothesisTargetedPlanner()
    composer = LeakSafeProbeComposer(
        inner=build_composer(resolved, client=llm_client, auditor=auditor),
        guards=AnswerStoreLeakGuardFactory(answers),
    )
    service = SessionService(
        sessions=sessions,
        problems=problems,
        factory=factory,
        planner=planner,
        composer=composer,
    )
    return Container(
        sessions=sessions,
        problems=problems,
        answers=answers,
        service=service,
        settings=resolved,
    )


def build_composer(
    settings: LLMSettings,
    *,
    client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
) -> ProbeComposer:
    """Assemble the decorator chain; the leak guard is added by the caller."""
    rule = GraphProbeComposer()
    if not settings.llm_enabled:
        return rule

    sink = auditor or JsonlCallAuditor(Path(settings.audit_path))
    llm = LLMProbeComposer(
        client or OpenAICompatibleClient(settings),
        settings=settings,
        auditor=sink,
    )
    if settings.mode == "shadow":
        # Baseline is returned; the model result is compared, never shown.
        return ShadowProbeComposer(baseline=rule, experiment=llm, auditor=sink)

    guarded = FallbackProbeComposer(primary=llm, fallback=rule, auditor=sink)
    return CanaryProbeComposer(
        baseline=rule,
        candidate=guarded,
        use_candidate=settings.use_for,
    )


def get_service(request: Request) -> SessionService:
    container = cast(Container, request.app.state.container)
    return container.service