"""Phase 1b: the existing FORMAL/EMPIRICAL checks behind generic claims.

The adapters are intentionally thin, so these tests focus on the boundary the
product cares about: a real check can ``pass``/``fail``, and a claim that the
checker cannot read is ``unknown`` — never a silent pass.
"""

from __future__ import annotations

import pytest

from synapse.domain.problem.claims import Interval, VerificationClaim
from synapse.domain.problem.generic import EmpiricalClaim
from synapse.infrastructure.verification import (
    default_empirical_verifier,
    default_formal_verifier,
)

# The same claim shape the solution-graph verifier tests already pin: for
# f(x)=e^x−a x, f(x)≥0 for all x iff a∈[0,e].
CORRECT = VerificationClaim(
    kind="parameter_range",
    parameter="a",
    variable="x",
    variable_domain="(-inf,+inf)",
    expression="exp(x) - a*x",
    relation=">=",
    intervals=(Interval(lower="0", upper="E", lower_inclusive=True, upper_inclusive=True),),
)


def test_a_correct_parameter_range_has_no_counterexample() -> None:
    result = default_formal_verifier().verify(CORRECT)

    assert result.kind == "formal"
    assert result.status == "pass", result.detail
    assert "两个方向都未发现反例" in result.detail


def test_a_too_wide_range_fails_with_a_concrete_counterexample() -> None:
    claim = VerificationClaim(
        kind="parameter_range",
        parameter="a",
        variable="x",
        variable_domain="(-inf,+inf)",
        expression="exp(x) - a*x",
        relation=">=",
        intervals=(Interval(lower="-1", upper="E", lower_inclusive=True),),
    )

    result = default_formal_verifier().verify(claim)

    assert result.status == "fail"
    assert "反例" in result.detail


def test_an_unsupported_claim_is_unknown_not_a_pass() -> None:
    claim = VerificationClaim(
        kind="solution_set",
        parameter="a",
        variable="x",
        variable_domain="(-inf,+inf)",
        expression="x^2 - a*x + 1",
        relation=">",
        intervals=(Interval(lower="-2", upper="2"),),
    )

    result = default_formal_verifier().verify(claim)

    assert result.status == "unknown"
    assert result.detail


def test_a_dimensionally_consistent_empirical_claim_passes() -> None:
    claim = EmpiricalClaim(
        equation="F*cos(theta) - mu*N = m*a",
        units={
            "F": "N",
            "theta": "deg",
            "mu": "",
            "N": "N",
            "m": "kg",
            "a": "m/s^2",
        },
        values={"F": 10, "theta": 60, "mu": 0.2, "N": 10, "m": 2, "a": 1.5},
    )

    result = default_empirical_verifier().verify(claim)

    assert result.kind == "empirical"
    assert result.status == "pass", result.detail
    assert "量纲一致" in result.detail


def test_a_dimension_mismatch_fails_with_both_sides() -> None:
    claim = EmpiricalClaim(
        equation="F = q/E",
        units={"F": "N", "q": "C", "E": "N/C"},
        values={"F": 1, "q": 1, "E": 1},
    )

    result = default_empirical_verifier().verify(claim)

    assert result.status == "fail"
    assert "量纲不一致" in result.detail


def test_an_expression_without_a_unit_cannot_be_built() -> None:
    with pytest.raises(ValueError):
        EmpiricalClaim(expression="v", units={"v": "m/s"})
