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

import os
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
from synapse.application.domain_detection import (
    CascadeDomainDetector,
    DomainDetector,
    HeuristicDomainDetector,
)
from synapse.application.domains import DomainRegistry, DomainResolver
from synapse.application.execution import CodeExecutor
from synapse.application.factory import SessionFactory
from synapse.application.generic_graph import GenericGraphGenerator
from synapse.application.graph import GraphGenerator
from synapse.application.knowledge import KnowledgeService
from synapse.application.limits import StepRateLimiter
from synapse.application.llm import LLMClient
from synapse.application.planner import HypothesisTargetedPlanner
from synapse.application.ports import AnswerStore, ProblemRepository, SessionRepository
from synapse.application.problem_resolver import ProblemResolver
from synapse.application.review import ReviewService
from synapse.application.service import SessionService
from synapse.application.subject import SubjectRegistry
from synapse.application.work_check import EqualityChecker
from synapse.domain.problem.alignment import RuleBasedAligner
from synapse.infrastructure.execution import ExecutionLimits, LocalPythonExecutor
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.guards import AnswerStoreLeakGuardFactory
from synapse.infrastructure.in_memory import (
    InMemoryAnswerStore,
    InMemoryProblemRepository,
    InMemorySessionRepository,
)
from synapse.infrastructure.knowledge import build_knowledge_service
from synapse.infrastructure.llm.audit import JsonlCallAuditor
from synapse.infrastructure.llm.client import OpenAICompatibleClient
from synapse.infrastructure.llm.composer import LLMProbeComposer
from synapse.infrastructure.llm.domain_detector import LLMDomainDetector
from synapse.infrastructure.llm.generic_graph import LLMGenericGraphGenerator
from synapse.infrastructure.llm.graph import LLMGraphGenerator
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.rate_limit import TokenBucketStepLimiter
from synapse.infrastructure.review import SqliteReviewQueue
from synapse.infrastructure.sqlite_state import (
    SqliteProblemRepository,
    SqliteSessionRepository,
)
from synapse.infrastructure.subjects.chinese import ChinesePlugin
from synapse.infrastructure.subjects.math import MathPlugin
from synapse.infrastructure.subjects.physics import PhysicsPlugin
from synapse.infrastructure.system import SystemClock, UuidSessionIdGenerator
from synapse.infrastructure.verification.equalities import SympyEqualityChecker


@dataclass(frozen=True, slots=True)
class Container:
    sessions: SessionRepository
    problems: ProblemRepository
    answers: AnswerStore
    service: SessionService
    review: ReviewService
    settings: LLMSettings
    subjects: SubjectRegistry
    features: FeatureFlags
    knowledge: KnowledgeService
    executor: CodeExecutor | None


