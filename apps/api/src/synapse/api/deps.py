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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import HTTPException, Request, status
from httpx import BaseTransport

from synapse.application.agent_planner import ToolPlanner
from synapse.application.audit import CallAuditor
from synapse.application.auth import AuthService, AuthUser
from synapse.application.coach import CoachNarrator, CoachService
from synapse.application.composer import (
    CanaryProbeComposer,
    FallbackProbeComposer,
    GraphProbeComposer,
    LeakSafeProbeComposer,
    ProbeComposer,
    ShadowProbeComposer,
)
from synapse.application.credentials import (
    CredentialService,
    ModelTester,
    RemoteUrlGuard,
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
from synapse.infrastructure.auth.build import AuthRuntime, build_auth
from synapse.infrastructure.auth.settings import AuthSettings
from synapse.infrastructure.credentials.settings import CredentialSettings
from synapse.infrastructure.execution import ExecutionLimits, LocalPythonExecutor
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.guards import AnswerStoreLeakGuardFactory
from synapse.infrastructure.in_memory import (
    InMemoryAnswerStore,
    InMemoryProblemRepository,
    InMemorySessionRepository,
)
from synapse.infrastructure.knowledge import build_knowledge_service
from synapse.infrastructure.llm.agent_planner import LLMToolPlanner
from synapse.infrastructure.llm.audit import JsonlCallAuditor
from synapse.infrastructure.llm.client import CredentialAwareLLMClient, OpenAICompatibleClient
from synapse.infrastructure.llm.coach import LLMCoachNarrator
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
    # Account layer. ``auth`` is None when SYNAPSE_AUTH=off, which is also how
    # the session gate knows it must not run.
    auth: AuthService | None
    auth_settings: AuthSettings
    # Per-user encrypted model credentials (BYOK). None when auth is off or a
    # gate-only runtime was injected without a database.
    credentials: CredentialService | None = None
    # Releases the engine/Redis connection opened for auth (None when off).
    auth_dispose: Callable[[], None] | None = None


def build_container(
    settings: LLMSettings | None = None,
    *,
    features: FeatureFlags | None = None,
    llm_client: LLMClient | None = None,
    llm_transport_factory: Callable[[], BaseTransport | None] | None = None,
    auditor: CallAuditor | None = None,
    generator: GraphGenerator | None = None,
    generic_generator: GenericGraphGenerator | None = None,
    step_limiter: StepRateLimiter | None = None,
    knowledge: KnowledgeService | None = None,
    executor: CodeExecutor | None = None,
    tool_planner: ToolPlanner | None = None,
    coach_narrator: CoachNarrator | None = None,
    auth_settings: AuthSettings | None = None,
    auth_runtime: AuthRuntime | None = None,
    credential_settings: CredentialSettings | None = None,
    credential_guard: RemoteUrlGuard | None = None,
    credential_tester: ModelTester | None = None,
) -> Container:
    resolved = settings or LLMSettings.from_env()
    flags = features or FeatureFlags.from_env()
    # Accounts are opt-in: ``SYNAPSE_AUTH=off`` builds no engine and touches no
    # database, so the baseline single-user checkout keeps its behaviour.
    auth_cfg = auth_settings if auth_settings is not None else AuthSettings.from_env()
    auth = (
        auth_runtime
        if auth_runtime is not None
        else build_auth(
            auth_cfg,
            credential_settings=credential_settings,
            credential_guard=credential_guard,
            credential_tester=credential_tester,
        )
    )
    credentials = auth.credentials if auth is not None else None
    # One model client for every path. It resolves the request's own credential
    # on each call; an injected client (tests) still wins.
    if llm_client is not None:
        model_client: LLMClient | None = llm_client
    elif resolved.llm_enabled:
        model_client = CredentialAwareLLMClient(
            resolved,
            credentials=credentials,
            transport_factory=llm_transport_factory,
        )
    else:
        model_client = None
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
    graph_generator = generator or build_graph_generator(
        resolved, client=model_client, auditor=sink
    )
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
        client=model_client,
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
            LLMDomainDetector(model_client or OpenAICompatibleClient(resolved)),
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
        inner=build_composer(resolved, client=model_client, auditor=auditor),
        guards=guards,
    )
    # Same guard, same renderer, no model call: the first question of a
    # generated problem does not wait for a cosmetic rewrite (chapter 12 §12.8).
    opening = LeakSafeProbeComposer(inner=GraphProbeComposer(), guards=guards)
    limiter = step_limiter if step_limiter is not None else TokenBucketStepLimiter()
    review_queue = SqliteReviewQueue(
        Path(os.environ.get("SYNAPSE_REVIEW_DB", "var/review.sqlite3"))
    )
    knowledge_service = (
        knowledge if knowledge is not None else build_knowledge_service(enabled=flags.rag)
    )
    # The feature flag is the outer switch: an injected adapter cannot turn the
    # endpoint on when ``SYNAPSE_EXEC`` is off.
    code_executor = executor if executor is not None and flags.execution else build_executor(flags)
    # Phase 4 (second slice): optional planner. Injected fakes are still gated
    # by the switch so a test cannot pretend the production path is on.
    tool_planner_adapter = build_tool_planner(
        resolved,
        candidate=tool_planner,
        client=model_client,
        auditor=sink,
    )
    planner_reason = "" if tool_planner_adapter is not None else tool_planner_off_reason(resolved)
    # The process coach is usable without a key: its rule path always exists.
    # A model narrator is attached only when the model path is live and not in
    # shadow, and an injected fake is gated by the same switch.
    coach_adapter = build_coach_narrator(
        resolved,
        candidate=coach_narrator,
        client=model_client,
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
        knowledge=knowledge_service,
        code_executor=code_executor,
        tool_planner=tool_planner_adapter,
        tool_planner_reason=planner_reason,
        coach_service=CoachService(coach_adapter),
    )
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
        auth=auth.service if auth is not None else None,
        auth_settings=auth_cfg,
        credentials=credentials,
        auth_dispose=auth.close if auth is not None else None,
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


