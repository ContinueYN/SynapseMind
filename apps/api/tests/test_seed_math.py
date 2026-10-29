"""The seed problem's answer is part of the product contract.

The seed graph is the only hand-annotated graph, and every golden case shares
it. A wrong range would not fail any dialogue test: the aligner only checks
which steps the student covered. This module evaluates the mathematical claim
directly, so the content cannot drift again without a red test.
"""

from __future__ import annotations

import sympy as sp

from synapse.infrastructure.seed import SAMPLE_ANSWER


def _global_maximum(parameter: sp.Expr) -> sp.Expr:
    """max of f(x)=ln x - parameter*x on x>0, from limits and critical points."""
    x = sp.symbols("x", positive=True)
    f = sp.log(x) - parameter * x
    derivative = sp.diff(f, x)
    critical = [
        point
        for point in sp.solveset(derivative, x, domain=sp.S.Reals)
        if point.is_real and point > 0
    ]
    candidates = [sp.limit(f, x, 0, "+"), sp.limit(f, x, sp.oo)]
    candidates += [sp.simplify(f.subs(x, point)) for point in critical]
    return max(candidates)


def test_seed_answer_excludes_the_nonpositive_branch() -> None:
    assert SAMPLE_ANSWER == "a∈[1/e,+∞)"
    # a=0 and a<0 make f(x)->+oo, so they cannot satisfy f(x)<=0 for all x>0.
    assert _global_maximum(sp.Integer(0)) > 0
    assert _global_maximum(sp.Integer(-1)) > 0


def test_seed_answer_includes_the_boundary_and_positive_branch() -> None:
    # a=1/e is the boundary: the maximum is exactly 0.
    assert _global_maximum(sp.exp(-1)) <= 0
    # Any a>1/e also satisfies the condition.
    assert _global_maximum(sp.Integer(1)) <= 0
