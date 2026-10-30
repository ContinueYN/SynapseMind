"""Graph verification infrastructure (M2.5 S5).

``default_verifier()`` is what the graph builder gets when it is not handed a
verifier explicitly. The SymPy-backed implementation is imported on first use, so
a build that produces no ``claim`` (or a deployment without SymPy installed)
never pays the roughly 1.7 s import.

The composition root calls ``warm()`` once at startup, so the *first* learner
whose problem carries a claim does not pay that import inside the 8s
first-question budget (measured: a refuted claim retry took 8.9 s, of which
≈1.7 s was the import). ``warm()`` is optional and idempotent; a verifier
without it is left alone.
"""

from __future__ import annotations

from synapse.application.verification import (
    CounterExample,
    GraphVerifier,
    VerificationResult,
    VerificationStatus,
    describe_claim,
)
from synapse.domain.problem.models import SolutionGraph

__all__ = [
    "CounterExample",
    "DefaultGraphVerifier",
    "GraphVerifier",
    "VerificationResult",
    "VerificationStatus",
    "default_verifier",
    "describe_claim",
]


class DefaultGraphVerifier:
    """Lazy proxy: the SymPy module is imported only when a claim exists."""

    def __init__(self) -> None:
        self._impl: GraphVerifier | None = None

    def warm(self) -> None:
        """Import SymPy now instead of during the first claim verification."""
        self._load()

    def _load(self) -> bool:
        if self._impl is not None:
            return True
        try:
            from synapse.infrastructure.verification.sympy_verifier import SymPyVerifier
        except ImportError:  # pragma: no cover - only without SymPy
            return False
        self._impl = SymPyVerifier()
        return True

    def verify(self, graph: SolutionGraph) -> VerificationResult:
        if graph.claim is None:
            return VerificationResult(
                status="unknown",
                reason="no_claim",
                detail="图没有 claim：答案不是可形式化的参数区间，本次不做数学验证",
            )
        if not self._load():  # pragma: no cover - only without SymPy
            return VerificationResult(
                status="unknown",
                reason="unavailable",
                detail="当前环境没有 SymPy，claim 未验证",
            )
        assert self._impl is not None
        return self._impl.verify(graph)


def default_verifier() -> GraphVerifier:
    return DefaultGraphVerifier()
