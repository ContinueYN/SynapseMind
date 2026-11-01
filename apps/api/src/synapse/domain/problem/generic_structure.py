"""Structural rules for a generated generic graph.

The generic graph is allowed to be incomplete: a decision may not have a cost
list yet, a code problem may not have a reproduction. What it may **not** do is
smuggle in a verdict or a recommendation. These rules therefore check shape and
product boundaries only:

* 3–10 nodes, a goal, and (for a decision) at least two options;
* no single "correct answer" / "you should pick" wording in a node;
* one node per kind except ``DECISION``, where multiple options are the point;
* identical nodes collapse instead of padding the count.

They never inspect whether the goal is the right one. Error strings are
machine-readable codes with a human suffix, matching the solution-graph builder,
so the retry feedback can name the exact defect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from synapse.domain.problem.generic import GenericGraph, GenericNode, NodeKind

MIN_NODES = 3
MAX_NODES = 10

# Phrases that would turn a structure card into a verdict or a recommendation.
# They are deliberately narrow: "推荐系统" is a domain term, "推荐你选" is not.
_FORBIDDEN = (
    "你应该",
    "建议你选",
    "建议选",
    "最好选",
    "必须选",
    "推荐选",
    "正确答案",
    "唯一答案",
    "最优解",
)


@dataclass(frozen=True, slots=True)
class GenericReview:
    graph: GenericGraph
    repairs: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


def review(
    graph: GenericGraph,
    *,
    decision: bool = False,
) -> GenericReview:
    """Apply the shape rules; return a cleaned graph plus explicit defects.

    ``decision`` is a plain flag so this module stays in the domain layer: the
    caller turns its intake framework into the one structural question that
    matters here — "are there two options to compare?".
    """

    issues: list[str] = []
    repairs: list[str] = []
    nodes = list(graph.nodes)

    unique: list[GenericNode] = []
    seen_pairs: set[tuple[NodeKind, str]] = set()
    seen_kinds: set[NodeKind] = set()
    for node in nodes:
        text = " ".join(node.text.split())
        if not text:
            issues.append(f"empty_node_text: 节点 {node.id} 没有文字")
            continue
        if (node.kind, text) in seen_pairs:
            repairs.append("duplicate_node_removed")
            continue
        if node.kind is not NodeKind.DECISION and node.kind in seen_kinds:
            repairs.append("duplicate_kind_removed")
            continue
        seen_pairs.add((node.kind, text))
        seen_kinds.add(node.kind)
        unique.append(replace(node, text=text))

    if len(unique) < MIN_NODES:
        issues.append(f"node_count: 至少 {MIN_NODES} 个节点，当前 {len(unique)} 个")
    if len(unique) > MAX_NODES:
        issues.append(f"node_count: 最多 {MAX_NODES} 个节点，当前 {len(unique)} 个")

    if not any(node.kind is NodeKind.GOAL for node in unique):
        issues.append("no_goal: 必须有一个目标节点")

    if decision:
        options = [node for node in unique if node.kind is NodeKind.DECISION]
        if len(options) < 2:
            issues.append("decision_options_too_few: 决策问题至少要列出两个选项")

    for node in unique:
        for phrase in _FORBIDDEN:
            if phrase in node.text:
                issues.append(
                    f"recommendation_in_node: 节点 {node.id} 出现「{phrase}」；"
                    "只列选项与取舍，不排序、不推荐、不给唯一答案"
                )
                break

    cleaned = replace(graph, nodes=tuple(unique))
    return GenericReview(
        graph=cleaned,
        repairs=tuple(sorted(set(repairs))),
        issues=tuple(issues),
    )


def fingerprint(graph: GenericGraph) -> str:
    """Stable digest for cache/audit; the payload is explicit, not ``repr``."""

    payload = {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "nodes": [
            {"id": node.id, "kind": node.kind.value, "text": node.text, "source": node.source}
            for node in graph.nodes
        ],
        "formal": _formal_payload(graph),
        "empirical": _empirical_payload(graph),
    }
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _formal_payload(graph: GenericGraph) -> dict[str, object] | None:
    claim = graph.formal
    if claim is None:
        return None
    return {
        "kind": claim.kind,
        "parameter": claim.parameter,
        "variable": claim.variable,
        "variable_domain": claim.variable_domain,
        "expression": claim.expression,
        "relation": claim.relation,
        "intervals": [
            {
                "lower": interval.lower,
                "upper": interval.upper,
                "lower_inclusive": interval.lower_inclusive,
                "upper_inclusive": interval.upper_inclusive,
            }
            for interval in claim.intervals
        ],
    }


def _empirical_payload(graph: GenericGraph) -> dict[str, object] | None:
    claim = graph.empirical
    if claim is None:
        return None
    return {
        "equation": claim.equation,
        "expression": claim.expression,
        "unit": claim.unit,
        "units": dict(claim.units),
        "values": dict(claim.values),
    }
