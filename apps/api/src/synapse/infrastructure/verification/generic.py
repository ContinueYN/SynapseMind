"""FORMAL/EMPIRICAL adapters for the generic problem graph (Phase 1b).

Both adapters are thin on purpose: the checks already exist and are already
tested. What changes is the input — a generic graph carries its claim directly
(``GenericGraph.formal`` / ``GenericGraph.empirical``) instead of a solution
graph. The adapters translate that claim, call the existing verification, and
map the result into :class:`ClaimCheck`.

Neither adapter may invent a verdict:

* no claim -> ``unknown`` (the caller normally does not even call us);
* a verifier that raises -> ``unknown`` with the exception type, never ``pass``;
* the physics checker's own ``unknown`` (missing symbol, unreadable unit) is
  passed through unchanged.
"""

from __future__ import annotations

from synapse.application.diagnosis.verification import GraphVerifier, VerificationResult
from synapse.application.shared.subject import StudentStep
from synapse.domain.problem.claims import VerificationClaim
from synapse.domain.problem.generic import ClaimCheck, EmpiricalClaim
from synapse.domain.problem.models import SolutionGraph
from synapse.infrastructure.verification.physics_units import verify_step


class FormalVerifier:
    """Adapt a generic formal claim to the SymPy parameter-range falsifier."""

    def __init__(self, verifier: GraphVerifier | None = None) -> None:
        self._verifier = verifier

    def warm(self) -> None:
        """Import SymPy before a learner waits for it; optional and idempotent."""

        verifier = self._resolve()
        warm = getattr(verifier, "warm", None)
        if callable(warm):
            warm()

    def _resolve(self) -> GraphVerifier:
        if self._verifier is None:
            # Imported here, not at module import: the proxy is what keeps
            # SymPy's ~1.7s import out of a process that never verifies.
            from synapse.infrastructure.verification import default_verifier

            self._verifier = default_verifier()
        return self._verifier

    def verify(self, claim: VerificationClaim) -> ClaimCheck:
        try:
            result = self._resolve().verify(
                SolutionGraph(
                    problem_id="P_GENERIC",
                    version="g1",
                    stem="",
                    nodes=(),
                    edges=(),
                    claim=claim,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a verifier bug is not a pass
            return ClaimCheck(
                kind="formal",
                status="unknown",
                detail=f"形式验证器无法运行（{type(exc).__name__}）；本次不把 claim 当作已检查。",
            )
        return ClaimCheck(kind="formal", status=result.status, detail=_formal_detail(result))


class EmpiricalVerifier:
    """Adapt a generic empirical claim to the physics unit/numeric replay."""

    def verify(self, claim: EmpiricalClaim) -> ClaimCheck:
        data: dict[str, object] = {
            "units": dict(claim.units),
            "values": dict(claim.values),
        }
        if claim.equation is not None:
            data["equation"] = claim.equation
        else:
            data["expression"] = claim.expression
            data["unit"] = claim.unit or ""
        try:
            verdict = verify_step(StudentStep(node_id="", text="", data=data))
        except Exception as exc:  # noqa: BLE001 - a verifier bug is not a pass
            return ClaimCheck(
                kind="empirical",
                status="unknown",
                detail=f"经验验证器无法运行（{type(exc).__name__}）；本次未做量纲检查。",
            )
        detail = verdict.detail or "经验验证器没有给出说明。"
        return ClaimCheck(kind="empirical", status=verdict.status, detail=detail)


def _formal_detail(result: VerificationResult) -> str:
    detail = result.detail or "形式验证器没有给出说明。"
    counter = result.counterexample
    if counter is not None and counter.detail and counter.detail not in detail:
        detail = f"{detail}；反例：{counter.detail}"
    return detail
