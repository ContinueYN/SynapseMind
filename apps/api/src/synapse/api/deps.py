"""Composition root.

FastAPI's dependency injection reads the container from ``app.state``; tests
can build a fresh app/container without touching globals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request

from synapse.application.composer import GraphProbeComposer, LeakSafeProbeComposer
from synapse.application.factory import SessionFactory
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
from synapse.infrastructure.system import SystemClock, UuidSessionIdGenerator


@dataclass(frozen=True, slots=True)
class Container:
    sessions: SessionRepository
    problems: ProblemRepository
    answers: AnswerStore
    service: SessionService


def build_container() -> Container:
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
        inner=GraphProbeComposer(),
        guards=AnswerStoreLeakGuardFactory(answers),
    )
    service = SessionService(
        sessions=sessions,
        problems=problems,
        factory=factory,
        planner=planner,
        composer=composer,
    )
    return Container(sessions=sessions, problems=problems, answers=answers, service=service)


def get_service(request: Request) -> SessionService:
    container = cast(Container, request.app.state.container)
    return container.service
