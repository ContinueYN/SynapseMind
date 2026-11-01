"""Phase 1a: a submission becomes a generic graph, and a rule table checks it.

These tests pin the two properties that make the feature honest:

* the extractor copies what the student wrote and never invents a slot, so a
  missing constraint can be reported safely (a coincidental cue may hide a gap,
  never create one);
* every finding is a coverage statement. There is no "wrong" verdict anywhere in
  ``application/generic_check.py``, and a decision check never recommends one of
  the options.
"""

from __future__ import annotations

import pytest

from synapse.application.domains import DomainRegistry, IntakeFramework
from synapse.application.generic_check import structure_gaps
from synapse.application.generic_slots import CueSlotExtractor
from synapse.application.intake import build_domain_intake
from synapse.domain.problem.claims import Interval, VerificationClaim
from synapse.domain.problem.generic import (
    ClaimCheck,
    EmpiricalClaim,
    GenericGraph,
    GenericNode,
    NodeKind,
)
from synapse.domain.problem.models import Problem, SolutionGraph

EXTRACTOR = CueSlotExtractor()
REGISTRY = DomainRegistry()

DECISION_ATTEMPT = "我想在两年内转做后端。要么留在现在的公司转岗，要么跳槽去小厂。但我怕收入下降。"


def _graph(*nodes: tuple[NodeKind, str]) -> GenericGraph:
    return GenericGraph(
        problem_id="P_GEN_TEST",
        version="g1",
        nodes=tuple(
            GenericNode(id=f"n{index}", kind=kind, text=text)
            for index, (kind, text) in enumerate(nodes, start=1)
        ),
    )


def _problem(
    subject: str,
    confidence: float = 1.0,
    *,
    generic: GenericGraph | None = None,
    checks: tuple[ClaimCheck, ...] = (),
) -> Problem:
    return Problem(
        id="P_GEN_TEST",
        title="测试",
        text="测试",
        graph=SolutionGraph(problem_id="P_GEN_TEST", version="g0", stem="", nodes=(), edges=()),
        subject=subject,
        annotated=False,
        domain_confidence=confidence,
        domain_method="declared",
        generic=generic,
        generic_checks=checks,
    )


def _gaps(framework: IntakeFramework, graph: GenericGraph) -> list[str]:
    return [gap.text for gap in structure_gaps(framework, graph)]


class TestExtraction:
    def test_one_sentence_can_fill_a_goal_and_a_constraint(self) -> None:
        graph = EXTRACTOR.extract("P", "我想两周内上线，但不能加班。")

        assert graph.has(NodeKind.GOAL)
        assert graph.has(NodeKind.CONSTRAINT)

    def test_a_kind_is_recorded_once(self) -> None:
        graph = EXTRACTOR.extract("P", "我想修好登录。我想加个测试。")

        assert len(graph.of_kind(NodeKind.GOAL)) == 1

    def test_option_markers_become_two_options(self) -> None:
        graph = EXTRACTOR.extract("P", DECISION_ATTEMPT)

        options = graph.of_kind(NodeKind.DECISION)
        assert len(options) == 2, [node.text for node in options]
        assert all(node.text for node in options)

    def test_a_short_fragment_is_not_a_node(self) -> None:
        assert len(EXTRACTOR.extract("P", "不知道。")) == 0

    def test_the_node_text_is_copied_verbatim(self) -> None:
        graph = EXTRACTOR.extract("P", "我怕收入下降。")

        assert graph.of_kind(NodeKind.RISK)[0].text == "我怕收入下降"

    def test_kinds_are_reported_in_plan_order(self) -> None:
        graph = EXTRACTOR.extract("P", "我怕收入下降，我想转后端。")

        assert graph.kinds() == (NodeKind.GOAL, NodeKind.RISK)

    def test_duplicate_node_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            GenericGraph(
                problem_id="P",
                version="g1",
                nodes=(
                    GenericNode(id="n1", kind=NodeKind.GOAL, text="a"),
                    GenericNode(id="n1", kind=NodeKind.RISK, text="b"),
                ),
            )


class TestDecisionCheck:
    def test_a_decision_without_options_is_blocking(self) -> None:
        gaps = structure_gaps(IntakeFramework.DECISION, _graph((NodeKind.GOAL, "我想转后端")))

        assert gaps[0].severity == "blocking"
        assert "两个选项" in gaps[0].text

    def test_a_single_option_does_not_count(self) -> None:
        gaps = _gaps(
            IntakeFramework.DECISION,
            _graph((NodeKind.GOAL, "我想转后端"), (NodeKind.DECISION, "跳槽")),
        )

        assert any("两个选项" in text for text in gaps)

    def test_a_decision_with_options_still_asks_for_a_reversible_test(self) -> None:
        gaps = _gaps(
            IntakeFramework.DECISION,
            _graph(
                (NodeKind.GOAL, "我想转后端"),
                (NodeKind.DECISION, "转岗"),
                (NodeKind.DECISION, "跳槽"),
                (NodeKind.CONSTRAINT, "不能降薪"),
                (NodeKind.RISK, "怕收入下降"),
            ),
        )

        assert gaps == ["没看到可逆实验：1–2 周内能先试哪一步。"]

    def test_options_are_never_ranked(self) -> None:
        gaps = _gaps(
            IntakeFramework.DECISION,
            _graph(
                (NodeKind.GOAL, "我想转后端"),
                (NodeKind.DECISION, "转岗"),
                (NodeKind.DECISION, "跳槽"),
                (NodeKind.CONSTRAINT, "不能降薪"),
                (NodeKind.RISK, "怕收入下降"),
                (NodeKind.NEXT, "先在公司内部试两周"),
            ),
        )

        assert gaps == []


