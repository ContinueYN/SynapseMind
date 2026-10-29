"""Solution-graph verification port (M2.5 S5).

The STRONG tier in chapter 13 §13.3 promises a *falsifiable* diagnosis. S4
showed why structure alone cannot keep that promise: a graph can be schema-valid,
acyclic, connected, evidence-complete — and still claim an answer range that is
simply wrong (`P_DERIV_003` dropped `a=0`).

So a graph may carry a ``claim`` (``domain/problem/models.VerificationClaim``),
and a verifier turns it into ``pass | fail | unknown``:

- ``pass``   — no counterexample was found by the checks that ran; this is a
                falsifier's pass, not a proof;
- ``fail``   — a concrete counterexample exists: a parameter value inside the
                declared range where the constraint breaks, or a value outside
                it where the constraint holds (the missing-boundary case);
- ``unknown``— nothing was claimed, the claim shape is not supported, or the
                numeric search could not decide. Recorded, never fatal.

The port lives here (data + Protocol) so the graph builder never imports SymPy;
the implementation is ``infrastructure/verification/sympy_verifier.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.domain.problem.models import Interval, SolutionGraph, VerificationClaim

VerificationStatus = Literal["pass", "fail", "unknown"]

VerificationReason = Literal[
    "ok",  # pass: sampled both directions without a counterexample
    "counterexample",  # fail: the answer range and the constraint disagree
    "malformed",  # fail: the claim cannot be read by the verifier
    "no_claim",  # unknown: the graph declares nothing machine-checkable
    "unsupported_kind",  # unknown: e.g. a solution set in x, not a parameter range
    "undecidable",  # unknown: the search could not reach a verdict
    "unavailable",  # unknown: no SymPy in this environment
]


@dataclass(frozen=True, slots=True)
class CounterExample:
    """The witness that makes a claim fail."""

    parameter: str
    parameter_value: str
    variable: str
    # Empty when the constraint holds for every x, i.e. the answer range is
    # too narrow and the witness is the parameter value itself.
    variable_value: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    reason: VerificationReason
    detail: str = ""
    counterexample: CounterExample | None = None
    parameter_samples: int = 0
    point_checks: int = 0

    @property
    def ok(self) -> bool:
        """``unknown`` is not a failure: it is an honest gap, recorded as such."""
        return self.status != "fail"

    def as_issue(self) -> str:
        """One feedback line for the builder's single retry."""
        return f"verification_{self.reason}: {self.detail}"


class GraphVerifier(Protocol):
    def verify(self, graph: SolutionGraph) -> VerificationResult: ...


_RELATION_SYMBOLS = {"<=": "≤", ">=": "≥", "<": "<", ">": ">"}


def describe_claim(claim: VerificationClaim) -> str:
    """One-line rendering used in counterexample messages and reports."""
    relation = _RELATION_SYMBOLS.get(claim.relation, claim.relation)
    ranges = " ∪ ".join(_render_interval(interval) for interval in claim.intervals)
    return (
        f"∀{claim.variable}∈{claim.variable_domain}: {claim.expression} {relation} 0"
        f" ⇒ {claim.parameter} ∈ {ranges}"
    )


def _render_interval(interval: Interval) -> str:
    # An unbounded side has no endpoint to include, so it always stays open.
    left = "[" if interval.lower_inclusive and interval.lower is not None else "("
    right = "]" if interval.upper_inclusive and interval.upper is not None else ")"
    lower = "−∞" if interval.lower is None else interval.lower
    upper = "+∞" if interval.upper is None else interval.upper
    return f"{left}{lower}, {upper}{right}"
