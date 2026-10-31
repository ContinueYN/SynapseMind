from __future__ import annotations

import json
from pathlib import Path

import pytest

from synapse.domain.problem.alignment import (
    CompositeAligner,
    RuleBasedAligner,
    TypeCueAligner,
)
from synapse.domain.problem.models import (
    Problem,
    SolutionGraph,
    SolutionNode,
    StudentAttempt,
)
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
        answer="a∈[1/e,+∞)",
        work=(
            "定义域 x>0。f'(x)=1/x-a，最大值为 f(1/a)。"
            "a≤0 时函数无上界，排除；a>0 时 -ln a-1≤0。"
            "综上只保留 a≥1/e。"
        ),
    )
    result = RuleBasedAligner().align(SAMPLE_PROBLEM, attempt)
    assert result.first_divergence == "none"
    assert result.missing_node_ids == ()


# --- M2.5 S5 ②: graph-derived alignment for generated graphs ---------------


def _generated(*nodes: tuple[str, str]) -> Problem:
    """A graph with the shape the generator produces (n1.. in order)."""

    return Problem(
        id="gen:demo",
        title="生成的题",
        text="已知函数 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的范围。",
        annotated=False,
        graph=SolutionGraph(
            problem_id="gen:demo",
            version="v1",
            stem="g(x)=x^2-a x+1>0",
            nodes=tuple(
                SolutionNode(id=f"n{index}", type=node_type, text=text)
                for index, (node_type, text) in enumerate(nodes, start=1)
            ),
            edges=(),
        ),
    )


DEMO = _generated(
    ("READ", "确认条件：对所有 x∈R 成立。"),
    ("CONDITION", "按开口方向与判别式分类讨论。"),
    ("COMPUTE", "算判别式 Δ=a^2-4<0。"),
    ("CHECK", "检验端点 a=±2 是否可取。"),
)


def test_a_generated_graph_diverges_at_the_first_unmentioned_step() -> None:
    attempt = StudentAttempt(answer="a∈(-2,2)", work="题目要求对所有 x∈R 成立。")

    result = TypeCueAligner().align(DEMO, attempt)

    # "恒成立/所有 x" is a READ cue; the classification step is not mentioned.
    assert result.first_divergence == "n2"
    assert result.matched_node_ids == ("n1",)
    assert any("分类讨论" in item for item in result.evidence)


def test_the_evidence_only_reports_omission_never_a_wrong_step() -> None:
    """Presence checking cannot grade a step, so the wording must not either."""

    attempt = StudentAttempt(answer="a∈(-2,2)", work="定义域是 R。")

    result = TypeCueAligner().align(DEMO, attempt)

    assert result.evidence
    assert all("没有出现" in item for item in result.evidence)


def test_a_blank_attempt_starts_at_the_first_node() -> None:
    attempt = StudentAttempt(answer="不会", self_report="no_idea")

    result = TypeCueAligner().align(DEMO, attempt)

    assert result.first_divergence == "n1"
    assert result.missing_node_ids == ("n1", "n2", "n3", "n4")
    assert "完全不会" in result.evidence[0]


def test_a_complete_solution_has_no_gap() -> None:
    attempt = StudentAttempt(
        answer="a∈(-2,2)",
        work=(
            "题目要求对所有 x∈R 成立。按开口方向与判别式分类讨论："
            "Δ=a^2-4<0，解得 -2<a<2。检验端点 a=±2 时 Δ=0，不满足，排除。"
        ),
    )

    result = TypeCueAligner().align(DEMO, attempt)

    assert result.first_divergence == "none"
    assert result.missing_node_ids == ()


def test_any_formula_counts_as_touching_a_compute_step() -> None:
    """A student who computes without naming the operation still computed."""

    problem = _generated(("COMPUTE", "求导数并令它等于零。"))
    attempt = StudentAttempt(answer="", work="f'(x)=2x-a=0")

    result = TypeCueAligner().align(problem, attempt)

    assert result.first_divergence == "none"


def test_a_two_sided_parameter_split_counts_as_case_analysis() -> None:
    """The g-009 lesson: splitting cases without writing 分类 must still count."""

    problem = _generated(("CONDITION", "按参数分类。"))
    attempt = StudentAttempt(
        answer="a∈(-2,2)",
        work="a<=0 时 Δ 恒小于 0，成立；a>0 时要额外检验。",
    )

    result = TypeCueAligner().align(problem, attempt)

    assert result.first_divergence == "none"


def test_one_sided_parameter_talk_is_not_a_case_split() -> None:
    problem = _generated(("CONDITION", "按参数分类。"))
    attempt = StudentAttempt(answer="a>0", work="a>0 时 Δ=a^2-4，所以 a>=2。")

    result = TypeCueAligner().align(problem, attempt)

    assert result.first_divergence == "n1"


def test_a_prose_node_can_match_by_shared_wording() -> None:
    """Generated nodes are often prose; a near-quote of the node counts."""

    problem = _generated(("STRATEGY", "把恒成立转化为最值问题。"))
    attempt = StudentAttempt(answer="", work="先把恒成立转化为最值问题，再求最大值。")

    result = TypeCueAligner().align(problem, attempt)

    assert result.first_divergence == "none"


def test_composite_aligner_sends_annotated_problems_to_the_rule_aligner() -> None:
    aligner = CompositeAligner(
        annotated=RuleBasedAligner(),
        generated=TypeCueAligner(),
    )
    seed_attempt = StudentAttempt(answer="a≥1/e", work="定义域 x>0。")
    generated_attempt = StudentAttempt(answer="a∈(-2,2)", work="题目要求对所有 x∈R 成立。")

    seed_result = aligner.align(SAMPLE_PROBLEM, seed_attempt)
    generated_result = aligner.align(DEMO, generated_attempt)

    # The seed keeps its hand-tuned rules; the generated graph never inherits
    # them (its node ids happen to look the same).
    assert seed_result.first_divergence == "n2"
    assert any("a≤0" in item for item in seed_result.evidence)
    assert generated_result.first_divergence == "n2"
    assert all("a≤0" not in item for item in generated_result.evidence)


GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden" / "golden-v0.1.jsonl"
# Public CI does not carry the private golden corpus; keep the other alignment
# tests running and skip only this labelled-work comparison.
_GOLDEN_CASES = (
    [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()]
    if GOLDEN_PATH.exists()
    else []
)
# Which layer the seed graph's node belongs to, used only to compare the two
# aligners on labelled work.
_SEED_LAYER = {"n1": "L1", "n2": "L1", "n3": "L2", "n4": "L2", "n5": "L4", "n6": "L2"}


@pytest.mark.parametrize(
    "case",
    _GOLDEN_CASES,
    ids=lambda case: case["case_id"],
)
def test_graph_derived_alignment_agrees_with_the_labelled_layer(case: dict[str, str]) -> None:
    """Sanity, not accuracy: the generated-graph heuristic on labelled work.

    The labelled cases were written for the seed problem and tuned against the
    rule aligner, so agreement here does not measure quality on a generated
    graph. It does show the heuristic is not arbitrary, and it will fail loudly
    if someone loosens a cue until every step looks covered.
    """

    attempt = StudentAttempt(answer=case["answer"], work=case["work"])
    result = TypeCueAligner().align(SAMPLE_PROBLEM, attempt)
    layer = "NONE" if result.first_divergence == "none" else _SEED_LAYER[result.first_divergence]

    assert layer == case["label_layer"], f"{case['case_id']} diverged at {result.first_divergence}"
