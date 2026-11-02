"""Explicit code execution mapper."""

from __future__ import annotations

from synapse.api.schemas.execution import ExecutionFindingOut, ExecutionOut
from synapse.application.execution.service import ExecutionResult


def execution_out(result: ExecutionResult) -> ExecutionOut:
    return ExecutionOut(
        version="0.1",
        status=result.status,
        detail=result.detail,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        truncated=result.truncated,
        findings=[
            ExecutionFindingOut(code=finding.code, message=finding.message)
            for finding in result.findings
        ],
    )
