"""The generic problem graph: what a problem is made of, not just a solution.

Phase 0 let an open domain start a session and stop at the intake. Phase 1 needs
something to compare a submission *against* that is not a solution graph: a math
graph is a chain of steps, but a code bug, a life decision or a research question
has goals, constraints, assumptions, options, risks and a next experiment.
``GenericGraph`` is that shape.

It is deliberately not a diagnosis model: no hypotheses, no posterior, no
confidence. A node records that the text *mentions* a goal/constraint/option — it
never records that the goal is the right one. Every check downstream can
therefore only say "没看到" or "看到了", the same epistemic level as the NONE
tier's structure hint (chapter 13 §13.3). Anything stronger needs a verifier
(``application/diagnosis/verification.py`` for claims, the code sandbox for executable
work), not a bigger graph.

``NodeKind`` follows plan §4.1. ``DECISION`` means *one candidate option*, not
"the choice": a decision problem has two or more, and "什么都不做" is one of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from synapse.domain.problem.claims import VerificationClaim

NodeSource = Literal["student", "system"]
ClaimKind = Literal["formal", "empirical"]
ClaimStatus = Literal["pass", "fail", "unknown"]


class NodeKind(StrEnum):
    GOAL = "goal"
    GIVEN = "given"
    CONSTRAINT = "constraint"
    ASSUMPTION = "assumption"
    PLAN = "plan"
    ACTION = "action"
    EVIDENCE = "evidence"
    CHECK = "check"
    DECISION = "decision"
    RISK = "risk"
    NEXT = "next"


# User-facing labels. Kept beside the enum so gap messages and the intake view
# do not grow a second copy that can drift.
KIND_LABELS: dict[NodeKind, str] = {
    NodeKind.GOAL: "目标",
    NodeKind.GIVEN: "已知",
    NodeKind.CONSTRAINT: "约束",
    NodeKind.ASSUMPTION: "假设",
    NodeKind.PLAN: "计划/推理",
    NodeKind.ACTION: "尝试",
    NodeKind.EVIDENCE: "证据",
    NodeKind.CHECK: "检查",
    NodeKind.DECISION: "选项",
    NodeKind.RISK: "风险",
    NodeKind.NEXT: "下一步",
}

KIND_ORDER: tuple[NodeKind, ...] = tuple(NodeKind)


@dataclass(frozen=True, slots=True)
class GenericNode:
    """One mentioned piece of a problem. ``text`` is copied, not interpreted."""

    id: str
    kind: NodeKind
    text: str
    source: NodeSource = "student"

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass(frozen=True, slots=True)
class EmpiricalClaim:
    """A structured physical/empirical statement, never extracted from prose.

    The physics verifier has always required structured data (``equation`` or
    ``expression`` plus units); a generic graph may now carry exactly that shape
    so the same checker can run on it. ``equation`` and ``expression`` are
    mutually exclusive, and ``expression`` needs ``unit``. An empty claim is not
    a "pass": the adapter returns ``unknown`` and says what is missing.
    """

    equation: str | None = None
    expression: str | None = None
    unit: str | None = None
    units: Mapping[str, str] = field(default_factory=dict)
    values: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.equation is not None and self.expression is not None:
            raise ValueError("empirical claim cannot carry both equation and expression")
        if self.equation is None and self.expression is None:
            raise ValueError("empirical claim needs equation or expression")
        if self.expression is not None and not (self.unit or "").strip():
            raise ValueError("empirical expression needs a declared unit")


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    """One verifier's outcome, persisted with the problem.

    ``unknown`` is a first-class result: no claim, no structured data, no
    verifier, or a search that could not decide. It is never rendered as a pass.
    """

    kind: ClaimKind
    status: ClaimStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != "fail"


@dataclass(frozen=True, slots=True)
class GenericGraph:
    """A flat set of mentioned pieces, not a step chain and not evidence.

    ``version`` is the shape of this record, not a promise tier: ``g1`` is the
    Phase 1a cue extraction, ``g2`` is a generated graph that may also carry a
    formal or empirical claim. Neither upgrades what the product may claim — the
    domain's verification mode does that.

    ``formal``/``empirical`` are optional on purpose. A graph with no claim is
    the normal case for a decision, a writing task or a code bug; the verifiers
    then return ``unknown`` instead of pretending a check ran.
    """

    problem_id: str
    version: Literal["g1", "g2"]
    nodes: tuple[GenericNode, ...]
    formal: VerificationClaim | None = None
    empirical: EmpiricalClaim | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for node in self.nodes:
            if not node.id:
                raise ValueError("generic node id is empty")
            if node.id in seen:
                raise ValueError(f"duplicate generic node id: {node.id}")
            if not node.text.strip():
                raise ValueError(f"generic node {node.id} has no text")
            seen.add(node.id)
        if (self.formal is not None or self.empirical is not None) and self.version != "g2":
            raise ValueError("formal/empirical claims require generic graph version g2")

    def of_kind(self, kind: NodeKind) -> tuple[GenericNode, ...]:
        return tuple(node for node in self.nodes if node.kind is kind)

    def has(self, kind: NodeKind) -> bool:
        return any(node.kind is kind for node in self.nodes)

    def kinds(self) -> tuple[NodeKind, ...]:
        """Kinds present, in plan order, deduplicated."""

        present = {node.kind for node in self.nodes}
        return tuple(kind for kind in KIND_ORDER if kind in present)

    def absent(self, kinds: Iterable[NodeKind]) -> tuple[NodeKind, ...]:
        return tuple(kind for kind in kinds if not self.has(kind))

    def __len__(self) -> int:
        return len(self.nodes)
