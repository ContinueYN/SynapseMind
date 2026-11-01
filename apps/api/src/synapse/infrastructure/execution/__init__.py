"""Phase 2 local execution adapter."""

from __future__ import annotations

from synapse.infrastructure.execution.python_runner import (
    ExecutionLimits,
    LocalPythonExecutor,
)

__all__ = ["ExecutionLimits", "LocalPythonExecutor"]
