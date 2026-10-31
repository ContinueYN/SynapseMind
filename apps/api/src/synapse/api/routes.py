"""HTTP routes. Keep them thin: validate, call a use case, map the result."""

from __future__ import annotations

from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from synapse.api.deps import get_knowledge_service, get_review_service, get_service
from synapse.api.mappers import (
    diagnosis_out,
    knowledge_search_out,
    review_items_out,
    session_out,
    step_verdict_out,
)
from synapse.api.schemas import (
    CreateSessionRequest,
    DiagnosisOut,
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
from synapse.application.factory import ProblemNotSupported, UnsupportedMode
from synapse.application.knowledge import KnowledgeService, KnowledgeUnavailable
from synapse.application.limits import StepRateLimited
from synapse.application.review import ReviewService
from synapse.application.service import (
    DiagnosisNotReady,
    InvalidAnswer,
    SessionNotFound,
    SessionService,
)
from synapse.domain.dialogue.table import IllegalTransition

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(version="0.1.0")


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
    subject: Literal["math", "physics", "chinese"] | None = Query(default=None),
    limit: int = Query(default=3, ge=1, le=5),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeSearchOut:
    """Find sourced knowledge cards for a concept label.

    The query is a label, not the student's answer or work: callers must not
    send prose from the attempt. Retrieval is read-only and never advances a
    session or changes a diagnosis.
    """

    try:
        result = knowledge.search(q, subject=subject, limit=limit)
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
    return session_out(
        view,
        service.problem_title(view.session.problem_id),
        service.problem_text(view.session.problem_id),
        service.problem_subject(view.session.problem_id),
    )


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return session_out(
        view,
        service.problem_title(view.session.problem_id),
        service.problem_text(view.session.problem_id),
        service.problem_subject(view.session.problem_id),
    )


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
    return session_out(
        view,
        service.problem_title(view.session.problem_id),
        service.problem_text(view.session.problem_id),
        service.problem_subject(view.session.problem_id),
    )


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
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.exit(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return session_out(
        view,
        service.problem_title(view.session.problem_id),
        service.problem_text(view.session.problem_id),
        service.problem_subject(view.session.problem_id),
    )
