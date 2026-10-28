"""HTTP routes. Keep them thin: validate, call a use case, map the result."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from synapse.api.deps import get_service
from synapse.api.mappers import session_out
from synapse.api.schemas import (
    CreateSessionRequest,
    HealthOut,
    SessionOut,
    TurnRequest,
)
from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand
from synapse.application.factory import ProblemNotSupported, UnsupportedMode
from synapse.application.service import InvalidAnswer, SessionNotFound, SessionService
from synapse.domain.dialogue.table import IllegalTransition

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(version="0.1.0")


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
    )
    try:
        view = service.start(command)
    except (ProblemNotSupported, UnsupportedMode) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return session_out(view, service.problem_title(view.session.problem_id))


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return session_out(view, service.problem_title(view.session.problem_id))


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
    return session_out(view, service.problem_title(view.session.problem_id))


@router.post("/sessions/{session_id}/exit", response_model=SessionOut)
def exit_session(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.exit(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return session_out(view, service.problem_title(view.session.problem_id))
