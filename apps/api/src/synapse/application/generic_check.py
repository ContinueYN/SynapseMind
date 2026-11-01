"""Structural checks over a generic graph: what is missing, never what is wrong.

Chapter 13 §13.3 allows a NONE-tier domain to say only "这一步你的过程里没有写到".
A generic graph gives that statement more to stand on — goals, constraints,
options, risks — but the promise does not change: every finding here is a
*coverage* finding. There is no "你错了" message in this module, and there is no
verdict type that could produce one.

Each verification mode asks a different question of the same graph:

* FORMAL — is the goal/given/constraint stated so a check could apply?
* EXECUTABLE — is there a reproduction (what ran, what happened), not just a bug?
* EMPIRICAL — is there a model and a unit/magnitude check?
* ARGUMENTATIVE — is there evidence for the claim, and a counter-argument?
* DECISION — are there two options, the constraint, the cost, and a reversible test?

The five rule tables are data, so a new mode needs a table, not a new verifier
class. ``FormalVerifier``/``EmpiricalVerifier`` adapters (plan §4.3) are not built
here: they need a claim and structured data, which the generic graph does not
carry yet. Saying ``unknown`` without them is more honest than faking a check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.application.domains import IntakeFramework
from synapse.domain.problem.generic import GenericGraph, NodeKind

GapSeverity = Literal["blocking", "notable"]


@dataclass(frozen=True, slots=True)
class StructureGap:
    """One "the submission does not mention this" observation.

    ``kind`` names the node the student would have to add; ``text`` is already
    user-facing, so the intake view does not translate it again.
    """

    kind: NodeKind | None
    severity: GapSeverity
    text: str
    # Optional kind- and mode-specific wording. ``None`` lets the intake use its
    # generic question, but a rule whose gap is narrower than its node kind
    # (EXECUTABLE's ACTION means "reproduction", ARGUMENTATIVE's RISK means
    # "counter-argument") must provide its own so the probe does not ask the
    # wrong question.
    question: str | None = None


@dataclass(frozen=True, slots=True)
class GapRule:
    """``kind`` must appear at least ``min_count`` times, unless ``only_if`` is absent."""

    kind: NodeKind
    min_count: int
    severity: GapSeverity
    text: str
    only_if: NodeKind | None = None
    question: str | None = None


class StructureVerifier(Protocol):
    framework: IntakeFramework

    def check(self, graph: GenericGraph) -> tuple[StructureGap, ...]: ...


class RuleBasedVerifier:
    """A rule table executed over a graph; the only verifier Phase 1 needs."""

    def __init__(self, framework: IntakeFramework, rules: tuple[GapRule, ...]) -> None:
        self.framework = framework
        self._rules = rules

    def check(self, graph: GenericGraph) -> tuple[StructureGap, ...]:
        gaps: list[StructureGap] = []
        for rule in self._rules:
            if rule.only_if is not None and not graph.has(rule.only_if):
                continue
            if len(graph.of_kind(rule.kind)) >= rule.min_count:
                continue
            gaps.append(
                StructureGap(
                    kind=rule.kind,
                    severity=rule.severity,
                    text=rule.text,
                    question=rule.question,
                )
            )
        return tuple(gaps)


_GOAL = NodeKind.GOAL
_GIVEN = NodeKind.GIVEN
_CONSTRAINT = NodeKind.CONSTRAINT
_ASSUMPTION = NodeKind.ASSUMPTION
_PLAN = NodeKind.PLAN
_ACTION = NodeKind.ACTION
_EVIDENCE = NodeKind.EVIDENCE
_CHECK = NodeKind.CHECK
_DECISION = NodeKind.DECISION
_RISK = NodeKind.RISK
_NEXT = NodeKind.NEXT

_RULES: dict[IntakeFramework, tuple[GapRule, ...]] = {
    IntakeFramework.FORMAL: (
        GapRule(
            _GOAL,
            1,
            "blocking",
            "没看到目标：这一轮要证明或求出什么。",
            question="这一轮要证明或求出什么？",
        ),
        GapRule(
            _GIVEN,
            1,
            "blocking",
            "没看到已知：可用的条件与取值范围。",
            question="可用的条件和取值范围有哪些？",
        ),
        GapRule(
            _CONSTRAINT,
            1,
            "notable",
            "没看到约束：定义域、参数范围或边界。",
            question="定义域、参数范围或边界是什么？",
        ),
        GapRule(
            _ACTION,
            1,
            "notable",
            "没看到你写到哪一步。",
            question="你写到哪一步了？",
        ),
    ),
    IntakeFramework.EXECUTABLE: (
        GapRule(
            _GOAL,
            1,
            "blocking",
            "没看到目标：这段代码或算法应该做到什么。",
            question="这段代码或算法应该做到什么？",
        ),
        GapRule(
            _ACTION,
            1,
            "blocking",
            "没看到复现：最小片段、输入或完整报错。",
            question="最小复现是什么：哪段代码、什么输入、完整报错？",
        ),
        GapRule(
            _EVIDENCE,
            1,
            "notable",
            "没看到预期与实际：你以为什么、实际发生了什么。",
            question="预期是什么，实际又发生了什么？",
        ),
        GapRule(
            _GIVEN,
            1,
            "notable",
            "没看到环境：语言版本、依赖、平台。",
            question="跑这段代码的环境是什么：语言版本、依赖、平台？",
        ),
        GapRule(
            _CHECK,
            1,
            "notable",
            "没看到已经试过哪些改动。",
            question="你已经试过哪些改动，各是什么结果？",
        ),
    ),
    IntakeFramework.EMPIRICAL: (
        GapRule(
            _GOAL,
            1,
            "blocking",
            "没看到目标：要解释或预测哪个量。",
            question="要解释或预测哪个量？",
        ),
        GapRule(
            _GIVEN,
            1,
            "blocking",
            "没看到已知量，或者单位没写。",
            question="已知量有哪些？请带上单位。",
        ),
        GapRule(
            _PLAN,
            1,
            "notable",
            "没看到模型：用了哪条定律，适用条件是什么。",
            question="你用了哪条定律或模型？它的适用条件是什么？",
        ),
        GapRule(
            _CHECK,
            1,
            "notable",
            "没看到量纲或数量级检查。",
            question="你打算怎么做量纲或数量级检查？",
        ),
    ),
    IntakeFramework.ARGUMENTATIVE: (
        GapRule(
            _GOAL,
            1,
            "blocking",
            "没看到结论：你想让读者接受什么。",
            question="先用一句话写下结论：你想让读者接受什么？",
        ),
        GapRule(
            _EVIDENCE,
            1,
            "blocking",
            "没看到证据：哪些事实或引文在支撑它。",
            question="哪些事实或引文在支撑它？",
        ),
        GapRule(
            _PLAN,
            1,
            "notable",
            "没看到推理：从证据到结论之间那一步。",
            question="从证据到结论之间那一步是什么？",
        ),
        GapRule(
            _CHECK,
            1,
            "notable",
            "有假设，但没有写怎么检查它。",
            only_if=_ASSUMPTION,
            question="你依赖的假设，打算怎么检查？",
        ),
        GapRule(
            _RISK,
            1,
            "notable",
            "没看到反方：最强的反对意见是什么。",
            question="最强的反对意见是什么？",
        ),
    ),
    IntakeFramework.DECISION: (
        GapRule(
            _GOAL,
            1,
            "blocking",
            "没看到目标：你最看重什么。",
            question="你最看重什么？",
        ),
        GapRule(
            _DECISION,
            2,
            "blocking",
            "没看到两个选项：至少摆出两个，含「什么都不做」。",
            question="先摆出两个选项（含「什么都不做」），各写一句。",
        ),
        GapRule(
            _CONSTRAINT,
            1,
            "notable",
            "没看到约束：时间、钱、关系、不可逆性。",
            question="哪些条件不能动：时间、钱、关系还是不可逆性？",
        ),
        GapRule(
            _RISK,
            1,
            "notable",
            "没看到代价与风险：每个选项会失去什么。",
            question="每个选项会失去什么？",
        ),
        GapRule(
            _NEXT,
            1,
            "notable",
            "没看到可逆实验：1–2 周内能先试哪一步。",
            question="1–2 周内能先做哪个可逆的小实验？",
        ),
    ),
    IntakeFramework.GENERIC: (
        GapRule(_GOAL, 1, "blocking", "没看到目标：这次希望得到什么结果。"),
        GapRule(_GIVEN, 1, "notable", "没看到已知：手上有哪些材料或事实。"),
        GapRule(_CONSTRAINT, 1, "notable", "没看到约束：哪些条件不能动。"),
        GapRule(_ACTION, 1, "notable", "没看到已经试过什么、结果如何。"),
        GapRule(_CHECK, 1, "notable", "没看到判定标准：什么算「解决了」。"),
    ),
}

_VERIFIERS: dict[IntakeFramework, StructureVerifier] = {
    framework: RuleBasedVerifier(framework, rules) for framework, rules in _RULES.items()
}


def verifier_for(framework: IntakeFramework) -> StructureVerifier:
    return _VERIFIERS[framework]


def structure_gaps(framework: IntakeFramework, graph: GenericGraph) -> tuple[StructureGap, ...]:
    """Findings in rule order: blocking gaps first, then notable ones.

    An empty graph produces every requirement as a gap. That is correct — a
    submission with no recognisable structure is missing all of it — which is
    why the caller decides whether an attempt was given at all before showing
    this (see ``application/intake.py``).
    """

    return verifier_for(framework).check(graph)
