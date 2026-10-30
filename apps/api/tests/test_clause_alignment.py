"""M2.5 S8: clause-level existence matching for prose-heavy NONE-tier graphs.

The S7 report recorded the gap: a Chinese node is often one long sentence made
of two or three answer actions, and the whole-sentence 3-gram backstop called a
student who wrote only the first action ``missing``. These tests pin the middle
answer (``partial``) and, just as important, pin what must *not* become partial:
a generic answer, a short fragment, or a type cue that already covers the node.

The clause aligner is an existence check. ``partial`` means "the first half of
this step appears in the work", never "half correct".
"""

from __future__ import annotations

from synapse.domain.problem.alignment import ClauseCueAligner, TypeCueAligner
from synapse.domain.problem.models import (
    Problem,
    SolutionGraph,
    SolutionNode,
    StudentAttempt,
)

TWO_CLAUSES = "判定题型为物象作用题，明确从内容、结构、情感三角度作答"


def _problem(text: str, node_type: str = "CONDITION") -> Problem:
    return Problem(
        id="gen:clause",
        title="分句测试",
        text="阅读下面的文字，完成题目。",
        annotated=False,
        graph=SolutionGraph(
            problem_id="gen:clause",
            version="v1",
            stem="阅读下面的文字，完成题目。",
            nodes=(SolutionNode(id="n1", type=node_type, text=text),),
            edges=(),
        ),
    )


def test_one_clause_is_partial_not_missing() -> None:
    attempt = StudentAttempt(
        answer="答：分析作用。",
        work="判定这是散文物象作用题，打算从内容和结构两方面答。",
    )

    result = ClauseCueAligner().align(_problem(TWO_CLAUSES), attempt)

    assert result.first_divergence == "n1"
    assert result.matched_node_ids == ()
    assert result.missing_node_ids == ()
    assert result.partial_node_ids == ("n1",)
    assert result.evidence
    assert "只写到了" in result.evidence[0]
    assert "的一部分" in result.evidence[0]


def test_all_clauses_is_covered() -> None:
    attempt = StudentAttempt(
        answer="答：分析作用。",
        work="判定题型为物象作用题，明确从内容、结构、情感三角度作答。",
    )

    result = ClauseCueAligner().align(_problem(TWO_CLAUSES), attempt)

    assert result.first_divergence == "none"
    assert result.matched_node_ids == ("n1",)
    assert result.partial_node_ids == ()


def test_a_generic_answer_is_not_partial() -> None:
    """No shared wording means missing; the matcher must not invent coverage."""

    attempt = StudentAttempt(answer="写了，但拿不准。", work="写了，但拿不准。")

    result = ClauseCueAligner().align(_problem(TWO_CLAUSES), attempt)

    assert result.first_divergence == "n1"
    assert result.partial_node_ids == ()
    assert result.missing_node_ids == ("n1",)
    assert "没有出现" in result.evidence[0]


def test_a_short_fragment_is_not_enough() -> None:
    """A 2-character fragment must not turn a three-action node into partial."""

    problem = _problem("分点组织语言，每点先术语后结合原文，写成完整句子", "COMPUTE")
    attempt = StudentAttempt(answer="答：写完了。", work="分点。")

    result = ClauseCueAligner().align(problem, attempt)

    assert result.first_divergence == "n1"
    assert result.partial_node_ids == ()
    assert result.missing_node_ids == ("n1",)


def test_a_type_cue_still_covers_the_node() -> None:
    problem = _problem("读题干，圈出限制语与分值", "READ")
    attempt = StudentAttempt(answer="答：先读题。", work="先读题干。")

    result = ClauseCueAligner().align(problem, attempt)

    assert result.first_divergence == "none"
    assert result.partial_node_ids == ()


def test_a_near_verbatim_quote_keeps_the_whole_node_floor() -> None:
    """The old 3-gram floor survives: near-verbatim is covered, not partial."""

    problem = _problem("把恒成立转化为最值问题，再求最大值", "STRATEGY")
    attempt = StudentAttempt(
        answer="a∈(-2,2)",
        work="先把恒成立转化为最值问题，再求最大值。",
    )

    result = ClauseCueAligner().align(problem, attempt)

    assert result.first_divergence == "none"
    assert result.partial_node_ids == ()


def test_the_two_state_aligner_still_never_reports_partial() -> None:
    """Math/physics must keep the exact result S5/S6 measured."""

    attempt = StudentAttempt(
        answer="答：分析作用。",
        work="判定这是散文物象作用题，打算从内容和结构两方面答。",
    )

    result = TypeCueAligner().align(_problem(TWO_CLAUSES), attempt)

    assert result.first_divergence == "n1"
    assert result.partial_node_ids == ()
    assert result.missing_node_ids == ("n1",)


def test_a_blank_attempt_starts_at_the_first_node() -> None:
    attempt = StudentAttempt(answer="不会", self_report="no_idea")

    result = ClauseCueAligner().align(_problem(TWO_CLAUSES), attempt)

    assert result.first_divergence == "n1"
    assert result.partial_node_ids == ()
    assert result.missing_node_ids == ("n1",)
