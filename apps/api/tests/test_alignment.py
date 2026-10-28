from __future__ import annotations

from synapse.domain.problem.alignment import RuleBasedAligner
from synapse.domain.problem.models import StudentAttempt
from synapse.infrastructure.seed import SAMPLE_PROBLEM


def test_sample_attempt_misses_parameter_case() -> None:
    attempt = StudentAttempt(
        answer="a≥1/e",
        work=(
            "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。"
            "a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。"
        ),
    )
    result = RuleBasedAligner().align(SAMPLE_PROBLEM, attempt)
    assert result.first_divergence == "n3"
    assert "n3" in result.missing_node_ids
    assert "n1" in result.matched_node_ids
    assert "n5" in result.matched_node_ids
    assert any("a≤0" in item for item in result.evidence)


def test_no_idea_starts_at_reading() -> None:
    attempt = StudentAttempt(answer="不会", self_report="no_idea")
    result = RuleBasedAligner().align(SAMPLE_PROBLEM, attempt)
    assert result.first_divergence == "n1"
    assert result.missing_node_ids == ("n1",)
    assert result.evidence


def test_complete_attempt_has_no_gap() -> None:
    attempt = StudentAttempt(
        answer="a∈(-∞,0]∪[1/e,∞)",
        work=(
            "定义域 x>0。f'(x)=1/x-a，最大值为 f(1/a)。"
            "a≤0 时函数无上界；a>0 时 -ln a-1≤0。"
            "综上合并并集，得 a≥1/e 或 a≤0。"
        ),
    )
    result = RuleBasedAligner().align(SAMPLE_PROBLEM, attempt)
    assert result.first_divergence == "none"
    assert result.missing_node_ids == ()
