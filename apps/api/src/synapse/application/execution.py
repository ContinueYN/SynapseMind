"""Code execution port (Phase 2).

This is a deliberately small port: the application layer may ask for one
explicitly submitted Python program, with optional tests, to be run once. It
never decides which code to run, never pulls code out of a problem statement,
and never turns a successful run into a diagnosis or a correctness claim.

The adapter owns the actual isolation (static gate, subprocess, timeout,
memory limit, output cap). The port is synchronous because the rest of the API
is synchronous and a run is bounded to a few seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ExecutionStatus = Literal["pass", "fail", "timeout", "rejected"]
ExecutionFindingCode = Literal[
    "forbidden_import",
    "forbidden_call",
    "forbidden_attribute",
    "syntax_error",
    "too_large",
    "sandbox_unavailable",
]


@dataclass(frozen=True, slots=True)
class ExecutionFinding:
    code: ExecutionFindingCode
    message: str


@dataclass(frozen=True, slots=True)
class RunCodeCommand:
    """One explicit submission; ``tests`` is either empty or a unittest file."""

    language: Literal["python"]
    code: str
    tests: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    detail: str
    exit_code: int | None
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    findings: tuple[ExecutionFinding, ...] = field(default_factory=tuple)


class ExecutionDisabled(Exception):
    """The feature flag is off; the endpoint must say so, not fake a run."""


class ExecutionBusy(Exception):
    """Another execution is already using the single local slot."""


class CodeExecutor(Protocol):
    def run(self, command: RunCodeCommand) -> ExecutionResult: ...
