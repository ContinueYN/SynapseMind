"""等式链校验（M2.5 S5 ⑥）：学生自己写的等号，机器能判它对不对。"""

from __future__ import annotations

import pytest

from synapse.infrastructure.verification.equalities import check_work
from synapse.infrastructure.verification.notation import parse

# 真实学生原话（`eval/problems/student-answers-pub-v0.1.jsonl`，`source=public-web`）。
REAL_LIMIT_WORK = "=lim[sinX/(X+sinX/cosX)] =lim[sinX/X +cosX] =1+1 =2，有哪里错了么"
REAL_FRUSTUM_WORK = (
    "根号下（80/245）=h台/h锥=4/7，∴h台=20cm，V台套公式 1/3（245+80+根号（245*80））X20=3100cm^3"
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("2x+1", "2*x + 1"),
        ("x^2", "x**2"),
        ("x²", "x**2"),
        ("sinX", "sin(x)"),
        ("（x+1）（x-1）", "(x + 1)*(x - 1)"),
        ("根号（16）", "4"),
        ("√2", "sqrt(2)"),
        ("根号2", "sqrt(2)"),
        ("√2/2", "sqrt(2)/2"),
    ],
)
def test_student_notation_is_translated(source: str, expected: str) -> None:
    value = parse(source)
    assert value is not None
    assert str(value) == str(parse(expected))


@pytest.mark.parametrize("source", ["h台/h锥", "有哪里错了么", "", "an", "x20", "√2x"])
def test_unreadable_notation_returns_none(source: str) -> None:
    assert parse(source) is None


def test_identity_chain_that_holds_has_no_finding() -> None:
    report = check_work("（x+1）² = x²+2x+1 = x²+2x+1")
    assert report.findings == []
    assert report.checked == 2


def test_wrong_identity_reports_a_counterexample() -> None:
    report = check_work("x+1=2x")
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.kind == "identity"
    assert "x=" in finding.counterexample


def test_numeric_chain_is_compared_by_value() -> None:
    report = check_work("1+1=3")
    assert len(report.findings) == 1
    assert "左边 2" in report.findings[0].counterexample


def test_real_student_limit_chain_catches_the_broken_equality() -> None:
    """真实学生原话：把分母里的 sinX/cosX 拆开，这一步不成立。"""

    report = check_work(REAL_LIMIT_WORK)
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.kind == "limit"
    # 正确答案是 1/2，学生算出 2；两边极限不同是这一步错的可机器复算的证据。
    assert "0.5" in finding.counterexample
    assert "2" in finding.counterexample
    # The card quotes this exact sentence; it is built where the numbers are known.
    assert finding.summary == "x→0 时左边极限 0.5、右边 2"


def test_correct_limit_chain_is_not_flagged() -> None:
    report = check_work("=lim[sinX/(X+tanX)] =lim[1/(1+1/cosX)] =1/2")
    assert report.findings == []


def test_bare_radical_is_read_when_unambiguous() -> None:
    report = check_work("√2/2 = 1/√2")
    assert report.findings == []
    assert report.checked == 1


def test_unreadable_heights_do_not_produce_a_false_alarm() -> None:
    """`根号下（80/245）` 被截成 `80/245` 就会把学生正确的一步判错——必须跳过。"""

    report = check_work(REAL_FRUSTUM_WORK)
    assert report.findings == []
    assert report.skipped.get("notation_unsupported", 0) >= 1


def test_single_assignment_is_not_judged() -> None:
    report = check_work("x=2")
    assert report.findings == []


def test_definition_with_another_symbol_is_not_judged() -> None:
    report = check_work("a=3^(n-1)")
    assert report.findings == []
