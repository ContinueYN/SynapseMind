"""Diagnosis card: annotated (hand-written) vs generated (graph-derived)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from synapse.application.card_builder import build_diagnosis_card
from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.problem.models import (
    AlignmentResult,
    Probe,
    Problem,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.seed import SAMPLE_PROBLEM

EVIDENCE = {"p1": {"A": {"H_L2": 1.2}, "B": {"H_L1": 1.2}}}


def _problem(*, annotated: bool) -> Problem:
    graph = SolutionGraph(
        problem_id="gen:demo",
        version="v1",
        stem="g(x)=x^2-a x+1>0",
        nodes=(
            SolutionNode(id="n1", type="READ", text="确认条件：对所有 x∈R 成立。"),
            SolutionNode(
                id="n2",
                type="CONDITION",
                text="按 a≤0 / a>0 分类讨论。",
                probes=(
                    Probe(
                        id="p1",
                        question="a=0 这个边界要不要单独检查？",
                        options=("要，a=0 也在 a≤0 这一支里", "不要，a>0 已经覆盖"),
                        targets=("H_L2", "H_L1"),
                    ),
                ),
            ),
        ),
        edges=(("n1", "n2"),),
    )
    return Problem(
        id="gen:demo",
        title="生成的题",
        text="已知 g(x)=x^2-a x+1，求 a。",
        graph=graph,
        annotated=annotated,
    )


def _session(
    problem: Problem, *, option_id: str | None = "A", observed: bool = True
) -> DialogueSession:
    alignment = AlignmentResult(
        first_divergence="n2",
        matched_node_ids=("n1",),
        missing_node_ids=("n2",),
        evidence=("过程里没有出现「按 a≤0 / a>0 分类讨论。」这一步",),
        excluded=("确认条件：对所有 x∈R 成立。",),
    )
    session = DialogueSession(
        session_id="s1",
        problem_id=problem.id,
        state="DIAGNOSE",  # type: ignore[arg-type]
        alignment=alignment,
        hypotheses=HypothesisSet.from_alignment(alignment, evidence=EVIDENCE),
        max_turns=6,
        created_at=datetime.now(UTC),
    )
    if observed:
        session.hypotheses.observe("p1", option_id or "A")
    session.asked_probe_ids.append("p1")
    session.record_turn(
        TurnRecord(
            turn=1,
            probe_id="p1",
            question="a=0 这个边界要不要单独检查？",
            answer="要，a=0 也在 a≤0 这一支里",
            option_id=option_id,
            action="answer" if option_id else "hint",
            is_unknown=option_id is None,
        )
    )
    return session


def test_a_generated_card_quotes_the_answer_that_moved_the_posterior() -> None:
    problem = _problem(annotated=False)

    card = build_diagnosis_card(_session(problem), problem)

    assert card.node_id == "n2"
    assert "按 a≤0 / a>0 分类讨论。" in card.one_line
    assert "要，a=0 也在 a≤0 这一支里" in card.one_line
    assert card.next_action["concept_id"] == "node:n2"
    assert card.verify["item_id"] == f"verify:{problem.id}"


def test_a_generated_card_without_probe_evidence_only_reports_omission() -> None:
    """No probe moved the posterior: the card must not claim a misconception."""

    problem = _problem(annotated=False)
    session = _session(problem, option_id=None, observed=False)

    card = build_diagnosis_card(session, problem)

    assert card.node_id == "n2"
    assert "没有出现" in card.one_line
    assert any("对齐：" in item for item in card.evidence)


def test_a_generated_card_without_any_node_falls_back_to_the_graph() -> None:
    problem = _problem(annotated=False)
    session = _session(problem)
    session.alignment = AlignmentResult(
        first_divergence="none",
        matched_node_ids=("n1", "n2"),
        missing_node_ids=(),
        evidence=(),
        excluded=(),
    )
    session.hypotheses = HypothesisSet.from_alignment(session.alignment, evidence=EVIDENCE)

    card = build_diagnosis_card(session, problem)

    assert card.node_id == "n1"
    assert card.one_line


@pytest.mark.parametrize("top_option", ["A", "B"])
def test_a_generated_card_names_the_hypothesis_its_evidence_supports(top_option: str) -> None:
    problem = _problem(annotated=False)

    card = build_diagnosis_card(_session(problem, option_id=top_option), problem)

    expected = "条件转译 / 参数分类" if top_option == "A" else "概念不清：恒成立与最值"
    assert card.label == expected
    assert expected in card.one_line


def test_an_annotated_card_keeps_the_hand_written_line() -> None:
    """The seed path must not drift: S5 ② only changes generated problems."""

    session = _session(SAMPLE_PROBLEM)
    session.alignment = AlignmentResult(
        first_divergence="n3",
        matched_node_ids=("n1", "n2"),
        missing_node_ids=("n3",),
        evidence=("没有单独检查 a≤0 / a=0 的边界",),
        excluded=("定义域",),
    )
    session.hypotheses = HypothesisSet.from_alignment(session.alignment, evidence=EVIDENCE)
    session.hypotheses.observe("p1", "A")

    card = build_diagnosis_card(session, SAMPLE_PROBLEM)

    assert card.one_line.startswith("你能走完 a>0 的最值")
    assert card.next_action["task_id"] == "T_FUNC_001"
    assert card.verify["item_id"] == "V_FUNC_001"
    top_id, _ = session.hypotheses.top()
    assert card.node_id == session.hypotheses.states[top_id].hypothesis.node_id
