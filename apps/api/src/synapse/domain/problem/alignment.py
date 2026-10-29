"""Step alignment strategies.

The MVP uses a deterministic keyword aligner so the walking skeleton can be
tested without a model. The Protocol is the seam for a model-backed aligner.
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
