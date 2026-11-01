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


class TestCueSynonyms:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("我没法加班。", NodeKind.CONSTRAINT),
            ("时间来不及。", NodeKind.CONSTRAINT),
            ("我不希望降薪。", NodeKind.CONSTRAINT),
            ("我要两周内上线。", NodeKind.GOAL),
            ("希望能先跑通。", NodeKind.GOAL),
            ("已有两份报价。", NodeKind.GIVEN),
            ("输入是一个列表。", NodeKind.GIVEN),
            ("假定样本有代表性。", NodeKind.ASSUMPTION),
            ("方法是先改缓存。", NodeKind.PLAN),
            ("我试了一下改缓存。", NodeKind.ACTION),
            ("改过两处。", NodeKind.ACTION),
            ("运行了测试。", NodeKind.ACTION),
            ("返回了 -1。", NodeKind.EVIDENCE),
            ("结果是 -1。", NodeKind.EVIDENCE),
            ("错误信息是 KeyError。", NodeKind.EVIDENCE),
            ("异常是 KeyError。", NodeKind.EVIDENCE),
            ("我核对过金额。", NodeKind.CHECK),
            ("复查一下。", NodeKind.CHECK),
            ("本地跑通了。", NodeKind.CHECK),
            ("怎么知道修好了？", NodeKind.CHECK),
            ("测试通过。", NodeKind.CHECK),
            ("这里有个隐患。", NodeKind.RISK),
            ("最坏会怎样？", NodeKind.RISK),
            ("先做一个小实验。", NodeKind.NEXT),
            ("先跑一遍。", NodeKind.NEXT),
            ("先改一处。", NodeKind.NEXT),
            ("我有点犹豫。", NodeKind.DECISION),
        ],
    )
    def test_common_synonyms_fill_their_slot(self, text: str, kind: NodeKind) -> None:
        assert EXTRACTOR.extract("P", text).has(kind)

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("我考试了。", NodeKind.ACTION),
            ("异常处理要小心。", NodeKind.EVIDENCE),
            ("损失函数要调。", NodeKind.RISK),
            ("返回首页。", NodeKind.EVIDENCE),
            ("哪怕失败也要试。", NodeKind.RISK),
        ],
    )
    def test_a_near_miss_does_not_fill_a_slot(self, text: str, kind: NodeKind) -> None:
        assert not EXTRACTOR.extract("P", text).has(kind)

    def test_the_intake_uses_the_synonym(self) -> None:
        intake = build_domain_intake(
            _problem("programming"),
            REGISTRY.profile_for("programming"),
            "我要两周内上线；我没法加班。",
        )

        assert "目标" in intake.observed
        assert "约束" in intake.observed
        assert not any("没看到约束" in gap for gap in intake.gaps)


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

        assert intake.version == "0.4"
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

    def test_the_probe_question_tracks_the_specific_gap(self) -> None:
        """A missing EXECUTABLE reproduction must not ask a generic "what did you try"."""

        code = build_domain_intake(
            _problem("programming"),
            REGISTRY.profile_for("programming"),
            "我想让它跑起来。",
        )
        assert code.probe is not None
        assert code.probe.kind is NodeKind.ACTION
        assert "最小复现" in code.probe.question
        assert "试过哪一步" not in code.probe.question

        writing = build_domain_intake(
            _problem("writing"),
            REGISTRY.profile_for("writing"),
            "我想论证远程办公更好。因为省通勤。因此公司应该继续。",
        )
        assert writing.probe is not None
        assert writing.probe.kind is NodeKind.RISK
        assert "反对意见" in writing.probe.question

        physics = build_domain_intake(
            _problem("physics"),
            REGISTRY.profile_for("physics"),
            "我想算小球落地时间。",
        )
        assert physics.probe is not None
        assert physics.probe.kind is NodeKind.GIVEN
        assert "单位" in physics.probe.question

    def test_a_minimal_reproduction_answer_fills_the_reproduction_gap(self) -> None:
        """The question asks for a reproduction; the natural answer must count."""

        code = build_domain_intake(
            _problem("programming"),
            REGISTRY.profile_for("programming"),
            "目标是让 add(2, 3) 返回 5；已知它返回 -1；约束是不能改测试。"
            "最小复现是 add(2, 3)；输出是 -1，预期是 5。",
        )

        assert "尝试" in code.observed
        assert code.gaps == ("没看到已经试过哪些改动。",)
        assert code.probe is not None
        assert code.probe.kind is NodeKind.CHECK
        assert "试过哪些改动" in code.probe.question

    def test_a_negated_reproduction_is_still_a_gap(self) -> None:
        """A bare "复现" is not a cue: "没有复现" must not fill the gap."""

        code = build_domain_intake(
            _problem("programming"),
            REGISTRY.profile_for("programming"),
            "目标是让 add(2, 3) 返回 5；已知它返回 -1；约束是不能改测试。我没有复现。",
        )

        assert code.probe is not None
        assert code.probe.kind is NodeKind.ACTION
        assert any("没看到复现" in gap for gap in code.gaps)

    def test_a_generic_probe_falls_back_to_its_shared_question(self) -> None:
        intake = build_domain_intake(
            _problem("generic"),
            REGISTRY.profile_for("generic"),
            "我卡住了。",
        )

        assert intake.probe is not None
        assert intake.probe.kind is NodeKind.GOAL
        assert "最想解决" in intake.probe.question


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
