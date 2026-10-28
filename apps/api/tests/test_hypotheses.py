from __future__ import annotations

from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.problem.models import AlignmentResult


def _alignment() -> AlignmentResult:
    return AlignmentResult(
        first_divergence="n3",
        matched_node_ids=("n1", "n2", "n5"),
        missing_node_ids=("n3", "n6"),
        evidence=("没有单独检查 a≤0 / a=0 的边界",),
        excluded=("定义域", "导数与最值计算"),
    )


def test_priors_favour_parameter_case() -> None:
    hs = HypothesisSet.from_alignment(_alignment())
    assert hs.top()[0] == "H_L2"
    assert abs(sum(hs.posteriors().values()) - 1) < 1e-9


def test_two_discriminating_answers_converge() -> None:
    hs = HypothesisSet.from_alignment(_alignment())
    hs.observe("p_a0_derivative", "A")
    hs.observe("p_boundary_check", "A")
    decision = hs.decide(turn=2, max_turns=6)
    assert decision.kind == "diagnose"
    assert decision.confidence >= 0.80
    assert hs.top()[0] == "H_L2"


def test_turn_limit_below_threshold_stops() -> None:
    hs = HypothesisSet.from_alignment(_alignment())
    hs.observe("p_a0_derivative", "C")
    hs.observe("p_a0_derivative", "C")
    decision = hs.decide(turn=6, max_turns=6)
    assert decision.kind in {"stop", "diagnose"}


def test_unknown_does_not_treat_as_wrong_option() -> None:
    hs = HypothesisSet.from_alignment(_alignment())
    before = hs.posteriors()["H_L1"]
    hs.observe_unknown("p_a0_derivative")
    assert hs.posteriors()["H_L1"] > before
