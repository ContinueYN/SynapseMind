"""T0–T2: the ``GenericReview`` contract, its composer and its honesty rules.

The fixtures pin the published v0.1 shape and the rules the composer must not
weaken:

* every finding cites at least one evidence id that exists in the same review;
  an observation with no evidence belongs in ``not_checked``;
* a decision frame has at least two options (including "什么都不做") and no
  score/rank/recommended field, while an ``execution=skipped`` card is never
  reported as a pass.

The composer tests below read a real submission into a graph with the cue
extractor, so a change in the cue table surfaces here as well. The API is not
touched: T3 wires the review in.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from synapse.application.diagnosis.domains import IntakeFramework, VerificationMode
from synapse.application.diagnosis.generic_check import StructureGap, structure_gaps
from synapse.application.diagnosis.generic_slots import CueSlotExtractor
from synapse.application.review.generic import GenericReviewComposer
from synapse.domain.problem.generic import GenericGraph, GenericNode, NodeKind
from synapse.domain.problem.generic_review import (
    EvidenceSource,
    ExecutionStatus,
    FindingSeverity,
    GenericFinding,
    GenericReview,
    ReviewExecution,
    ReviewKind,
)

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "generic-review.schema.json"
MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "synapse"
    / "domain"
    / "problem"
    / "generic_review.py"
)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "generic_review"

# Four groups; the code group has a "not executed" and a "failed" variant.
FIXTURES = {
    "writing": "writing.json",
    "decision": "decision.json",
    "code_skipped": "execution_skipped.json",
    "code_fail": "execution_fail.json",
    "unknown": "unknown.json",
}

DECISION_FORBIDDEN_KEYS = frozenset({"score", "rank", "recommended", "best"})
# T1 structure reviews may not score a submission at all.
SCORE_FORBIDDEN_KEYS = frozenset({"score", "grade", "rank"})
FORBIDDEN_COPY = ("你错了", "正确答案", "应该", "建议选")


def _load(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _review(name: str) -> GenericReview:
    return GenericReview.from_dict(_load(FIXTURES[name]))


def _all_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        keys.update(node)
        for value in node.values():
            keys |= _all_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_conforms_to_the_published_schema(schema: dict[str, Any], name: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(_load(FIXTURES[name])),
        key=lambda error: list(error.path),
    )

    assert not errors, [
        f"/{'/'.join(str(part) for part in error.path)}: {error.message}" for error in errors
    ]


@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_round_trips_through_the_model(name: str) -> None:
    payload = _load(FIXTURES[name])

    assert _review(name).to_dict() == payload


@pytest.mark.parametrize("name", FIXTURES)
def test_every_finding_cites_evidence_that_exists(name: str) -> None:
    payload = _load(FIXTURES[name])
    evidence_ids = {item["id"] for item in payload["evidence"]}

    for finding in payload["findings"]:
        assert finding["evidence_refs"]
        assert set(finding["evidence_refs"]) <= evidence_ids


def test_the_spec_is_v0_1() -> None:
    schema = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["version"]["const"] == "0.1"
    assert schema["additionalProperties"] is False
    assert _review("writing").version == "0.1"


def test_a_finding_without_evidence_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="evidence_refs"):
        GenericFinding(
            id="f1",
            kind="missing_evidence",
            label="缺证据",
            severity=FindingSeverity.NOTABLE,
            summary="只描述观察到的东西。",
            evidence_refs=(),
        )


def test_a_finding_citing_unknown_evidence_cannot_be_built() -> None:
    payload = _load("writing.json")
    payload["findings"][0]["evidence_refs"] = ["ev_missing"]

    with pytest.raises(ValueError, match="not in this review"):
        GenericReview.from_dict(payload)


def test_duplicate_evidence_ids_are_rejected() -> None:
    payload = _load("writing.json")
    payload["evidence"].append(dict(payload["evidence"][0]))

    with pytest.raises(ValueError, match="unique"):
        GenericReview.from_dict(payload)


def test_more_than_three_blocking_findings_is_rejected() -> None:
    payload = _load("writing.json")
    first = payload["findings"][0]
    payload["findings"] = [{**first, "id": f"f{index}"} for index in range(4)]

    with pytest.raises(ValueError, match="blocking"):
        GenericReview.from_dict(payload)


def test_an_unknown_version_is_rejected() -> None:
    payload = _load("writing.json")
    payload["version"] = "0.2"

    with pytest.raises(ValueError, match="version"):
        GenericReview.from_dict(payload)


def test_an_empty_graph_is_a_valid_review_with_a_next_question() -> None:
    review = _review("unknown")

    assert review.kind is ReviewKind.STRUCTURE
    assert review.findings == ()
    assert review.evidence == ()
    assert review.not_checked
    assert review.next_step.endswith("？")


def test_the_decision_fixture_offers_two_options_including_doing_nothing() -> None:
    review = _review("decision")

    assert review.kind is ReviewKind.DECISION
    assert len(review.options) >= 2
    assert any("什么都不做" in option.label for option in review.options)
    for option in review.options:
        assert option.costs
        assert option.risks
        assert option.reversible_test


def test_a_decision_never_ranks_or_recommends(schema: dict[str, Any]) -> None:
    payload = _review("decision").to_dict()

    assert not _all_keys(payload) & DECISION_FORBIDDEN_KEYS
    # The contract itself must not give a later composer a ranking field.
    option_properties = set(schema["$defs"]["option"]["properties"])
    assert not option_properties & DECISION_FORBIDDEN_KEYS


def test_the_schema_rejects_a_score_on_an_option(schema: dict[str, Any]) -> None:
    payload = _load("decision.json")
    payload["options"][0]["score"] = 0.9

    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_a_decision_with_a_single_option_is_rejected() -> None:
    payload = _load("decision.json")
    payload["options"] = payload["options"][:1]

    with pytest.raises(ValueError, match="two options"):
        GenericReview.from_dict(payload)


def test_a_decision_without_a_do_nothing_option_is_rejected() -> None:
    payload = _load("decision.json")
    payload["options"] = [
        option for option in payload["options"] if "什么都不做" not in option["label"]
    ]

    with pytest.raises(ValueError, match="什么都不做"):
        GenericReview.from_dict(payload)


def test_a_skipped_execution_is_never_reported_as_a_pass() -> None:
    review = _review("code_skipped")

    assert review.kind is ReviewKind.EXECUTION
    assert review.execution is not None
    assert review.execution.status is ExecutionStatus.SKIPPED
    assert review.execution.ran is False
    assert review.to_dict()["execution"] == {"status": "skipped", "tests_submitted": False}


def test_a_skipped_execution_cannot_carry_output_or_a_failure() -> None:
    with pytest.raises(ValueError, match="did not run"):
        ReviewExecution(status=ExecutionStatus.SKIPPED, first_failure="AssertionError")
    with pytest.raises(ValueError, match="did not run"):
        ReviewExecution(status=ExecutionStatus.REJECTED, stdout_excerpt="Traceback ...")


def test_a_pass_cannot_carry_a_failure() -> None:
    with pytest.raises(ValueError, match="pass"):
        ReviewExecution(status="pass", first_failure="AssertionError")


def test_the_failing_execution_records_the_first_failure() -> None:
    review = _review("code_fail")

    assert review.execution is not None
    assert review.execution.status is ExecutionStatus.FAIL
    assert review.execution.ran is True
    assert review.execution.tests_submitted is True
    assert review.execution.first_failure is not None
    assert "AssertionError" in review.execution.first_failure


def test_the_domain_model_has_no_framework_or_storage_imports() -> None:
    tree = ast.parse(MODEL_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])

    assert imported <= {"__future__", "re", "collections", "dataclasses", "enum", "typing"}


# --- T1: the structure composer ------------------------------------------------
#
# The fixtures above pin the published shape; the tests below exercise the code
# that produces it. They use the real cue extractor and gap rules, so a change
# in either surfaces here as well as in test_generic_structure.py.

WRITING_ATTEMPT = "我想论证学校应该禁止学生带手机。很多同学都这样。"
UNKNOWN_ATTEMPT = "我最近很烦，不知道该怎么办。"


def _compose_structure(
    attempt: str,
    *,
    framework: IntakeFramework = IntakeFramework.ARGUMENTATIVE,
    graph: GenericGraph | None = None,
    domain_name: str = "writing",
    domain_label: str = "写作",
    session_id: str = "S_T1_REVIEW_001",
    problem_id: str = "P_T1_REVIEW_001",
) -> GenericReview:
    if graph is None:
        graph = CueSlotExtractor().extract(problem_id, attempt)
    gaps = structure_gaps(framework, graph)
    return GenericReviewComposer().compose(
        session_id=session_id,
        problem_id=problem_id,
        domain_name=domain_name,
        domain_label=domain_label,
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=gaps,
        initial_answer=attempt,
    )


def test_the_structure_composer_reports_a_missing_evidence_or_reasoning_gap(
    schema: dict[str, Any],
) -> None:
    review = _compose_structure(WRITING_ATTEMPT)

    assert review.kind is ReviewKind.STRUCTURE
    assert review.domain.verification.value == "argumentative"
    payload = review.to_dict()
    assert "options" not in payload
    assert "execution" not in payload
    assert "tradeoff_question" not in payload
    kinds = {finding.kind for finding in review.findings}
    assert "missing_evidence" in kinds
    assert "reasoning_jump" in kinds

    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors, [error.message for error in errors]


def test_every_composed_finding_cites_evidence_that_exists() -> None:
    review = _compose_structure(WRITING_ATTEMPT)
    evidence_ids = {item.id for item in review.evidence}

    assert review.evidence
    for finding in review.findings:
        assert finding.evidence_refs
        assert set(finding.evidence_refs) <= evidence_ids


def test_the_composer_never_invents_a_graph_node_id() -> None:
    graph = CueSlotExtractor().extract("P_T1_REVIEW_002", WRITING_ATTEMPT)
    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_002",
        problem_id="P_T1_REVIEW_002",
        domain_name="writing",
        domain_label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=structure_gaps(IntakeFramework.ARGUMENTATIVE, graph),
        initial_answer=WRITING_ATTEMPT,
    )
    node_ids = {node.id for node in graph.nodes}

    for item in review.evidence:
        if item.source is EvidenceSource.GRAPH:
            assert item.ref in node_ids
        else:
            assert item.source is EvidenceSource.STUDENT
            assert item.ref == "student"


def test_a_structure_review_never_scores_or_says_you_are_wrong() -> None:
    review = _compose_structure(WRITING_ATTEMPT)

    assert not _all_keys(review.to_dict()) & SCORE_FORBIDDEN_KEYS
    copy = [review.headline, review.next_step, review.disclaimer]
    copy.extend(finding.summary for finding in review.findings)
    copy.extend(review.not_checked)
    for text in copy:
        assert not any(phrase in text for phrase in FORBIDDEN_COPY), text


def test_an_unknown_domain_with_an_empty_graph_gets_not_checked_and_one_question(
    schema: dict[str, Any],
) -> None:
    review = _compose_structure(
        UNKNOWN_ATTEMPT,
        framework=IntakeFramework.GENERIC,
        domain_name="generic",
        domain_label="通用问题",
        session_id="S_T1_UNKNOWN_001",
        problem_id="P_T1_UNKNOWN_001",
    )

    assert review.kind is ReviewKind.STRUCTURE
    assert review.findings == ()
    assert review.evidence == ()
    assert review.not_checked
    assert review.next_step.endswith("？")
    assert review.next_step.count("？") == 1

    errors = list(Draft202012Validator(schema).iter_errors(review.to_dict()))
    assert not errors, [error.message for error in errors]


def test_no_attempt_does_not_manufacture_findings() -> None:
    review = _compose_structure(
        "   ",
        framework=IntakeFramework.GENERIC,
        domain_name="generic",
        domain_label="通用问题",
        session_id="S_T1_EMPTY_001",
        problem_id="P_T1_EMPTY_001",
    )

    assert review.findings == ()
    assert review.evidence == ()
    assert review.not_checked
    assert review.next_step.endswith("？")


def test_every_gap_becomes_a_finding() -> None:
    attempt = "我想论证远程办公更好。因为省通勤。"
    graph = CueSlotExtractor().extract("P_T1_REVIEW_003", attempt)
    gaps = structure_gaps(IntakeFramework.ARGUMENTATIVE, graph)
    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_003",
        problem_id="P_T1_REVIEW_003",
        domain_name="writing",
        domain_label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=gaps,
        initial_answer=attempt,
    )

    assert len(review.findings) == len(gaps)
    assert {finding.kind for finding in review.findings} == {
        "reasoning_jump",
        "missing_counter_argument",
    }


def test_a_missing_inference_step_cites_the_nodes_on_both_sides() -> None:
    attempt = "我想论证远程办公更好。因为省通勤。"
    graph = CueSlotExtractor().extract("P_T1_REVIEW_004", attempt)
    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_004",
        problem_id="P_T1_REVIEW_004",
        domain_name="writing",
        domain_label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=structure_gaps(IntakeFramework.ARGUMENTATIVE, graph),
        initial_answer=attempt,
    )
    reasoning = next(finding for finding in review.findings if finding.kind == "reasoning_jump")
    evidence = {item.id: item for item in review.evidence}
    cited_refs = {
        evidence[ref].ref
        for ref in reasoning.evidence_refs
        if evidence[ref].source is EvidenceSource.GRAPH
    }

    assert cited_refs == {
        graph.of_kind(NodeKind.GOAL)[0].id,
        graph.of_kind(NodeKind.EVIDENCE)[0].id,
    }
    assert any(evidence[ref].source is EvidenceSource.STUDENT for ref in reasoning.evidence_refs)


def test_a_gap_without_a_related_node_falls_back_to_the_student_text() -> None:
    graph = GenericGraph(
        problem_id="P_T1_REVIEW_005",
        version="g1",
        nodes=(GenericNode(id="risk1", kind=NodeKind.RISK, text="我怕失败"),),
    )
    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_005",
        problem_id="P_T1_REVIEW_005",
        domain_name="writing",
        domain_label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=structure_gaps(IntakeFramework.ARGUMENTATIVE, graph),
        initial_answer="我想论证 A，但我怕失败。",
    )
    goal = next(finding for finding in review.findings if finding.kind == "missing_goal")
    evidence = {item.id: item for item in review.evidence}

    assert [evidence[ref].source for ref in goal.evidence_refs] == [EvidenceSource.STUDENT]
    assert evidence[goal.evidence_refs[0]].ref == "student"


def test_an_empty_graph_with_no_gaps_still_composes() -> None:
    graph = GenericGraph(problem_id="P_T1_REVIEW_006", version="g1", nodes=())
    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_006",
        problem_id="P_T1_REVIEW_006",
        domain_name="generic",
        domain_label="通用问题",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=(),
        initial_answer="我卡住了。",
    )

    assert review.findings == ()
    assert review.evidence == ()
    assert review.not_checked
    assert review.next_step.endswith("？")


def test_a_complete_structure_does_not_invent_findings() -> None:
    attempt = "我想论证远程办公更好。因为省通勤。因此公司可以继续。但我担心协作会变慢。"
    graph = CueSlotExtractor().extract("P_T1_REVIEW_007", attempt)
    gaps = structure_gaps(IntakeFramework.ARGUMENTATIVE, graph)
    assert gaps == ()

    review = GenericReviewComposer().compose(
        session_id="S_T1_REVIEW_007",
        problem_id="P_T1_REVIEW_007",
        domain_name="writing",
        domain_label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=gaps,
        initial_answer=attempt,
    )

    assert review.findings == ()
    assert review.evidence == ()
    assert "没有发现" in review.headline


def test_the_composer_only_composes_the_argumentative_structure_branch() -> None:
    graph = GenericGraph(problem_id="P_T1_REVIEW_008", version="g1", nodes=())

    with pytest.raises(ValueError, match="argumentative"):
        GenericReviewComposer().compose(
            session_id="S_T1_REVIEW_008",
            problem_id="P_T1_REVIEW_008",
            domain_name="math",
            domain_label="数学",
            verification=VerificationMode.FORMAL,
            graph=graph,
            gaps=(),
            initial_answer="求 a 的范围。",
        )


# --- T2: the decision frame ----------------------------------------------------
#
# The contract above (T0) already pins the decision shape. The tests below pin
# the composer: options come from the student's DECISION nodes, "什么都不做" is
# the only option the composer adds, costs/risks/tests are copied from the text
# beside their option, and an incomplete frame returns a structure review rather
# than an invented second option.

DECISION_ATTEMPT = (
    "我要决定接受北京的工作还是留在上海还是先读研。"
    "接受北京的工作，代价是异地分居，先试试远程三个月再决定。"
    "留在上海，担心发展变慢。"
    "先读研，代价是再花两年。"
)
# Not "推荐"/"排序" on their own: the disclaimer legitimately says "不推荐".
DECISION_FORBIDDEN_COPY = ("你错了", "正确答案", "应该选", "建议选", "推荐选", "最佳选项", "排名")


def _compose_decision(
    attempt: str,
    *,
    graph: GenericGraph | None = None,
    gaps: tuple[StructureGap, ...] | None = None,
    framework: IntakeFramework = IntakeFramework.DECISION,
    domain_name: str = "decision",
    domain_label: str = "决策",
    session_id: str = "S_T2_DECISION_001",
    problem_id: str = "P_T2_DECISION_001",
) -> GenericReview:
    if graph is None:
        graph = CueSlotExtractor().extract(problem_id, attempt)
    if gaps is None:
        gaps = structure_gaps(framework, graph)
    return GenericReviewComposer().compose(
        session_id=session_id,
        problem_id=problem_id,
        domain_name=domain_name,
        domain_label=domain_label,
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=gaps,
        initial_answer=attempt,
        framework=framework,
    )


def _finding_kinds_by_ref(review: GenericReview) -> dict[str, set[str]]:
    evidence = {item.id: item for item in review.evidence}
    kinds: dict[str, set[str]] = {}
    for finding in review.findings:
        for ref in finding.evidence_refs:
            kinds.setdefault(evidence[ref].ref, set()).add(finding.kind)
    return kinds


def test_a_decision_lists_the_students_options_and_adds_only_do_nothing(
    schema: dict[str, Any],
) -> None:
    graph = CueSlotExtractor().extract("P_T2_DECISION_001", DECISION_ATTEMPT)
    review = _compose_decision(DECISION_ATTEMPT, graph=graph)

    assert review.kind is ReviewKind.DECISION
    assert review.domain.verification.value == "argumentative"
    labels = [option.label for option in review.options]
    assert len(review.options) >= 3
    assert sum(1 for label in labels if "什么都不做" in label) == 1

    node_texts = [node.text for node in graph.of_kind(NodeKind.DECISION)]
    student_options = [option for option in review.options if "什么都不做" not in option.label]
    assert len(student_options) == len(node_texts)
    for option in student_options:
        # Only a deliberation lead-in ("我要决定", "还是") is dropped; the rest of
        # the label is the student's own option text.
        assert any(text.endswith(option.label) for text in node_texts)
        assert option.label in DECISION_ATTEMPT

    errors = list(Draft202012Validator(schema).iter_errors(review.to_dict()))
    assert not errors, [error.message for error in errors]


def test_every_option_has_cost_risk_and_reversible_test_or_a_finding() -> None:
    graph = CueSlotExtractor().extract("P_T2_DECISION_002", DECISION_ATTEMPT)
    review = _compose_decision(
        DECISION_ATTEMPT,
        graph=graph,
        session_id="S_T2_DECISION_002",
        problem_id="P_T2_DECISION_002",
    )
    kinds = _finding_kinds_by_ref(review)
    evidence_ids = {item.id for item in review.evidence}

    for finding in review.findings:
        assert finding.evidence_refs
        assert set(finding.evidence_refs) <= evidence_ids

    for node, option in zip(graph.of_kind(NodeKind.DECISION), review.options, strict=False):
        assert bool(option.costs) or "option_without_cost" in kinds[node.id], option.label
        assert bool(option.risks) or "option_without_risk" in kinds[node.id], option.label
        assert bool(option.reversible_test) or "missing_reversible_test" in kinds[node.id], (
            option.label
        )

    baseline = review.options[-1]
    assert "什么都不做" in baseline.label
    assert baseline.costs == ()
    assert baseline.risks == ()
    assert baseline.reversible_test == ""
    student_kinds = kinds["student"]
    assert {
        "option_without_cost",
        "option_without_risk",
        "missing_reversible_test",
    } <= student_kinds


def test_costs_risks_and_tests_are_copied_from_the_student_text() -> None:
    review = _compose_decision(DECISION_ATTEMPT)

    copied = [item for option in review.options for item in (*option.costs, *option.risks)]
    copied.extend(option.reversible_test for option in review.options if option.reversible_test)
    assert copied
    for item in copied:
        assert item in DECISION_ATTEMPT

    beijing = next(option for option in review.options if option.label == "接受北京的工作")
    assert beijing.costs == ("代价是异地分居",)
    assert beijing.risks == ()
    assert beijing.reversible_test == "先试试远程三个月再决定"


def test_a_generated_graph_attributes_each_risk_to_the_option_in_its_sentence() -> None:
    graph = GenericGraph(
        problem_id="P_T2_DECISION_003",
        version="g2",
        nodes=(
            GenericNode(id="d1", kind=NodeKind.DECISION, text="接受北京的工作"),
            GenericNode(id="d2", kind=NodeKind.DECISION, text="留在上海"),
            GenericNode(id="r1", kind=NodeKind.RISK, text="担心异地分居", source="system"),
            GenericNode(id="r2", kind=NodeKind.RISK, text="怕发展变慢", source="system"),
            GenericNode(id="n1", kind=NodeKind.NEXT, text="先试远程三个月", source="system"),
        ),
    )
    attempt = (
        "接受北京的工作还是留在上海。"
        "接受北京的工作，担心异地分居，先试远程三个月。"
        "留在上海，怕发展变慢。"
    )

    review = _compose_decision(
        attempt,
        graph=graph,
        session_id="S_T2_DECISION_003",
        problem_id="P_T2_DECISION_003",
    )

    by_label = {option.label: option for option in review.options}
    assert by_label["接受北京的工作"].risks == ("担心异地分居",)
    assert by_label["接受北京的工作"].reversible_test == "先试远程三个月"
    assert by_label["留在上海"].risks == ("怕发展变慢",)
    assert by_label["留在上海"].reversible_test == ""


def test_a_composed_decision_never_scores_ranks_or_recommends() -> None:
    review = _compose_decision(DECISION_ATTEMPT)
    payload = review.to_dict()

    assert not _all_keys(payload) & DECISION_FORBIDDEN_KEYS
    for option in review.options:
        assert set(option.to_dict()) == {"label", "costs", "risks", "reversible_test"}

    copy = [review.headline, review.next_step, review.disclaimer, review.tradeoff_question or ""]
    copy.extend(option.label for option in review.options)
    copy.extend(item for option in review.options for item in (*option.costs, *option.risks))
    copy.extend(option.reversible_test for option in review.options if option.reversible_test)
    copy.extend(finding.summary for finding in review.findings)
    copy.extend(review.not_checked)
    for text in copy:
        assert not any(phrase in text for phrase in DECISION_FORBIDDEN_COPY), text

    assert review.tradeoff_question is not None
    assert review.tradeoff_question.endswith("？")


def test_an_option_without_a_cost_is_reported_as_option_without_cost() -> None:
    attempt = "我在纠结接受北京的工作还是留在上海。"
    review = _compose_decision(attempt)
    kinds = {finding.kind for finding in review.findings}

    assert "option_without_cost" in kinds
    assert "option_without_risk" in kinds
    assert "missing_reversible_test" in kinds
    # The frame-level constraint gap is kept; the per-option gap is not repeated.
    assert "missing_constraint" in kinds
    assert "missing_cost_or_risk" not in kinds


def test_one_option_falls_back_to_a_structure_review_instead_of_inventing_a_second(
    schema: dict[str, Any],
) -> None:
    attempt = "我在纠结要不要接北京的工作。"
    graph = CueSlotExtractor().extract("P_T2_DECISION_004", attempt)
    assert len(graph.of_kind(NodeKind.DECISION)) == 1

    review = _compose_decision(
        attempt,
        graph=graph,
        session_id="S_T2_DECISION_004",
        problem_id="P_T2_DECISION_004",
    )

    assert review.kind is ReviewKind.STRUCTURE
    assert review.options == ()
    assert any("至少两个选项" in item and "什么都不做" in item for item in review.not_checked), (
        review.not_checked
    )
    assert "第二个选项" in review.next_step
    assert review.next_step.endswith("？")

    errors = list(Draft202012Validator(schema).iter_errors(review.to_dict()))
    assert not errors, [error.message for error in errors]


def test_a_submission_with_no_options_falls_back_without_raising() -> None:
    attempt = "最近项目很乱，不知道从哪里开始。"
    review = _compose_decision(attempt)

    assert review.kind is ReviewKind.STRUCTURE
    assert review.options == ()
    assert any("决策框需要至少两个选项" in item for item in review.not_checked)
    assert review.next_step.endswith("？")


def test_an_explicit_do_nothing_option_is_not_duplicated() -> None:
    attempt = "接受北京的工作还是什么都不做。"
    review = _compose_decision(attempt)

    labels = [option.label for option in review.options]
    assert sum(1 for label in labels if "什么都不做" in label) == 1
    assert len(labels) == 2


def test_more_options_than_the_contract_allows_are_truncated_not_rejected() -> None:
    choices = tuple(f"选项{index}" for index in range(1, 8))
    graph = GenericGraph(
        problem_id="P_T2_DECISION_005",
        version="g2",
        nodes=tuple(
            GenericNode(id=f"d{index}", kind=NodeKind.DECISION, text=text)
            for index, text in enumerate(choices, start=1)
        ),
    )
    attempt = "还是".join(choices)

    review = _compose_decision(
        attempt,
        graph=graph,
        session_id="S_T2_DECISION_005",
        problem_id="P_T2_DECISION_005",
    )

    assert review.kind is ReviewKind.DECISION
    assert len(review.options) == 6
    assert any("什么都不做" in option.label for option in review.options)
    assert any("超过" in item for item in review.not_checked)


def test_a_risk_in_a_sentence_naming_two_options_is_not_attributed_to_either() -> None:
    graph = GenericGraph(
        problem_id="P_T2_DECISION_008",
        version="g2",
        nodes=(
            GenericNode(id="d1", kind=NodeKind.DECISION, text="接受北京"),
            GenericNode(id="d2", kind=NodeKind.DECISION, text="留在上海"),
            GenericNode(id="r1", kind=NodeKind.RISK, text="担心两边都失去", source="system"),
        ),
    )
    attempt = "接受北京还是留在上海，担心两边都失去。"

    review = _compose_decision(
        attempt,
        graph=graph,
        session_id="S_T2_DECISION_008",
        problem_id="P_T2_DECISION_008",
    )

    # The sentence names both options, so the risk cannot be pinned on one of
    # them without guessing; it is reported as a missing field instead.
    student_options = [option for option in review.options if "什么都不做" not in option.label]
    assert student_options
    for option in student_options:
        assert option.risks == ()
    kinds = {finding.kind for finding in review.findings}
    assert "option_without_risk" in kinds


def test_the_decision_branch_still_requires_argumentative_verification() -> None:
    graph = GenericGraph(
        problem_id="P_T2_DECISION_006",
        version="g1",
        nodes=(
            GenericNode(id="d1", kind=NodeKind.DECISION, text="接受北京"),
            GenericNode(id="d2", kind=NodeKind.DECISION, text="留在上海"),
        ),
    )

    with pytest.raises(ValueError, match="argumentative"):
        GenericReviewComposer().compose(
            session_id="S_T2_DECISION_006",
            problem_id="P_T2_DECISION_006",
            domain_name="decision",
            domain_label="决策",
            verification=VerificationMode.FORMAL,
            graph=graph,
            gaps=(),
            initial_answer="接受北京还是留在上海。",
            framework=IntakeFramework.DECISION,
        )


def test_the_default_framework_keeps_the_t1_structure_branch() -> None:
    graph = CueSlotExtractor().extract("P_T2_DECISION_007", DECISION_ATTEMPT)
    review = _compose_structure(
        DECISION_ATTEMPT,
        graph=graph,
        domain_name="decision",
        domain_label="决策",
        session_id="S_T2_DECISION_007",
        problem_id="P_T2_DECISION_007",
    )

    assert review.kind is ReviewKind.STRUCTURE
    assert review.options == ()
    assert "options" not in review.to_dict()
