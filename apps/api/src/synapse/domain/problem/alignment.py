"""Step alignment strategies.

The MVP uses a deterministic keyword aligner so the walking skeleton can be
tested without a model. The Protocol is the seam for a model-backed aligner.

M2.5 S5 adds a second, *graph-derived* aligner for problems that have no
hand-written rules (generated graphs). The two are not interchangeable: the
rule aligner was tuned against labelled student work and stays the baseline for
the annotated catalog (chapter 12 §12.7, red line 3), while the graph aligner
only checks whether each step was *mentioned at all*. See its docstring for why
that is the honest ceiling without a model-backed aligner (T5 is out of scope).
"""

from __future__ import annotations

import re
from typing import Protocol

from synapse.domain.problem.models import (
    AlignmentResult,
    Problem,
    StudentAttempt,
)

_NODE_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("n1", ("x>0", "定义域"), "没有确认定义域 x>0"),
    ("n2", ("最大", "恒成立", "f(1/a)"), "没有把“对所有 x>0 成立”转成最大值≤0"),
    ("n3", ("a<=0", "a≤0", "a=0", "a<0"), "没有单独检查 a≤0 / a=0 的边界"),
    ("n4", ("无上界", "趋于", "+∞", "a<=0时"), "没有讨论 a≤0 时函数无上界"),
    ("n5", ("1/a", "1/e", "f'", "导数"), "没有完成 a>0 时的最值计算"),
    ("n6", ("合并", "并集", "综上", "排除", "只保留"), "没有对参数分支做取舍（排除不满足的分支）"),
)

_NODE_LABELS = {
    "n1": "定义域",
    "n2": "恒成立转最值",
    "n3": "参数分类",
    "n4": "a≤0 时的无上界",
    "n5": "导数与最值计算",
    "n6": "分支合并",
}

# A comparison or formula fragment: "x>0", "f'(x)=1/x-a", "a>=1/e".
_FORMULA = re.compile(r"[a-z0-9.+\-*/^()']*(?:<=|>=|<|>|=)[a-z0-9.+\-*/^()']*")
# A letter compared against something: used to notice a two-sided case split.
_SIDE = re.compile(r"([a-z])\s*(<=|>=|<|>)")


def normalize(text: str) -> str:
    text = text.lower().strip()
    return (
        text.replace("≤", "<=")
        .replace("≥", ">=")
        .replace("＜", "<")
        .replace("＞", ">")
        .replace("＇", "'")
        .replace("’", "'")
        .replace("（", "(")
        .replace("）", ")")
        .replace("，", ",")
        .replace("。", ".")
        .replace("；", ";")
        .replace(" ", "")
        .replace("\n", "")
    )


class StepAligner(Protocol):
    """Port: turn an attempt into the first missing cognitive step."""

    def align(self, problem: Problem, attempt: StudentAttempt) -> AlignmentResult: ...


class RuleBasedAligner:
    """Deterministic aligner for the M1 seed problem.

    It is intentionally simple: each reference node has observable keywords.
    The first missing node in graph order is the divergence. A model-backed
    aligner can implement the same Protocol later.
    """

    def align(self, problem: Problem, attempt: StudentAttempt) -> AlignmentResult:
        work = normalize(attempt.work)
        answer = normalize(attempt.answer)

        if attempt.knows_nothing and not work:
            return AlignmentResult(
                first_divergence="n1",
                matched_node_ids=(),
                missing_node_ids=("n1",),
                evidence=("学生自述完全不会，且没有提供过程",),
                excluded=(),
            )

        haystack = work or answer
        missing: list[str] = []
        evidence: list[str] = []
        excluded: list[str] = []

        for node_id, keywords, reason in _NODE_RULES:
            if any(keyword in haystack for keyword in keywords):
                excluded.append(_NODE_LABELS[node_id])
            else:
                missing.append(node_id)
                evidence.append(reason)

        if not missing:
            # A complete process is not a diagnosis target; the caller should
            # treat this as "no gap detected" rather than invent one.
            return AlignmentResult(
                first_divergence="none",
                matched_node_ids=tuple(_NODE_LABELS),
                missing_node_ids=(),
                evidence=("过程覆盖了定义域、最值、参数分类与合并",),
                excluded=tuple(_NODE_LABELS.values()),
            )

        matched = tuple(node for node in _NODE_LABELS if node not in missing)
        # Keep only nodes that exist in this graph, in graph order.
        graph_order = [node.id for node in problem.graph.nodes]
        matched = tuple(node for node in graph_order if node in matched)
        missing = [node for node in graph_order if node in missing]
        first = missing[0]
        if not evidence:
            evidence.append(f"缺少 {first} 对应的步骤")
        return AlignmentResult(
            first_divergence=first,
            matched_node_ids=matched,
            missing_node_ids=tuple(missing),
            evidence=tuple(evidence[:4]),
            excluded=tuple(dict.fromkeys(excluded))[:4],
        )


