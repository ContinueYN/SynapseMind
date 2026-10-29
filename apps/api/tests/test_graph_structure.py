"""M2.5 S4: the structural rules the JSON schema cannot express."""

from __future__ import annotations

from dataclasses import replace

from synapse.domain.problem.graph_structure import (
    fingerprint,
    quality_notes,
    review,
)
from synapse.domain.problem.models import Probe, SolutionGraph, SolutionNode

TARGETS = frozenset({"H_L1", "H_L2", "H_L4"})


def _probe(
    probe_id: str = "p1",
    *,
    targets: tuple[str, ...] = ("H_L2", "H_L1"),
    question: str = "这一步先做什么？",
    options: tuple[str, ...] = ("A", "B"),
    evidence: dict[str, dict[str, float]] | None = None,
) -> Probe:
    return Probe(
        id=probe_id,
        question=question,
        options=options,
        targets=targets,
        evidence=evidence or {},
    )


def _node(
    node_id: str,
    *,
    node_type: str = "READ",
    text: str = "读题并确认条件",
    probes: tuple[Probe, ...] = (),
    demand: dict[str, float] | None = None,
) -> SolutionNode:
    return SolutionNode(
        id=node_id,
        type=node_type,
        text=text,
        demand=demand or {},
        probes=probes,
    )


def _graph(
    nodes: tuple[SolutionNode, ...],
    edges: tuple[tuple[str, str], ...] = (),
) -> SolutionGraph:
    return SolutionGraph(
        problem_id="P_DERIV_002",
        version="g1",
        stem="求函数的单调区间",
        nodes=nodes,
        edges=edges,
    )


def _clean_graph() -> SolutionGraph:
    return _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="CONCEPT"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )


def test_a_clean_graph_needs_no_repair() -> None:
    check = review(_clean_graph(), allowed_targets=TARGETS)

    assert check.ok
    assert check.repairs == ()
    assert check.graph.nodes[0].id == "n1"


def test_renumbers_ids_and_rewrites_edges() -> None:
    graph = _graph(
        (
            _node("1", probes=(_probe("p1"),)),
            _node("2", node_type="COMPUTE"),
            _node("3", node_type="CHECK"),
        ),
        (("1", "2"), ("2", "3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert [node.id for node in check.graph.nodes] == ["n1", "n2", "n3"]
    assert check.graph.edges == (("n1", "n2"), ("n2", "n3"))
    assert "ids_renumbered" in check.repairs


def test_drops_dangling_edges_and_self_loops() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3"), ("n2", "n9"), ("n3", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert check.graph.edges == (("n1", "n2"), ("n2", "n3"))
    assert {"edge_dropped", "self_loop_dropped"} <= set(check.repairs)


def test_cuts_a_cycle_deterministically() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3"), ("n3", "n1")),
    )

    first = review(graph, allowed_targets=TARGETS)
    second = review(graph, allowed_targets=TARGETS)

    assert first.graph.edges == (("n1", "n2"), ("n2", "n3"))
    assert "cycle_cut" in first.repairs
    assert first.graph.edges == second.graph.edges


def test_duplicate_node_ids_are_an_issue_not_a_repair() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n1", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n3"),),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert not check.ok
    assert check.repairs == ()
    assert check.issues[0].startswith("duplicate_node_id")


def test_isolated_node_is_not_part_of_a_solution() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"),),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert any(issue.startswith("isolated_node: n3") for issue in check.issues)


def test_unknown_node_type_is_reported() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="SOLVE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert not check.ok
    assert any("unknown_node_type" in issue for issue in check.issues)


def test_probe_rules_require_two_known_targets() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1", targets=("H_L2",)),)),
            _node("n2", node_type="COMPUTE", probes=(_probe("p2", targets=("H_X", "H_L2")),)),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert any("probe_targets_too_few" in issue for issue in check.issues)
    assert any("probe_target_unknown: p2" in issue for issue in check.issues)


def test_require_evidence_flags_a_probe_without_weights() -> None:
    check = review(_clean_graph(), allowed_targets=TARGETS, require_evidence=True)

    assert not check.ok
    assert "probe_evidence_missing: p1 没有为选项生成权重" in check.issues


