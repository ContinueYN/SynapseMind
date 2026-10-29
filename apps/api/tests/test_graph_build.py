"""M2.5 S4: generated graphs must pass repair, structure rules and the spec."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from synapse.application.graph import GraphBuildFailed
from synapse.application.llm import LLMRequest, LLMResponse, LLMTimeout
from synapse.domain.problem.graph_structure import fingerprint
from synapse.domain.problem.models import ProblemDraft, SolutionGraph
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.llm.graph import (
    GRAPH_MAX_TOKENS,
    LLMGraphGenerator,
    to_payload,
    validate_payload,
)
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.subjects.math import MathPlugin

DRAFT = ProblemDraft(
    id="P_DERIV_002",
    text="已知函数 f(x)=x^3-3x^2+2，求 f(x) 的单调区间与极值。",
)

_VALID: dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "READ",
            "text": "读题，确认定义域与所求对象",
            "demand": {"V": 0.2},
        },
        {
            "id": "n2",
            "type": "CONCEPT",
            "text": "把单调性转化为导数符号问题",
            "demand": {"Gf": 0.5},
        },
        {
            "id": "n3",
            "type": "CONDITION",
            "text": "按参数 a≤0 与 a>0 分类讨论",
            "demand": {"WM": 0.5},
            "probes": [
                {
                    "id": "p1",
                    "question": "a=0 这个边界需要单独检查吗？",
                    "options": ["需要", "不需要", "不确定"],
                    "targets": ["H_L2", "H_L1"],
                    "evidence": {
                        "A": {"H_L2": -0.40, "H_L1": 0.20},
                        "B": {"H_L2": 0.45, "H_L1": -0.10},
                        "C": {"H_L1": 0.30},
                    },
                }
            ],
        },
        {
            "id": "n4",
            "type": "COMPUTE",
            "text": "求导并解出参数范围",
            "demand": {"Gf": 0.6},
            "probes": [
                {
                    "id": "p2",
                    "question": "导数的零点对应最大值还是最小值？",
                    "options": ["最大值", "最小值", "不确定"],
                    "targets": ["H_L4", "H_L2"],
                    "evidence": {
                        "A": {"H_L4": -0.35, "H_L2": 0.20},
                        "B": {"H_L4": 0.40, "H_L2": -0.15},
                        "C": {"H_L2": 0.25},
                    },
                }
            ],
        },
        {
            "id": "n5",
            "type": "CHECK",
            "text": "合并两支范围并检查端点",
            "demand": {"M": 0.3},
        },
    ],
    "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
}

VALID = json.dumps(_VALID, ensure_ascii=False)


class FakeClient:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        self.calls.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(
            text=reply,
            model="fake-1",
            latency_ms=42,
            prompt_tokens=120,
            completion_tokens=80,
        )


def _settings(**overrides: object) -> LLMSettings:
    values: dict[str, Any] = {
        "mode": "on",
        "api_key": "sk-test",
        "max_attempts": 2,
        "graph_timeout_s": 5.0,
    }
    values.update(overrides)
    return LLMSettings(**values)  # type: ignore[arg-type]


def _generator(
    client: FakeClient,
    auditor: InMemoryCallAuditor | None = None,
    **settings_overrides: object,
) -> LLMGraphGenerator:
    return LLMGraphGenerator(
        client,
        settings=_settings(**settings_overrides),
        auditor=auditor,
    )


def test_valid_graph_is_built_and_audited() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(VALID)

    result = _generator(client, auditor).generate(DRAFT)

    assert result.attempts == 1
    assert result.repairs == ()
    assert result.cached is False
    assert result.graph.problem_id == DRAFT.id
    assert result.graph.version == "g1"
    assert result.graph.stem == DRAFT.text
    assert result.fingerprint == fingerprint(result.graph)
    assert len(result.graph.nodes) == 5
    assert len(result.graph.probes()) == 2
    assert client.calls[0].purpose == "graph_build"
    assert client.calls[0].max_tokens == GRAPH_MAX_TOKENS

    (entry,) = auditor.entries
    assert entry.kind == "graph_build"
    assert entry.schema_ok is True
    assert entry.retried is False
    assert entry.model == "fake-1"
    assert entry.prompt_version == "graph-v2"
    assert entry.graph_fingerprint == result.fingerprint


def test_bad_json_is_retried_with_feedback() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient("这不是 JSON", VALID)

    result = _generator(client, auditor).generate(DRAFT)

    assert result.attempts == 2
    assert len(client.calls) == 2
    assert "未通过校验" in client.calls[1].user
    first, second = auditor.entries
    assert first.schema_ok is False
    assert first.fallback_reason == "bad_json"
    assert second.schema_ok is True
    assert second.retried is True


def test_two_bad_replies_fail_explicitly() -> None:
    client = FakeClient("nope", "{not json either")

    with pytest.raises(GraphBuildFailed) as info:
        _generator(client).generate(DRAFT)

    assert info.value.reason == "bad_json"
    assert info.value.attempts == 2
    assert len(client.calls) == 2


def test_mechanical_repairs_are_applied_and_reported() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"] = [
        {**node, "id": str(index + 1)} for index, node in enumerate(payload["nodes"])
    ]
    payload["edges"] = [
        ["1", "2"],
        ["2", "3"],
        ["3", "4"],
        ["4", "5"],
        ["5", "2"],  # closes a cycle
        ["2", "9"],  # dangling
        ["1", "1"],  # self loop
    ]

    result = _generator(FakeClient(json.dumps(payload, ensure_ascii=False))).generate(DRAFT)

    assert result.graph.edges == (
        ("n1", "n2"),
        ("n2", "n3"),
        ("n3", "n4"),
        ("n4", "n5"),
    )
    assert {
        "ids_renumbered",
        "cycle_cut",
        "edge_dropped",
        "self_loop_dropped",
    } <= set(result.repairs)


def test_probe_with_one_target_is_retried_then_fixed() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"][2]["probes"][0]["targets"] = ["H_L2"]
    client = FakeClient(json.dumps(payload, ensure_ascii=False), VALID)

    result = _generator(client).generate(DRAFT)

    assert result.attempts == 2
    assert "probe_targets_too_few" in client.calls[1].user


def test_unknown_node_type_fails_after_the_retry() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"][1]["type"] = "SOLVE"
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "unknown_node_type" in info.value.detail


def test_too_few_nodes_is_degenerate() -> None:
    first, second = copy.deepcopy(_VALID["nodes"][:2])
    second["probes"] = [copy.deepcopy(_VALID["nodes"][3]["probes"][0])]
    payload = {"nodes": [first, second], "edges": [["n1", "n2"]]}
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(DRAFT)

    assert info.value.reason == "degenerate"
    assert "node_count" in info.value.detail


def test_cache_returns_the_same_build_without_a_second_call() -> None:
    client = FakeClient(VALID, VALID)
    generator = _generator(client)

    first = generator.generate(DRAFT)
    second = generator.generate(DRAFT)

    assert len(client.calls) == 1
    assert second.cached is True
    assert second.fingerprint == first.fingerprint

    other = generator.generate(ProblemDraft(id="P_DERIV_003", text=DRAFT.text))
    assert len(client.calls) == 2
    assert other.graph.problem_id == "P_DERIV_003"


def test_timeout_is_not_retried() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(LLMTimeout("slow"))

    with pytest.raises(GraphBuildFailed) as info:
        _generator(client, auditor).generate(DRAFT)

    assert info.value.reason == "timeout"
    assert len(client.calls) == 1
    (entry,) = auditor.entries
    assert entry.fallback_reason == "timeout"


def test_disabled_mode_refuses_before_calling_the_model() -> None:
    client = FakeClient(VALID)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(client, mode="off").generate(DRAFT)

    assert info.value.reason == "disabled"
    assert client.calls == []


def test_invalid_draft_id_is_rejected() -> None:
    client = FakeClient(VALID)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(client).generate(ProblemDraft(id="P-bad", text=DRAFT.text))

    assert info.value.reason == "invalid_draft"
    assert client.calls == []


def test_evidence_is_serialised_for_each_option() -> None:
    result = _generator(FakeClient(VALID)).generate(DRAFT)

    payload = to_payload(result.graph)
    probe = payload["nodes"][2]["probes"][0]
    assert probe["evidence"] == {
        "A": {"H_L2": -0.40, "H_L1": 0.20},
        "B": {"H_L2": 0.45, "H_L1": -0.10},
        "C": {"H_L1": 0.30},
    }


def test_missing_evidence_is_retried_with_feedback() -> None:
    payload = copy.deepcopy(_VALID)
    del payload["nodes"][2]["probes"][0]["evidence"]
    client = FakeClient(json.dumps(payload, ensure_ascii=False), VALID)

    result = _generator(client).generate(DRAFT)

    assert result.attempts == 2
    assert "probe_evidence_missing" in client.calls[1].user


def test_an_option_without_weights_is_rejected() -> None:
    payload = copy.deepcopy(_VALID)
    del payload["nodes"][2]["probes"][0]["evidence"]["B"]
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "probe_evidence_option_missing: p1" in info.value.detail


def test_evidence_for_an_undeclared_target_is_rejected() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"][2]["probes"][0]["evidence"]["A"]["H_L4"] = 0.30
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "probe_evidence_target_unknown: p1" in info.value.detail


def test_a_target_without_any_weight_is_rejected() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"][2]["probes"][0]["evidence"] = {
        "A": {"H_L2": -0.40},
        "B": {"H_L2": 0.45},
        "C": {"H_L2": 0.20},
    }
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "probe_evidence_target_unused: p1" in info.value.detail


def test_seed_graph_conforms_to_the_published_spec() -> None:
    # The hand-written graph and generated ones share one contract; if this
    # fails, the spec or the serialiser drifted, not the model.
    assert validate_payload(to_payload(SAMPLE_PROBLEM.graph)) == ()


def test_payload_never_carries_the_answer_key() -> None:
    payload = to_payload(SAMPLE_PROBLEM.graph)
    serialised = json.dumps(payload, ensure_ascii=False)
    assert "correct_option" not in serialised


def test_plugin_uses_the_generated_evidence_not_the_seed_table() -> None:
    generator = _generator(FakeClient(VALID))
    plugin = MathPlugin({SAMPLE_PROBLEM.id: SAMPLE_PROBLEM}, generator=generator)

    graph = plugin.build_graph(DRAFT)
    model = plugin.evidence_model(graph)

    assert set(model.probe_ids) == {"p1", "p2"}
    assert model.for_probe("p1")["A"] == {"H_L2": -0.40, "H_L1": 0.20}
    assert model.for_probe("p2")["B"] == {"H_L4": 0.40, "H_L2": -0.15}


def test_a_generated_graph_without_evidence_gets_no_seed_weights() -> None:
    graph = SAMPLE_PROBLEM.graph
    stripped = SolutionGraph(
        problem_id="P_DERIV_999",
        version=graph.version,
        stem=graph.stem,
        nodes=graph.nodes,
        edges=graph.edges,
    )
    plugin = MathPlugin({SAMPLE_PROBLEM.id: SAMPLE_PROBLEM})

    assert plugin.evidence_model(stripped).weights == {}


def test_plugin_builds_a_draft_through_the_generator() -> None:
    generator = _generator(FakeClient(VALID))
    plugin = MathPlugin({SAMPLE_PROBLEM.id: SAMPLE_PROBLEM}, generator=generator)

    graph = plugin.build_graph(DRAFT)

    assert graph.problem_id == DRAFT.id
    assert len(graph.nodes) == 5


def test_plugin_without_a_generator_says_so() -> None:
    plugin = MathPlugin({SAMPLE_PROBLEM.id: SAMPLE_PROBLEM})

    with pytest.raises(GraphBuildFailed) as info:
        plugin.build_graph(DRAFT)

    assert info.value.reason == "disabled"
    assert "LLMGraphGenerator" in info.value.detail
