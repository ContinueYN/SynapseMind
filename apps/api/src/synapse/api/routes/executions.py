"""Explicit code execution route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from synapse.api.auth import require_authenticated
from synapse.api.deps import get_executor
from synapse.api.mappers.execution import execution_out
from synapse.api.schemas.execution import ExecutionOut, ExecutionRequestIn
from synapse.application.execution.service import (
    CodeExecutor,
    ExecutionBusy,
    RunCodeCommand,
)

router = APIRouter()


@router.post(
    "/executions",
    response_model=ExecutionOut,
    dependencies=[Depends(require_authenticated)],
)
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

    With ``SYNAPSE_AUTH=on`` the middleware rejects a missing cookie with 401
    before this body runs, even when execution is enabled; with the flag off the
    dependency is a no-op and the 403/execute behaviour is unchanged.
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