class TypeCueAligner:
    """Align a generated graph without per-problem rules (M2.5 S5 ②).

    What it can and cannot do, stated up front:

    * it checks whether a step was **mentioned**, using cues that belong to the
      node *type* (seven of them, chapter 3) plus "did the student write any
      formula at all" — it never judges whether the step was done correctly;
    * therefore it can catch an **omitted** step and can never catch a wrong
      one. The probes do the discriminating; this only picks a starting point
      and a card node;
    * a node whose type has no cue match is reported missing even if the
      student did the work in their head, so the card must phrase the finding
      as "your process does not show this step", never as a misconception.

    The rule aligner (``RuleBasedAligner``) was hand-tuned against labelled
    student work and stays the baseline for the annotated catalog; this one
    exists because a generated graph has no such labels. Both implement the
    same Protocol, so the caller picks by problem, not by code path.
    """

    # Cues are deliberately multi-character: single characters like 时/得 match
    # almost any solution and would make every step look covered.
    _CUES: dict[str, tuple[str, ...]] = {
        "READ": ("定义域", "题意", "已知", "读题", "条件"),
        "CONCEPT": ("等价", "恒成立", "定理", "定义", "转化"),
        "CONDITION": ("分类", "讨论", "情况", "边界", "端点"),
        "STRATEGY": ("思路", "构造", "转化为", "考虑"),
        "TRANSFORM": ("化简", "代入", "整理", "变形"),
        "COMPUTE": ("求导", "导数", "计算", "解得", "联立"),
        "CHECK": ("检验", "综上", "排除", "回代", "验证"),
    }
    # Node types whose absence is normally total: a student who computes
    # anything has touched them, even without naming the operation.
    _FORMULA_TYPES = frozenset({"COMPUTE", "TRANSFORM"})

    def align(self, problem: Problem, attempt: StudentAttempt) -> AlignmentResult:
        graph = problem.graph
        if attempt.knows_nothing and not attempt.work.strip():
            first = graph.nodes[0].id if graph.nodes else "none"
            return AlignmentResult(
                first_divergence=first,
                matched_node_ids=(),
                missing_node_ids=tuple(node.id for node in graph.nodes),
                evidence=("学生自述完全不会，且没有提供过程",),
                excluded=(),
            )

        haystack = normalize(attempt.work or attempt.answer)
        has_formula = bool(_FORMULA.search(haystack))

        matched: list[str] = []
        missing: list[str] = []
        evidence: list[str] = []
        excluded: list[str] = []
        for node in graph.nodes:
            text = normalize(node.text)
            if self._mentions_cue(node.type, haystack, has_formula) or self._shares_words(
                text, haystack
            ):
                matched.append(node.id)
                excluded.append(node.text)
            else:
                missing.append(node.id)
                evidence.append(f"过程里没有出现「{node.text}」这一步")

        if not missing:
            return AlignmentResult(
                first_divergence="none",
                matched_node_ids=tuple(matched),
                missing_node_ids=(),
                evidence=("过程覆盖了图中每一步；本轮没有可诊断的断点。",),
                excluded=tuple(dict.fromkeys(excluded)),
            )
        return AlignmentResult(
            first_divergence=missing[0],
            matched_node_ids=tuple(matched),
            missing_node_ids=tuple(missing),
            evidence=tuple(evidence[:4]),
            excluded=tuple(dict.fromkeys(excluded))[:4],
        )

    def _mentions_cue(self, node_type: str, haystack: str, has_formula: bool) -> bool:
        if node_type in self._FORMULA_TYPES and has_formula:
            return True
        if node_type == "CONDITION" and self._splits_parameter(haystack):
            # A student who compares the parameter in two directions ("a<=0 …",
            # "a>0 …") has split cases even without writing 分类/讨论.
            return True
        return any(cue in haystack for cue in self._CUES.get(node_type, ()))

    @staticmethod
    def _splits_parameter(haystack: str) -> bool:
        """True when both directions of one letter appear as comparisons."""
        sides: dict[str, set[str]] = {}
        for match in _SIDE.finditer(haystack):
            letter = match.group(1)
            direction = "<" if match.group(2).startswith("<") else ">"
            sides.setdefault(letter, set()).add(direction)
        return any({"<", ">"} <= seen for seen in sides.values())

    @staticmethod
    def _shares_words(node_text: str, haystack: str) -> bool:
        """Backstop for prose nodes: half of the node's 3-grams appear in the work.

        Generated node text is often prose with no formula and no type cue; the
        student may still quote it almost verbatim ("把恒成立转化为最值").
        """

        grams = {node_text[index : index + 3] for index in range(len(node_text) - 2)}
        if not grams:
            return False
        hit = sum(1 for gram in grams if gram in haystack)
        return hit / len(grams) >= 0.5


class CompositeAligner:
    """Pick the aligner by problem: annotated catalog vs generated graph.

    Dispatch lives here rather than inside an aligner so neither strategy needs
    to know that the other exists.
    """

    def __init__(
        self,
        *,
        annotated: StepAligner,
        generated: StepAligner,
        annotated_ids: frozenset[str],
    ) -> None:
        self._annotated = annotated
        self._generated = generated
        self._annotated_ids = annotated_ids

    def align(self, problem: Problem, attempt: StudentAttempt) -> AlignmentResult:
        if problem.id in self._annotated_ids:
            return self._annotated.align(problem, attempt)
        return self._generated.align(problem, attempt)


def word_overlap(text: str, other: str, n: int = 5) -> float:
    """Character n-gram overlap, used by the answer-leak guard.

    Kept here as a tiny pure helper so both the guard and tests can reuse it
    without importing an LLM package.
    """

    left = re.sub(r"\s+", "", normalize(text))
    right = re.sub(r"\s+", "", normalize(other))
    if len(left) < n or len(right) < n:
        return 0.0
    left_grams = {left[i : i + n] for i in range(len(left) - n + 1)}
    right_grams = {right[i : i + n] for i in range(len(right) - n + 1)}
    if not left_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams)
