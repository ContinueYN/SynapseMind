"""M2.5 S7: the structure hint, and the boundary it must not cross.

The hint is built from the alignment only. These tests pin three things:

* it reports coverage in graph order and points at the first missing step;
* it never reads a hypothesis, a posterior or a confidence — the wording has no
  place to put one;
* the payload conforms to ``specs/structure-hint.schema.json``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from synapse.api.mappers import hint_out
from synapse.application.hint_builder import DISCLAIMER, build_structure_hint
from synapse.domain.diagnosis.hypotheses import HYPOTHESES, HypothesisSet
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.problem.models import (
    AlignmentResult,
    Problem,
    SolutionGraph,
    SolutionNode,
)

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "structure-hint.schema.json"

NODE_TEXTS = (
    ("n1", "READ", "读题干，圈出限制语与分值"),
    ("n2", "CONDITION", "定位原文区间，勾出依据句"),
    ("n3", "COMPUTE", "分点组织答案，写完整句子"),
    ("n4", "CHECK", "检查扣题与分值对应"),
)


def _graph() -> SolutionGraph:
    return SolutionGraph(
        problem_id="P_CN_001",
        version="g1",
        stem="阅读下面的文字，完成后面的题目。",
        nodes=tuple(
            SolutionNode(id=node_id, type=node_type, text=text)
            for node_id, node_type, text in NODE_TEXTS
        ),
        edges=(("n1", "n2"), ("n2", "n3"), ("n3", "n4")),
    )


def _problem() -> Problem:
    return Problem(
        id="P_CN_001",
        title="现代文阅读",
        text="阅读下面的文字，完成后面的题目。",
        graph=_graph(),
        subject="chinese",
        annotated=False,
    )


def _session(alignment: AlignmentResult) -> DialogueSession:
    return DialogueSession(
        session_id="S_ABC123456789",
        problem_id="P_CN_001",
        state=DialogueState.ALIGN,
        alignment=alignment,
        hypotheses=HypothesisSet.from_alignment(alignment, focus="L1"),
        max_turns=6,
        created_at=datetime(2026, 10, 30, tzinfo=UTC),
    )


def _partial_alignment() -> AlignmentResult:
    return AlignmentResult(
        first_divergence="n2",
        matched_node_ids=("n1",),
        missing_node_ids=("n2", "n3", "n4"),
        evidence=("过程里没有出现「定位原文区间，勾出依据句」这一步",),
    )


def _half_written_alignment() -> AlignmentResult:
    return AlignmentResult(
        first_divergence="n2",
        matched_node_ids=("n1",),
        missing_node_ids=("n3", "n4"),
        evidence=("过程里只写到了「定位原文区间，勾出依据句」的一部分",),
        partial_node_ids=("n2",),
    )


def _hint(alignment: AlignmentResult | None = None) -> object:
    return build_structure_hint(
        _session(alignment or _partial_alignment()),
        _problem(),
        level="none",
    )


def test_hint_reports_coverage_in_graph_order() -> None:
    hint = build_structure_hint(_session(_partial_alignment()), _problem(), level="none")

    assert hint.subject == "chinese"
    assert hint.level == "none"
    assert [step.node_id for step in hint.steps] == ["n1", "n2", "n3", "n4"]
    assert [step.status for step in hint.steps] == ["covered", "missing", "missing", "missing"]
    assert [step.node_id for step in hint.covered] == ["n1"]
    assert [step.node_id for step in hint.missing] == ["n2", "n3", "n4"]
    assert hint.covered[0].text == "读题干，圈出限制语与分值"


def test_focus_is_the_first_missing_step_not_a_verdict() -> None:
    hint = build_structure_hint(_session(_partial_alignment()), _problem(), level="none")

    assert hint.focus_node_id == "n2"
    assert "n2" not in hint.one_line
    assert "定位原文区间，勾出依据句" in hint.one_line
    # "下一步先看哪里", never "你卡在这里".
    assert "先补上" in hint.next_step
    assert "卡" not in hint.one_line + hint.next_step


def test_a_half_written_step_has_its_own_status() -> None:
    hint = build_structure_hint(_session(_half_written_alignment()), _problem(), level="none")

    assert [step.status for step in hint.steps] == [
        "covered",
        "partial",
        "missing",
        "missing",
    ]
    assert [step.node_id for step in hint.partial] == ["n2"]
    assert [step.node_id for step in hint.missing] == ["n3", "n4"]
    assert hint.focus_node_id == "n2"
    assert "只写到了" in hint.one_line
    assert "一部分" in hint.one_line
    assert "补全" in hint.next_step
    # Still coverage, never "你错了".
    assert "错" not in hint.one_line + hint.next_step


def test_a_fully_covered_process_has_no_focus() -> None:
    alignment = AlignmentResult(
        first_divergence="none",
        matched_node_ids=("n1", "n2", "n3", "n4"),
        missing_node_ids=(),
        evidence=("过程覆盖了图中每一步；本轮没有可诊断的断点。",),
    )
    hint = build_structure_hint(_session(alignment), _problem(), level="none")

    assert hint.missing == ()
    assert hint.focus_node_id is None
    assert len(hint.covered) == 4
    assert all(step.status == "covered" for step in hint.steps)
    assert "每一步都提到了" in hint.one_line


def test_hint_never_mentions_a_hypothesis_or_a_confidence() -> None:
    """If it read the posterior, this is where it would leak into the text."""

    hint = build_structure_hint(_session(_partial_alignment()), _problem(), level="none")
    spoken = " ".join(
        [hint.one_line, hint.next_step, hint.disclaimer] + [step.text for step in hint.steps]
    )

    for hypothesis_id in HYPOTHESES:
        assert hypothesis_id not in spoken
    for hypothesis in HYPOTHESES.values():
        assert hypothesis.label not in spoken
    for word in ("置信", "把握", "概率", "卡点", "假设"):
        # The disclaimer is allowed to say "不定位卡点" — that is a negation, and
        # it is the sentence that keeps the output honest.
        if word in spoken:
            assert word in hint.disclaimer and "不" in hint.disclaimer
    assert hint.disclaimer == DISCLAIMER


def test_the_payload_conforms_to_the_published_spec() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    payloads: list[dict[str, Any]] = []

    for alignment in (_partial_alignment(), _half_written_alignment()):
        hint = build_structure_hint(_session(alignment), _problem(), level="none")
        payload = hint_out(hint).model_dump(mode="json", exclude_none=False)
        errors = sorted(Draft202012Validator(spec).iter_errors(payload), key=str)

        assert not errors, [error.message for error in errors]
        assert payload["version"] == "0.2"
        assert payload["level"] == "none"
        # A card field must not be reachable through the hint payload.
        for forbidden in ("confidence", "layer", "next_action", "verify"):
            assert forbidden not in payload
        payloads.append(payload)

    assert [step["status"] for step in payloads[0]["steps"]] == [
        "covered",
        "missing",
        "missing",
        "missing",
    ]
    assert [step["status"] for step in payloads[1]["steps"]] == [
        "covered",
        "partial",
        "missing",
        "missing",
    ]