def build_container(
    settings: LLMSettings | None = None,
    *,
    features: FeatureFlags | None = None,
    llm_client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
    generator: GraphGenerator | None = None,
    generic_generator: GenericGraphGenerator | None = None,
    step_limiter: StepRateLimiter | None = None,
    knowledge: KnowledgeService | None = None,
    executor: CodeExecutor | None = None,
) -> Container:
    resolved = settings or LLMSettings.from_env()
    flags = features or FeatureFlags.from_env()
    # Persistence is opt-in: tests and evaluation scripts keep the in-memory
    # adapters, while the local launcher points this at var/synapse.sqlite3.
    # Sessions and generated problems share one file so a restored session can
    # still resolve the graph it was diagnosed against.
    state_db = os.environ.get("SYNAPSE_SESSION_DB", "").strip()
    sessions: SessionRepository
    problems: InMemoryProblemRepository
    if state_db:
        sessions = SqliteSessionRepository(Path(state_db))
        problems = SqliteProblemRepository(Path(state_db))
    else:
        sessions = InMemorySessionRepository()
        problems = InMemoryProblemRepository()
    answers = InMemoryAnswerStore()
    sink = auditor or JsonlCallAuditor(Path(resolved.audit_path))
    graph_generator = generator or build_graph_generator(resolved, client=llm_client, auditor=sink)
    # SymPy's import (~1.7s) is paid here, once, instead of inside the first
    # request that happens to carry a verifiable claim (chapter 12 §12.8).
    # Optional: a fake generator in the tests has no ``warm``.
    warm = getattr(graph_generator, "warm", None)
    if callable(warm):
        warm()
    # Phase 1b: a reference-free problem gets its own structure graph. This is
    # deliberately separate from the solution generator: a failure here must
    # still leave the generic intake available, never a 422.
    generic_graph_generator = generic_generator or build_generic_graph_generator(
        resolved,
        client=llm_client,
        auditor=sink,
    )
    generic_warm = getattr(generic_graph_generator, "warm", None)
    if callable(generic_warm):
        generic_warm()
    # Opt-in (default off): verifying the student's own equals signs changes
    # annotated baseline cards, so the golden path must not see it.
    equality_checker: EqualityChecker | None = (
        SympyEqualityChecker() if flags.equality_check else None
    )
    # The plugin owns the generator; the repository owns the store, so a
    # generated problem can be served again on later turns (M2.5 S5 ②).
    problems.set_plugins(
        SubjectRegistry(
            (
                MathPlugin(
                    problems.catalog,
                    generator=graph_generator,
                    equality_checker=equality_checker,
                ),
                PhysicsPlugin(generator=graph_generator),
                ChinesePlugin(generator=graph_generator),
            )
        )
    )
    # S8: the strategy lives on the subject plugin. This aligner is only the
    # no-registry fallback; every production subject returns its own.
    aligner = RuleBasedAligner()
    # Deterministic first; the model only sees stems the term scorer cannot
    # decide. ``shadow`` must not change what the student sees, so it stays on
    # the heuristic path along with ``off``. A non-decisive result is no longer
    # an error: the resolver keeps the generic profile.
    domains = DomainRegistry()
    detector: DomainDetector = HeuristicDomainDetector()
    if resolved.llm_enabled and resolved.mode != "shadow":
        detector = CascadeDomainDetector(
            detector,
            LLMDomainDetector(llm_client or OpenAICompatibleClient(resolved)),
        )
    domain_resolver = DomainResolver(domains, detector)
    factory = SessionFactory(
        problems=problems,
        aligner=aligner,
        ids=UuidSessionIdGenerator(),
        clock=SystemClock(),
        subjects=problems.plugins,
        resolver=ProblemResolver(
            problems,
            problems.plugins,
            store=problems,
            domains=domain_resolver,
            generic_generator=generic_graph_generator,
        ),
    )
    planner = HypothesisTargetedPlanner()
    guards = AnswerStoreLeakGuardFactory(answers)
    composer = LeakSafeProbeComposer(
        inner=build_composer(resolved, client=llm_client, auditor=auditor),
        guards=guards,
    )
    # Same guard, same renderer, no model call: the first question of a
    # generated problem does not wait for a cosmetic rewrite (chapter 12 §12.8).
    opening = LeakSafeProbeComposer(inner=GraphProbeComposer(), guards=guards)
    limiter = step_limiter if step_limiter is not None else TokenBucketStepLimiter()
    review_queue = SqliteReviewQueue(
        Path(os.environ.get("SYNAPSE_REVIEW_DB", "var/review.sqlite3"))
    )
    service = SessionService(
        sessions=sessions,
        problems=problems,
        factory=factory,
        planner=planner,
        composer=composer,
        opening_composer=opening,
        equality_checker=equality_checker,
        subjects=problems.plugins,
        domains=domains,
        auditor=sink,
        step_limiter=limiter,
        review_queue=review_queue,
        answers=answers,
        chc_attribution=flags.chc_attribution,
    )
    knowledge_service = (
        knowledge if knowledge is not None else build_knowledge_service(enabled=flags.rag)
    )
    # The feature flag is the outer switch: an injected adapter cannot turn the
    # endpoint on when ``SYNAPSE_EXEC`` is off.
    code_executor = executor if executor is not None and flags.execution else build_executor(flags)
    return Container(
        sessions=sessions,
        problems=problems,
        answers=answers,
        service=service,
        review=ReviewService(review_queue),
        settings=resolved,
        subjects=problems.plugins,
        features=flags,
        knowledge=knowledge_service,
        executor=code_executor,
    )


def build_graph_generator(
    settings: LLMSettings,
    *,
    client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
) -> GraphGenerator | None:
    """Graph generation is only wired when the model path is actually serving.

    ``off`` keeps the M1 behaviour (annotated catalog only, 422 otherwise) and
    ``shadow`` must not change what the student sees, so neither generates.
    """

    if not settings.llm_enabled or settings.mode == "shadow":
        return None
    return LLMGraphGenerator(
        client or OpenAICompatibleClient(settings),
        settings=settings,
        auditor=auditor,
    )


def build_generic_graph_generator(
    settings: LLMSettings,
    *,
    client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
) -> GenericGraphGenerator | None:
    """Generic structure generation follows the same switch as graph building.

    ``off`` has no key path and ``shadow`` must not change what the learner
    sees; both leave the Phase 0 intake unchanged.
    """

    if not settings.llm_enabled or settings.mode == "shadow":
        return None
    return LLMGenericGraphGenerator(
        client or OpenAICompatibleClient(settings),
        settings=settings,
        auditor=auditor,
    )


def build_executor(
    flags: FeatureFlags,
    limits: ExecutionLimits | None = None,
) -> CodeExecutor | None:
    """Off means no executor object at all; the route returns 403."""

    if not flags.execution:
        return None
    return LocalPythonExecutor(limits)


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


def get_review_service(request: Request) -> ReviewService:
    container = cast(Container, request.app.state.container)
    return container.review


def get_knowledge_service(request: Request) -> KnowledgeService:
    container = cast(Container, request.app.state.container)
    return container.knowledge


def get_executor(request: Request) -> CodeExecutor | None:
    container = cast(Container, request.app.state.container)
    return container.executor