class TestModeSpecificChecks:
    def test_executable_requires_a_reproduction(self) -> None:
        gaps = _gaps(IntakeFramework.EXECUTABLE, _graph((NodeKind.GOAL, "修好脚本")))

        assert "复现" in gaps[0]

    def test_argumentative_requires_evidence(self) -> None:
        gaps = _gaps(IntakeFramework.ARGUMENTATIVE, _graph((NodeKind.GOAL, "结论是 A")))

        assert any(text.startswith("没看到证据") for text in gaps)

    def test_an_assumption_must_say_how_it_is_checked(self) -> None:
        gaps = _gaps(
            IntakeFramework.ARGUMENTATIVE,
            _graph(
                (NodeKind.GOAL, "结论是 A"),
                (NodeKind.EVIDENCE, "数据显示 A"),
                (NodeKind.ASSUMPTION, "假设样本有代表性"),
            ),
        )

        assert "有假设，但没有写怎么检查它。" in gaps

    def test_a_checked_assumption_is_not_a_gap(self) -> None:
        gaps = _gaps(
            IntakeFramework.ARGUMENTATIVE,
            _graph(
                (NodeKind.GOAL, "结论是 A"),
                (NodeKind.EVIDENCE, "数据显示 A"),
                (NodeKind.ASSUMPTION, "假设样本有代表性"),
                (NodeKind.CHECK, "对比了三个子样本"),
                (NodeKind.PLAN, "因此可以推广"),
                (NodeKind.RISK, "反方说样本太小"),
            ),
        )

        assert gaps == []

    def test_generic_mode_only_blocks_on_the_goal(self) -> None:
        gaps = structure_gaps(IntakeFramework.GENERIC, _graph())

        assert [gap.severity for gap in gaps].count("blocking") == 1
        assert gaps[0].text.startswith("没看到目标")


class TestAnswerAwareIntake:
    def test_a_rich_attempt_names_what_it_saw_and_what_is_missing(self) -> None:
        intake = build_domain_intake(
            _problem("decision"), REGISTRY.profile_for("decision"), DECISION_ATTEMPT
        )

        assert intake.version == "0.3"
        assert "目标" in intake.observed
        assert "选项" in intake.observed
        assert "风险" in intake.observed
        assert len(intake.gaps) <= 3
        assert not any("两个选项" in gap for gap in intake.gaps)
        # The two things this attempt really does not say: the constraint and a
        # reversible first step. Nothing else is claimed missing.
        assert [gap.split("：")[0] for gap in intake.gaps] == [
            "没看到约束",
            "没看到可逆实验",
        ]
        assert all("唯一正确答案" not in gap for gap in intake.gaps)

    def test_a_blank_attempt_reports_no_gap(self) -> None:
        intake = build_domain_intake(_problem("decision"), REGISTRY.profile_for("decision"), "   ")

        assert intake.observed == ()
        assert intake.gaps == ()

    def test_the_attempt_never_adds_a_verdict(self) -> None:
        intake = build_domain_intake(
            _problem("decision"), REGISTRY.profile_for("decision"), DECISION_ATTEMPT
        )

        assert not any("错" in gap for gap in intake.gaps)


class TestVerificationView:
    FORMAL_CLAIM = VerificationClaim(
        kind="parameter_range",
        parameter="a",
        variable="x",
        variable_domain="(0,+inf)",
        expression="log(x) - a*x",
        relation="<=",
        intervals=(Interval(lower="1/E", upper=None, upper_inclusive=False),),
    )

    def test_a_formal_domain_without_a_claim_says_unknown(self) -> None:
        intake = build_domain_intake(_problem("math"), REGISTRY.profile_for("math"), "求 a 的范围")

        assert [(item.kind, item.status) for item in intake.verifications] == [
            ("formal", "unknown")
        ]
        assert "没有可验证" in intake.verifications[0].detail

    def test_a_claim_without_a_running_verifier_is_not_a_pass(self) -> None:
        graph = GenericGraph(
            problem_id="P_GEN_TEST",
            version="g2",
            nodes=(
                GenericNode(id="g1", kind=NodeKind.GOAL, text="求 a 的范围"),
                GenericNode(id="g2", kind=NodeKind.CHECK, text="检查边界"),
            ),
            formal=self.FORMAL_CLAIM,
        )
        intake = build_domain_intake(
            _problem("math", generic=graph),
            REGISTRY.profile_for("math"),
            "a 的范围",
        )

        assert [(item.kind, item.status) for item in intake.verifications] == [
            ("formal", "unknown")
        ]
        assert "没有运行" in intake.verifications[0].detail

    def test_a_stored_failure_is_shown_but_still_only_as_a_check(self) -> None:
        graph = GenericGraph(
            problem_id="P_GEN_TEST",
            version="g2",
            nodes=(
                GenericNode(id="g1", kind=NodeKind.GOAL, text="量纲检查"),
                GenericNode(id="g2", kind=NodeKind.CHECK, text="两边单位"),
            ),
            empirical=EmpiricalClaim(
                equation="F = q/E",
                units={"F": "N", "q": "C", "E": "N/C"},
                values={"F": 1, "q": 1, "E": 1},
            ),
        )
        check = ClaimCheck(kind="empirical", status="fail", detail="量纲不一致：左侧 N，右侧 N·m/C")
        intake = build_domain_intake(
            _problem("physics", generic=graph, checks=(check,)),
            REGISTRY.profile_for("physics"),
            "F=q/E",
        )

        assert [(item.kind, item.status) for item in intake.verifications] == [
            ("empirical", "fail")
        ]
        assert "量纲不一致" in intake.verifications[0].detail
