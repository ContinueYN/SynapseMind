"""M2.5 S5: a graph's answer range must be falsifiable.

S4's review found the failure this module exists for: a schema-valid graph can
claim a wrong range (``P_DERIV_003`` dropped ``a=0``). The verifier is a
falsifier, so the tests are written the same way — each one hands it a claim and
asserts either a counterexample or the absence of one.
"""

from __future__ import annotations

from dataclasses import replace

from synapse.application.verification import describe_claim
from synapse.domain.problem.models import (
    Interval,
    SolutionGraph,
    SolutionNode,
    VerificationClaim,
)
from synapse.infrastructure.seed import SAMPLE_CLAIM, SAMPLE_PROBLEM
from synapse.infrastructure.verification.sympy_verifier import SymPyVerifier

VERIFIER = SymPyVerifier()

EXP_SAMPLE = VerificationClaim(
    kind="parameter_range",
    parameter="a",
    variable="x",
    variable_domain="(-inf,+inf)",
    expression="exp(x) - a*x",
    relation=">=",
    intervals=(Interval(lower="0", upper="E", lower_inclusive=True, upper_inclusive=True),),
)


def _graph(claim: VerificationClaim | None) -> SolutionGraph:
    return SolutionGraph(
        problem_id="P_DERIV_003",
        version="g1",
        stem="若 f(x)=e^x-a x≥0 对任意 x∈R 恒成立，求 a 的范围。",
        nodes=(SolutionNode(id="n1", type="READ", text="读题"),),
        edges=(),
        claim=claim,
    )


def test_the_seed_claim_has_no_counterexample() -> None:
    result = VERIFIER.verify(SAMPLE_PROBLEM.graph)

    assert result.status == "pass"
    assert result.reason == "ok"
    assert result.counterexample is None
    assert result.parameter_samples > 0
    assert result.point_checks > 0


def test_the_old_wrong_seed_answer_is_falsified() -> None:
    # This is the answer the seed problem shipped before 2026-10-29:
    # a∈(-∞,0]∪[1/e,∞). a=-1 makes ln x + x → +∞, so it cannot be included.
    claim = replace(
        SAMPLE_CLAIM,
        intervals=(
            Interval(lower=None, upper="0", upper_inclusive=True),
            Interval(lower="1/E", upper=None, lower_inclusive=True),
        ),
    )

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"
    assert result.reason == "counterexample"
    assert result.counterexample is not None
    # The witness is a parameter value the answer wrongly includes, and a
    # concrete x where the constraint breaks.
    assert float(result.counterexample.parameter_value) <= 0
    assert result.counterexample.variable_value
    assert "在答案区间内" in result.detail


def test_the_missing_zero_boundary_is_falsified() -> None:
    # The exact S4 failure: the true range is [0, e], the graph said (0, e].
    # a=0 satisfies e^x ≥ 0, so excluding it is wrong.
    claim = replace(EXP_SAMPLE, intervals=(Interval(lower="0", upper="E", lower_inclusive=False),))

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"
    assert result.counterexample is not None
    assert result.counterexample.parameter_value == "0"
    assert "漏" in result.detail


def test_the_correct_closed_range_passes() -> None:
    result = VERIFIER.verify(_graph(EXP_SAMPLE))

    assert result.status == "pass"


def test_a_range_that_includes_a_failing_parameter_is_falsified() -> None:
    # For a<0 the expression tends to −∞ as x→−∞, so no negative a works.
    claim = replace(
        EXP_SAMPLE,
        intervals=(Interval(lower="-1", upper="E", lower_inclusive=True, upper_inclusive=True),),
    )

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"
    assert result.counterexample is not None
    assert float(result.counterexample.parameter_value) < 0


def test_an_answer_covering_the_whole_line_is_still_checked() -> None:
    claim = replace(EXP_SAMPLE, intervals=(Interval(lower=None, upper=None),))

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"


def test_a_graph_without_a_claim_is_unknown_not_failed() -> None:
    result = VERIFIER.verify(_graph(None))

    assert result.status == "unknown"
    assert result.reason == "no_claim"
    assert result.ok is True


def test_an_unsupported_claim_kind_is_unknown() -> None:
    result = VERIFIER.verify(_graph(replace(EXP_SAMPLE, kind="solution_set")))

    assert result.status == "unknown"
    assert result.reason == "unsupported_kind"


def test_an_expression_with_an_undeclared_symbol_is_malformed() -> None:
    claim = replace(EXP_SAMPLE, expression="exp(x) - b*x")

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"
    assert result.reason == "malformed"
    assert "b" in result.detail


def test_parsing_never_reaches_python_builtins() -> None:
    # The expression string comes from a model. It is parsed, never executed.
    claim = replace(EXP_SAMPLE, expression="__import__('os')")

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "fail"
    assert result.reason == "malformed"


def test_lowercase_e_is_read_as_eulers_number() -> None:
    claim = replace(EXP_SAMPLE, expression="e^x - a x")

    result = VERIFIER.verify(_graph(claim))

    assert result.status == "pass"


def test_log_base_notation_is_supported() -> None:
    # log_2(x) - a ≤ 0 for all x>0 has no solution set that is a range; the
    # point is that the parser reads the base notation instead of failing.
    claim = replace(
        EXP_SAMPLE,
        expression="log_2(x) - a",
        variable_domain="(0,+inf)",
        relation="<=",
        intervals=(Interval(lower="1.5849625007211563", upper=None),),
    )

    result = VERIFIER.verify(_graph(claim))

    assert result.reason != "malformed"


def test_reversed_and_overlapping_intervals_are_malformed() -> None:
    reversed_claim = replace(EXP_SAMPLE, intervals=(Interval(lower="3", upper="1"),))
    overlapping = replace(
        EXP_SAMPLE,
        intervals=(
            Interval(lower="0", upper="2"),
            Interval(lower="1", upper="3"),
        ),
    )

    for claim in (reversed_claim, overlapping):
        result = VERIFIER.verify(_graph(claim))
        assert result.status == "fail"
        assert result.reason == "malformed"


def test_a_domain_with_a_closed_infinity_is_malformed() -> None:
    result = VERIFIER.verify(_graph(replace(EXP_SAMPLE, variable_domain="(0,+inf]")))

    assert result.status == "fail"
    assert result.reason == "malformed"


def test_the_failure_is_reported_as_a_retry_issue() -> None:
    claim = replace(EXP_SAMPLE, intervals=(Interval(lower="0", upper="E", lower_inclusive=False),))
    result = VERIFIER.verify(_graph(claim))

    issue = result.as_issue()

    assert issue.startswith("verification_counterexample: ")
    assert "a=0" in issue


def test_verification_is_deterministic() -> None:
    first = VERIFIER.verify(SAMPLE_PROBLEM.graph)
    second = VERIFIER.verify(SAMPLE_PROBLEM.graph)

    assert first == second


def test_describe_claim_keeps_infinity_open() -> None:
    assert describe_claim(SAMPLE_CLAIM) == "∀x∈(0,+inf): log(x) - a*x ≤ 0 ⇒ a ∈ [1/E, +∞)"
    assert describe_claim(EXP_SAMPLE) == "∀x∈(-inf,+inf): exp(x) - a*x ≥ 0 ⇒ a ∈ [0, E]"