def build_tool_planner(
    settings: LLMSettings,
    *,
    candidate: ToolPlanner | None = None,
    client: LLMClient | None = None,
    auditor: CallAuditor | None = None,
) -> ToolPlanner | None:
    """The optional planner needs its own switch, a live model and no shadow.

    ``off`` must keep the deterministic trace. ``shadow`` must not change what
    the student sees, so it keeps the rule choice even if a key is present.
    """

    if not settings.agent_planner:
        return None
    if not settings.llm_enabled or settings.mode == "shadow":
        return None
    if candidate is not None:
        return candidate
    return LLMToolPlanner(
        client or OpenAICompatibleClient(settings),
        settings=settings,
        auditor=auditor,
    )


def tool_planner_off_reason(settings: LLMSettings) -> str:
    """A stable code explaining why no planner was wired (shown in the trace)."""

    if not settings.agent_planner:
        return "planner_off"
    if settings.mode == "off":
        return "llm_off"
    if not settings.api_key:
        return "no_api_key"
    if settings.mode == "shadow":
        return "shadow"
    return "planner_off"


def build_coach_narrator(
    settings: LLMSettings,
    *,
    candidate: CoachNarrator | None = None,
    client: LLMClient | None = None,
) -> CoachNarrator | None:
    """The coach's model voice is optional; the rule coach is always available.

    ``off`` and a missing key leave the narrator at ``None``, so the endpoint is
    a deterministic rule coach rather than a fake model. ``shadow`` must not
    change what the student sees, so it also keeps the rule result. An injected
    fake is gated by the same switch.
    """

    if not settings.llm_enabled or settings.mode == "shadow":
        return None
    if candidate is not None:
        return candidate
    return LLMCoachNarrator(
        client or OpenAICompatibleClient(settings),
        settings=settings,
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
    """The session facade, bound to the current owner.

    The async auth middleware authenticated the cookie (exchanging a one-time
    login ticket if that is what was presented) and stored the account on
    ``request.state`` before dispatch; binding the owner here is what makes
    another user's session a 404 instead of a readable object. With auth off the
    owner is ``None`` and no filtering happens (the local baseline).

    A protected route that somehow reaches this without the middleware fails
    closed: silently serving an unbound service would leak every workspace.
    """

    container = cast(Container, request.app.state.container)
    user = cast(AuthUser | None, getattr(request.state, "auth_user", None))
    if container.auth_settings.enabled and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要先登录。",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return container.service.with_owner(user.id if user is not None else None)


def get_review_service(request: Request) -> ReviewService:
    container = cast(Container, request.app.state.container)
    return container.review


def get_knowledge_service(request: Request) -> KnowledgeService:
    container = cast(Container, request.app.state.container)
    return container.knowledge


def get_executor(request: Request) -> CodeExecutor | None:
    container = cast(Container, request.app.state.container)
    return container.executor
