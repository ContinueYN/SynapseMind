"""M2.5 S3: identification is exact, not keyword-based.

The regression these tests pin down: M1 accepted any text containing ``ln``,
so a *different* derivative problem was diagnosed with the seed graph.
"""

from __future__ import annotations

from dataclasses import replace

from synapse.domain.problem.identification import (
    TextProblemIdentifier,
    normalize_problem_text,
)
from synapse.infrastructure.seed import SAMPLE_PROBLEM

IDENTIFIER = TextProblemIdentifier({SAMPLE_PROBLEM.id: SAMPLE_PROBLEM})


def test_accepts_the_annotated_problem() -> None:
    assert IDENTIFIER.identify(SAMPLE_PROBLEM.text) == SAMPLE_PROBLEM.id


def test_accepts_cosmetic_variants() -> None:
    variants = [
        SAMPLE_PROBLEM.text.replace(" ", ""),
        f"  {SAMPLE_PROBLEM.text}\n",
        f"这题怎么做？{SAMPLE_PROBLEM.text}",
        SAMPLE_PROBLEM.text.replace("f(x)=ln x", r"$f(x)=\ln x$"),
        SAMPLE_PROBLEM.text.replace("，", ","),
    ]
    for text in variants:
        assert IDENTIFIER.identify(text) == SAMPLE_PROBLEM.id, text


def test_rejects_a_different_problem_that_shares_keywords() -> None:
    other = "已知函数 f(x)=ln x - a x，求 f(x) 的单调区间。"
    assert IDENTIFIER.identify(other) is None


def test_rejects_a_truncated_paste() -> None:
    assert IDENTIFIER.identify(SAMPLE_PROBLEM.text[:20]) is None


def test_rejects_empty_short_or_non_math_text() -> None:
    assert IDENTIFIER.identify("") is None
    assert IDENTIFIER.identify("   ") is None
    assert IDENTIFIER.identify("求导") is None
    assert IDENTIFIER.identify("阅读下面的文字，完成后面的题目。") is None


def test_longest_catalog_entry_wins() -> None:
    short = replace(SAMPLE_PROBLEM, id="P_SHORT", text="abc def ghi jkl mno pqr")
    long = replace(SAMPLE_PROBLEM, id="P_LONG", text="abc def ghi jkl mno pqr stu")
    identifier = TextProblemIdentifier({"P_SHORT": short, "P_LONG": long})

    assert identifier.identify(long.text) == "P_LONG"
    assert identifier.identify(short.text) == "P_SHORT"


def test_normalisation_folds_case_space_and_punctuation() -> None:
    assert normalize_problem_text("F(X) = LN X。") == normalize_problem_text("f(x)=lnx")