def test_complete_evidence_passes_review() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": -0.40, "H_L1": 0.20},
                            "B": {"H_L2": 0.45, "H_L1": -0.10},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert check.ok
    assert check.graph.node("n1").probes[0].evidence["A"]["H_L2"] == -0.40


def test_every_option_needs_weights() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={"A": {"H_L2": -0.40, "H_L1": 0.20}},
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert any("probe_evidence_option_missing: p1" in issue for issue in check.issues)


def test_an_empty_option_is_a_wasted_turn() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": -0.40, "H_L1": 0.20},
                            "B": {"H_L2": 0.0, "H_L1": 0.0},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert any("probe_evidence_empty: p1 的选项 B" in issue for issue in check.issues)


def test_evidence_cannot_target_a_hypothesis_outside_the_probe() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": -0.40, "H_L4": 0.20},
                            "B": {"H_L2": 0.45, "H_L1": -0.10},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert any("probe_evidence_target_unknown: p1" in issue for issue in check.issues)


def test_every_target_must_be_used_by_some_option() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": -0.40},
                            "B": {"H_L2": 0.45},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert any("probe_evidence_target_unused: p1 的目标 H_L1" in issue for issue in check.issues)


def test_all_positive_weights_do_not_discriminate() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": 0.40, "H_L1": 0.20},
                            "B": {"H_L2": 0.30, "H_L1": 0.10},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert any("probe_evidence_no_contrast: p1" in issue for issue in check.issues)


def test_evidence_weights_are_clamped_and_reported() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                probes=(
                    _probe(
                        "p1",
                        evidence={
                            "A": {"H_L2": -2.0, "H_L1": 0.20},
                            "B": {"H_L2": 1.5, "H_L1": -0.10},
                        },
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS, require_evidence=True)

    assert check.ok
    evidence = check.graph.node("n1").probes[0].evidence
    assert evidence["A"]["H_L2"] == -1.0
    assert evidence["B"]["H_L2"] == 1.0
    assert "evidence_clamped" in check.repairs


def test_missing_probes_are_reported() -> None:
    graph = _graph(
        (
            _node("n1"),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert "no_probes: 解法图至少要有一个探针" in check.issues


def test_probe_with_fewer_than_two_options_is_reported() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1", options=("唯一选项",)),)),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert any("probe_options_too_few: p1" in issue for issue in check.issues)


def test_clamps_truncates_and_drops_unknown_demand_keys() -> None:
    graph = _graph(
        (
            _node(
                "n1",
                text="长" * 600,
                demand={"V": 1.4, "Gf": -0.2, "ZZ": 0.5},
                probes=(
                    _probe(
                        "p1",
                        question="问" * 400,
                        options=("A", "B", "C", "D", "E"),
                    ),
                ),
            ),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert check.ok
    node = check.graph.node("n1")
    assert len(node.text) == 500
    assert node.demand == {"V": 1.0, "Gf": 0.0}
    assert len(node.probes[0].options) == 4
    assert len(node.probes[0].question) == 300
    assert {
        "node_text_truncated",
        "demand_clamped",
        "demand_key_dropped",
        "probe_options_truncated",
        "probe_question_truncated",
    } <= set(check.repairs)


def test_duplicate_probe_ids_are_dropped_visibly() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"), _probe("p1"))),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="CHECK"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    check = review(graph, allowed_targets=TARGETS)

    assert check.ok
    assert len(check.graph.probes()) == 1
    assert "probe_id_dropped" in check.repairs


def test_fingerprint_tracks_structure_not_wording() -> None:
    base = _clean_graph()
    reworded = base.nodes[0]
    changed = replace(
        base,
        nodes=(replace(reworded, text="换一种说法"), *base.nodes[1:]),
    )
    extra_edge = replace(base, edges=(*base.edges, ("n1", "n3")))

    assert fingerprint(base) == fingerprint(changed)
    assert fingerprint(base) != fingerprint(extra_edge)
    assert len(fingerprint(base)) == 16


def test_quality_notes_are_advisory() -> None:
    graph = _graph(
        (
            _node("n1", probes=(_probe("p1"),)),
            _node("n2", node_type="COMPUTE"),
            _node("n3", node_type="COMPUTE"),
        ),
        (("n1", "n2"), ("n2", "n3")),
    )

    assert quality_notes(graph) == ("no_check_node", "few_probes")
