from __future__ import annotations

from synapse.domain.guard.leak import AnswerLeakGuard


def test_guard_blocks_final_range() -> None:
    guard = AnswerLeakGuard(
        forbidden=("1/e",),
        reference_solution="a∈(-∞,0]∪[1/e,∞)",
    )
    assert guard.find("所以 a≥1/e") != ()
    assert guard.find("a 的最终范围是 (-∞,0]∪[1/e,∞)") != ()


def test_guard_allows_pedagogical_question() -> None:
    guard = AnswerLeakGuard(
        forbidden=("1/e",),
        reference_solution="a∈(-∞,0]∪[1/e,∞)",
    )
    assert guard.find("a=0 时，f'(x)=1/x 在 x>0 上有零点吗？") == ()
    assert guard.find("a≤0 这一支要不要单独检查？") == ()


def test_guard_reports_rule_name() -> None:
    guard = AnswerLeakGuard(forbidden=("1/e",))
    hit = guard.find("答案就是 1/e")[0]
    assert hit.rule == "forbidden_token"
