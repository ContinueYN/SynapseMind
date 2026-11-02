"""Explicit code execution DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from synapse.api.schemas.common import StrictModel


class ExecutionRequestIn(StrictModel):
    """Only explicit code; the executor never extracts code from a problem."""

    language: Literal["python"]
    code: str = Field(min_length=1, max_length=20000)
    tests: str = Field(default="", max_length=20000)


class ExecutionFindingOut(StrictModel):
    code: Literal[
        "forbidden_import",
        "forbidden_call",
        "forbidden_attribute",
        "syntax_error",
        "too_large",
        "sandbox_unavailable",
    ]
    message: str = Field(min_length=1, max_length=300)


class ExecutionOut(StrictModel):
    version: Literal["0.1"]
    status: Literal["pass", "fail", "timeout", "rejected"]
    detail: str = Field(max_length=1000)
    exit_code: int | None
    duration_ms: int = Field(ge=0, le=60000)
    stdout: str = Field(max_length=32000)
    stderr: str = Field(max_length=32000)
    truncated: bool
    findings: list[ExecutionFindingOut] = Field(max_length=5)
