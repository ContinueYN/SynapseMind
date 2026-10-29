"""Structural rules for generated solution graphs (M2.5 S4).

``specs/solution-graph.schema.json`` is the floor, not the whole contract: a
graph can satisfy every field and still be unusable. Dangling edges, cycles and
probes that separate no hypotheses are all schema-valid.

This module draws the line the schema cannot:

- **repairs** never invent content. They renumber ids, drop references to
  missing nodes, break cycles, de-duplicate, and clamp values into range. Every
  applied repair is reported, so a build is never silently "fixed".
- **issues** are things only the model can fix (an unknown node type, a probe
  with one target, an isolated step). They fail the attempt and are handed back
  to the model as feedback for the single retry.

Rule of thumb: if fixing it would change *what a step says* or *what a probe
separates*, it is an issue.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace

from synapse.domain.problem.models import Probe, SolutionGraph, SolutionNode

NODE_TYPES = (
    "READ",
    "CONCEPT",
    "CONDITION",
    "STRATEGY",
    "TRANSFORM",
    "COMPUTE",
    "CHECK",
)
DEMAND_KEYS = ("V", "Gf", "Gv", "WM", "Gs", "LTS", "M")

MIN_NODES = 3
MAX_NODES = 20
MAX_NODE_TEXT = 500
MAX_COMMON_ERRORS = 8
MAX_PROBES_PER_NODE = 10
MAX_QUESTION = 300
MAX_OPTIONS = 4
MIN_PROBE_OPTIONS = 2
MAX_STEM = 4000
MIN_PROBE_TARGETS = 2
HINT_LEVELS = (0, 1, 2, 3)

FINGERPRINT_LENGTH = 16


@dataclass(frozen=True, slots=True)
class GraphCheck:
    """The graph after mechanical repairs, plus what is still wrong."""

    graph: SolutionGraph
    repairs: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def review(
    graph: SolutionGraph,
    *,
    allowed_targets: Collection[str] | None = None,
    min_targets: int = MIN_PROBE_TARGETS,
) -> GraphCheck:
    """Repair what is mechanical and report what is not.

    ``allowed_targets`` is the hypothesis vocabulary a probe may target
    (``H_L1``/``H_L2``/``H_L4`` while the diagnosis layer is still the M1 one).
    ``None`` skips the membership check.
    """
    codes: set[str] = set()
    issues: list[str] = []

    node_ids = [node.id for node in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        # Renumbering would silently merge two different steps; let the model
        # fix it instead.
        return GraphCheck(
            graph=graph,
            repairs=(),
            issues=("duplicate_node_id: 节点 id 必须唯一",),
        )

    kept_nodes = list(graph.nodes[:MAX_NODES])
    if len(graph.nodes) > MAX_NODES:
        codes.add("node_limit")

    mapping = {node.id: f"n{index}" for index, node in enumerate(kept_nodes, start=1)}
    if any(node.id != mapping[node.id] for node in kept_nodes):
        codes.add("ids_renumbered")

    edges = _clean_edges(graph.edges, mapping, codes)

    seen_probe_ids: set[str] = set()
    nodes = tuple(
        _repair_node(node, mapping[node.id], seen_probe_ids, codes) for node in kept_nodes
    )

    stem = graph.stem
    if len(stem) > MAX_STEM:
        stem = stem[:MAX_STEM]
        codes.add("stem_truncated")

    if len(nodes) < MIN_NODES:
        issues.append(f"node_count: 节点数为 {len(nodes)}，至少需要 {MIN_NODES} 个")
    if len(nodes) >= 2 and not edges:
        issues.append("no_edges: 节点之间必须至少有一条依赖边")

    for node in nodes:
        if node.type not in NODE_TYPES:
            issues.append(f"unknown_node_type: {node.id} 的 type 是 {node.type!r}")
        if not node.text:
            issues.append(f"empty_node_text: {node.id} 没有步骤描述")

    issues.extend(_connectivity_issues(nodes, edges))

    total_probes = 0
    for node in nodes:
        for probe in node.probes:
            total_probes += 1
            if not probe.id:
                issues.append(f"empty_probe_id: {node.id} 上的探针缺少 id")
            if not probe.question:
                issues.append(f"empty_probe_question: {probe.id or node.id}")
            if len(probe.options) < MIN_PROBE_OPTIONS:
                issues.append(
                    f"probe_options_too_few: {probe.id or node.id} 只有 "
                    f"{len(probe.options)} 个选项，至少需要 {MIN_PROBE_OPTIONS} 个"
                )
            if len(probe.targets) < min_targets:
                issues.append(
                    f"probe_targets_too_few: {probe.id or node.id} 只指向 "
                    f"{len(probe.targets)} 个假设，至少需要 {min_targets} 个"
                )
            if allowed_targets is not None:
                for target in probe.targets:
                    if target not in allowed_targets:
                        issues.append(
                            f"probe_target_unknown: {probe.id or node.id} 指向 {target!r}"
                        )
    if total_probes == 0:
        issues.append("no_probes: 解法图至少要有一个探针")

    repaired = SolutionGraph(
        problem_id=graph.problem_id,
        version=graph.version,
        stem=stem,
        nodes=nodes,
        edges=edges,
    )
    return GraphCheck(graph=repaired, repairs=tuple(sorted(codes)), issues=tuple(issues))


def quality_notes(graph: SolutionGraph) -> tuple[str, ...]:
    """Non-blocking observations for the evaluation report, never for gating."""
    notes: list[str] = []
    if not any(node.type == "CHECK" for node in graph.nodes):
        notes.append("no_check_node")
    if len(graph.probes()) < 2:
        notes.append("few_probes")
    return tuple(notes)


def fingerprint(graph: SolutionGraph) -> str:
    """Stable structure digest: node ids/types plus the edge set (chapter 13 §13.6).

    Wording changes do not move it; adding a step or an edge does.
    """
    structure = {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "nodes": sorted((node.id, node.type) for node in graph.nodes),
        "edges": sorted(graph.edges),
    }
    encoded = json.dumps(structure, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def _repair_node(
    node: SolutionNode,
    new_id: str,
    seen_probe_ids: set[str],
    codes: set[str],
) -> SolutionNode:
    text = node.text.strip()
    if len(text) > MAX_NODE_TEXT:
        text = text[:MAX_NODE_TEXT]
        codes.add("node_text_truncated")

    demand: dict[str, float] = {}
    for key, raw in node.demand.items():
        if key not in DEMAND_KEYS:
            codes.add("demand_key_dropped")
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            codes.add("demand_value_dropped")
            continue
        if not math.isfinite(number):
            codes.add("demand_value_dropped")
            continue
        clamped = min(max(number, 0.0), 1.0)
        if clamped != number:
            codes.add("demand_clamped")
        demand[key] = clamped

    common_errors = tuple(node.common_errors[:MAX_COMMON_ERRORS])
    if len(node.common_errors) > MAX_COMMON_ERRORS:
        codes.add("common_errors_truncated")

    if len(node.probes) > MAX_PROBES_PER_NODE:
        codes.add("probe_limit")
    probes: list[Probe] = []
    for probe in node.probes[:MAX_PROBES_PER_NODE]:
        repaired = _repair_probe(probe, seen_probe_ids, codes)
        if repaired is not None:
            probes.append(repaired)

    return replace(
        node,
        id=new_id,
        text=text,
        demand=demand,
        common_errors=common_errors,
        probes=tuple(probes),
    )


def _repair_probe(
    probe: Probe,
    seen_probe_ids: set[str],
    codes: set[str],
) -> Probe | None:
    probe_id = probe.id.strip()
    if probe_id in seen_probe_ids:
        # A duplicate id would make the audit and the answer mapping ambiguous;
        # there is no way to rename it without guessing, so drop the later one.
        codes.add("probe_id_dropped")
        return None
    seen_probe_ids.add(probe_id)

    question = probe.question.strip()
    if len(question) > MAX_QUESTION:
        question = question[:MAX_QUESTION]
        codes.add("probe_question_truncated")

    options = tuple(option.strip() for option in probe.options[:MAX_OPTIONS])
    if len(probe.options) > MAX_OPTIONS:
        codes.add("probe_options_truncated")

    targets = _dedupe(target.strip() for target in probe.targets)
    if len(targets) != len(probe.targets):
        codes.add("probe_targets_deduped")

    hint_level = probe.hint_level
    if hint_level not in HINT_LEVELS:
        hint_level = min(max(hint_level, HINT_LEVELS[0]), HINT_LEVELS[-1])
        codes.add("hint_level_clamped")

    return replace(
        probe,
        id=probe_id,
        question=question,
        options=options,
        targets=targets,
        hint_level=hint_level,
    )


def _clean_edges(
    edges: tuple[tuple[str, str], ...],
    mapping: dict[str, str],
    codes: set[str],
) -> tuple[tuple[str, str], ...]:
    kept: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if len(edge) != 2:
            codes.add("edge_malformed")
            continue
        source, target = edge
        if source not in mapping or target not in mapping:
            # A model that dropped a node leaves its edges behind; keeping one
            # would make the graph unreadable, so the edge goes, not the node.
            codes.add("edge_dropped")
            continue
        pair = (mapping[source], mapping[target])
        if pair[0] == pair[1]:
            codes.add("self_loop_dropped")
            continue
        if pair in seen:
            codes.add("duplicate_edge_dropped")
            continue
        seen.add(pair)
        kept.append(pair)
    return _break_cycles(kept, codes)


def _break_cycles(
    edges: list[tuple[str, str]],
    codes: set[str],
) -> tuple[tuple[str, str], ...]:
    """Keep the earliest edges that leave the graph acyclic; drop the closers."""
    kept: list[tuple[str, str]] = []
    for edge in edges:
        kept.append(edge)
        if _has_cycle(kept):
            kept.pop()
            codes.add("cycle_cut")
    return tuple(kept)


def _has_cycle(edges: Iterable[tuple[str, str]]) -> bool:
    outgoing: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}
    for source, target in edges:
        outgoing.setdefault(source, []).append(target)
        indegree.setdefault(source, 0)
        indegree[target] = indegree.get(target, 0) + 1

    ready = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for neighbour in outgoing.get(node, []):
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                ready.append(neighbour)
    return visited != len(indegree)


def _connectivity_issues(
    nodes: tuple[SolutionNode, ...],
    edges: tuple[tuple[str, str], ...],
) -> list[str]:
    """A step with no dependency at all is not part of the solution."""
    if len(nodes) < 2 or not edges:
        return []
    adjacency: dict[str, set[str]] = {node.id: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)

    start = nodes[0].id
    reached = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in adjacency[node]:
            if neighbour not in reached:
                reached.add(neighbour)
                queue.append(neighbour)

    return [
        f"isolated_node: {node_id} 与其它步骤没有依赖关系"
        for node_id in adjacency
        if node_id not in reached
    ]


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
