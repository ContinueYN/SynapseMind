"""HTTP routes. Keep them thin: validate, call a use case, map the result."""

from __future__ import annotations

from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from synapse.api.deps import (
    get_executor,
    get_knowledge_service,
    get_review_service,
    get_service,
)
from synapse.api.mappers import (
    diagnosis_out,
    execution_out,
    knowledge_search_out,
    review_items_out,
    session_out,
    step_verdict_out,
)
from synapse.api.schemas import (
    ClarifierRequest,
    CreateSessionRequest,
    DiagnosisOut,
    ExecutionOut,
    ExecutionRequestIn,
    ExitRequest,
    HealthOut,
    KnowledgeSearchOut,
    ReviewItemsOut,
    SessionOut,
    StepRequest,
    StepVerdictOut,
    TurnRequest,
)
from synapse.application.commands import (
    StartSessionCommand,
    SubmitAnswerCommand,
    VerifyStepCommand,
)
from synapse.application.errors import SessionConflict
from synapse.application.execution import (
    CodeExecutor,
    ExecutionBusy,
    RunCodeCommand,
)
from synapse.application.factory import ProblemNotSupported, UnsupportedMode
from synapse.application.knowledge import KnowledgeService, KnowledgeUnavailable
from synapse.application.limits import StepRateLimited
from synapse.application.review import ReviewService
from synapse.application.service import (
    ClarifierUnavailable,
    DiagnosisNotReady,
    InvalidAnswer,
    SessionNotFound,
    SessionService,
    SessionView,
)
from synapse.domain.dialogue.table import IllegalTransition

router = APIRouter(prefix="/api/v1")


def _session_out(view: SessionView, service: SessionService) -> SessionOut:
    """One place that gathers the problem metadata a session response needs."""

    problem_id = view.session.problem_id
    return session_out(
        view,
        service.problem_title(problem_id),
        service.problem_text(problem_id),
        service.problem_subject(problem_id),
        service.domain_for(view.session),
    )


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(version="0.1.0")


@router.post("/executions", response_model=ExecutionOut)
def run_code(
    request: ExecutionRequestIn,
    executor: CodeExecutor | None = Depends(get_executor),
) -> ExecutionOut:
    """Run one explicitly submitted Python file, or its submitted tests.

    This endpoint is not a diagnostic step: it does not read a session, write a
    session, select code, or call the model. It is off unless
    ``SYNAPSE_EXEC=on``; when off it returns 403 instead of pretending a run
    happened. ``pass`` means the process exited 0 or the submitted tests passed,
    never that the answer is correct.
    """

    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="代码执行默认关闭；设置 SYNAPSE_EXEC=on 后才可用。",
        )
    try:
        result = executor.run(
            RunCodeCommand(
                language=request.language,
                code=request.code,
                tests=request.tests,
            )
        )
    except ExecutionBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    return execution_out(result)


@router.get("/review/items", response_model=ReviewItemsOut)
def list_review_items(
    review: ReviewService = Depends(get_review_service),
) -> ReviewItemsOut:
    """Read-only listing of disagreed cards for the teacher review page.

    There is no write endpoint and no authentication yet: the queue is a local
    SQLite file, and the page exports the reviewer's judgment as a CSV instead
    of storing it. The response never contains the student's own work.
    """

    return review_items_out(review.items())


@router.get("/knowledge/search", response_model=KnowledgeSearchOut)
def search_knowledge(
    q: str = Query(min_length=2, max_length=200),
    subject: str | None = Query(default=None, min_length=1, max_length=40),
    verification: Literal["formal", "executable", "empirical", "argumentative"] | None = Query(
        default=None
    ),
    limit: int = Query(default=3, ge=1, le=5),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSearchOut:
    """Find sourced knowledge cards for a concept label.

    The query is a label, not the student's answer or work: callers must not
    send prose from the attempt. Retrieval is read-only and never advances a
    session or changes a diagnosis.
    """

    try:
        result = knowledge.search(
            q,
            subject=subject,
            verification=verification,
            limit=limit,
        )
    except KnowledgeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return knowledge_search_out(result)


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    command = StartSessionCommand(
        problem_text=request.problem.text or "",
        answer=request.attempt.answer,
        work=request.attempt.work,
        stuck_at=request.attempt.stuck_at,
        confidence=request.attempt.confidence,
        self_report=request.attempt.self_report,
        mode=request.mode,
        subject=request.problem.subject,
    )
    try:
        view = service.start(command)
    except (ProblemNotSupported, UnsupportedMode) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话创建冲突，请重试（{exc}）。",
        ) from exc
    return _session_out(view, service)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return _session_out(view, service)


@router.post("/sessions/{session_id}/intake", response_model=SessionOut)
def answer_intake_clarifier(
    session_id: str,
    request: ClarifierRequest,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    """Append the one allowed clarification to a reference-free intake.

    The session stays closed; this does not probe, diagnose, or reveal an
    answer. A second attempt returns 409 (or the current view with a notice if
    the first one already stored the flag).
    """

    try:
        view = service.answer_clarifier(session_id, request.answer)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ClarifierUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="这次入口没有待补充的问题，或补充机会已经用过。",
        ) from exc
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return _session_out(view, service)


@router.post("/sessions/{session_id}/steps", response_model=StepVerdictOut)
def verify_step(
    session_id: str,
    request: StepRequest,
    service: SessionService = Depends(get_service),
) -> StepVerdictOut:
    """Verify one step; read-only, so it never advances the dialogue."""

    try:
        verdict = service.verify_step(
            session_id,
            VerifyStepCommand(
                text=request.text,
                node_id=request.node_id,
                data=request.data,
            ),
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except StepRateLimited as exc:
        wait_seconds = max(1, ceil(exc.retry_after))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"单步检查太频繁，请约 {wait_seconds} 秒后再试。",
            headers={"Retry-After": str(wait_seconds)},
        ) from exc
    return step_verdict_out(verdict)


@router.post("/sessions/{session_id}/turns", response_model=SessionOut)
def submit_turn(
    session_id: str,
    request: TurnRequest,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.submit(
            session_id,
            SubmitAnswerCommand(answer=request.answer, option_id=request.option_id),
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return _session_out(view, service)


@router.post("/sessions/{session_id}/card/disagree", response_model=DiagnosisOut)
def disagree_with_card(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> DiagnosisOut:
    """Record a disagreement; the card itself is unchanged."""

    try:
        card = service.mark_card_disagree(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except DiagnosisNotReady as exc:
        raise HTTPException(
            status_code=409,
            detail="卡点卡尚未生成，暂时不能记录异议。",
        ) from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return diagnosis_out(card)


@router.post("/sessions/{session_id}/exit", response_model=SessionOut)
def exit_session(
    session_id: str,
    request: ExitRequest | None = None,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.exit(session_id, reveal=bool(request and request.reveal))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return _session_out(view, service)
