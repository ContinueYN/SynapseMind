"""Diagnostic session routes."""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, HTTPException, status

from synapse.api.auth import require_authenticated
from synapse.api.deps import get_service
from synapse.api.mappers.agent import agent_trace_out
from synapse.api.mappers.coach import coach_out
from synapse.api.mappers.review import generic_review_out
from synapse.api.mappers.sessions import (
    diagnosis_out,
    session_out,
    step_verdict_out,
)
from synapse.api.schemas.agent import AgentRunRequest, AgentTraceOut
from synapse.api.schemas.coach import CoachOut, CoachRequest
from synapse.api.schemas.review import GenericReviewOut, ReviewRunRequest
from synapse.api.schemas.sessions import (
    ClarifierRequest,
    CreateSessionRequest,
    DiagnosisOut,
    ExitRequest,
    IntakeProbeRequest,
    SessionOut,
    StepRequest,
    StepVerdictOut,
    TurnRequest,
)
from synapse.application.diagnosis.agent import AgentInputRejected, AgentUnavailable
from synapse.application.execution.service import ExecutionBusy
from synapse.application.sessions.commands import (
    StartSessionCommand,
    SubmitAnswerCommand,
    VerifyStepCommand,
)
from synapse.application.sessions.factory import ProblemNotSupported, UnsupportedMode
from synapse.application.sessions.limits import StepRateLimited
from synapse.application.sessions.service import (
    ClarifierUnavailable,
    DiagnosisNotReady,
    IntakeProbeUnavailable,
    InvalidAnswer,
    ReviewRunRejected,
    SessionNotFound,
    SessionService,
    SessionView,
)
from synapse.application.shared.errors import SessionConflict
from synapse.domain.dialogue.table import IllegalTransition

# Diagnostic session endpoints. With ``SYNAPSE_AUTH=on`` the dependency rejects
# a missing/invalid cookie with 401 before the route body runs; with the flag
# off it returns immediately, so the local single-user behaviour is unchanged.
router = APIRouter(
    prefix="/sessions",
    dependencies=[Depends(require_authenticated)],
)


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


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
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


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    try:
        view = service.get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return _session_out(view, service)


@router.post("/{session_id}/coach", response_model=CoachOut)
def coach_session(
    session_id: str,
    request: CoachRequest,
    service: SessionService = Depends(get_service),
) -> CoachOut:
    """Process feedback for "where am I wrong" / "how do I start".

    Read-only: no state change, no probe budget, no answer store. With no model
    configured this is the deterministic rule coach (``mode="rules"``); when the
    model path is live the response may be ``mode="llm"``, and any model failure
    is already converted into the rule result by the service instead of a 500.
    """

    try:
        result = service.coach(session_id, focus=request.focus)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return coach_out(result)


@router.get("/{session_id}/agent", response_model=AgentTraceOut)
def get_agent_trace(
    session_id: str,
    service: SessionService = Depends(get_service),
) -> AgentTraceOut:
    """Read-only bounded tool trace; no code execution and no state changes."""

    try:
        trace = service.agent_trace(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except AgentUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="工具轨迹只用于通用入口会话；这道题已经有参考结构。",
        ) from exc
    return agent_trace_out(trace)


@router.post("/{session_id}/agent/run", response_model=AgentTraceOut)
def run_agent_trace(
    session_id: str,
    request: AgentRunRequest,
    service: SessionService = Depends(get_service),
) -> AgentTraceOut:
    """Trace with one explicitly submitted Python reproduction.

    This endpoint never pulls code out of the problem or the attempt; with
    ``SYNAPSE_EXEC=off`` the trace records a skipped execution instead of a
    fake pass. It does not write the session or read the answer store.
    """

    try:
        trace = service.agent_trace(
            session_id,
            code=request.code,
            tests=request.tests,
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except AgentUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="工具轨迹只用于通用入口会话；这道题已经有参考结构。",
        ) from exc
    except AgentInputRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return agent_trace_out(trace)


@router.post(
    "/{session_id}/review/run",
    response_model=GenericReviewOut,
    response_model_exclude_none=True,
)
def run_review(
    session_id: str,
    request: ReviewRunRequest,
    service: SessionService = Depends(get_service),
) -> GenericReviewOut:
    """Turn one explicitly submitted run into a code reproduction card.

    This is the only path that produces ``kind="execution"``; it never pulls
    code out of the problem or the attempt. Only a session whose verification
    mode is ``executable`` is accepted (409 otherwise). With ``SYNAPSE_EXEC=off``
    the card reports ``skipped`` and the executor is not called; ``pass`` means
    the process exited 0 or the submitted tests passed, never that the code is
    correct. The session is read-only: nothing is stored and the answer store is
    never read.
    """

    try:
        review = service.review_run(session_id, code=request.code, tests=request.tests)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ReviewRunRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ExecutionBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    return generic_review_out(review)


@router.post("/{session_id}/intake", response_model=SessionOut)
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


@router.post("/{session_id}/intake/probe", response_model=SessionOut)
def answer_intake_probe(
    session_id: str,
    request: IntakeProbeRequest,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    """Append one structural answer to a reference-free intake.

    The session stays closed. This is not a diagnostic probe: it adds a sentence
    to the student's local text and re-derives the coverage view. There are at
    most three such answers per session, and one question is shown at a time.
    """

    try:
        view = service.answer_intake_probe(session_id, request.answer)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except IntakeProbeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="这次入口没有待补充的结构问题，或补充次数已经用完。",
        ) from exc
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话已被另一个请求更新，请刷新后重试（{exc}）。",
        ) from exc
    return _session_out(view, service)


@router.post("/{session_id}/steps", response_model=StepVerdictOut)
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


@router.post("/{session_id}/turns", response_model=SessionOut)
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


@router.post("/{session_id}/card/disagree", response_model=DiagnosisOut)
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


@router.post("/{session_id}/exit", response_model=SessionOut)
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
