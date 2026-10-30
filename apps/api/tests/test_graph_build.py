"""M2.5 S4: generated graphs must pass repair, structure rules and the spec."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from synapse.application.graph import GraphBuildFailed
from synapse.application.llm import LLMRequest, LLMResponse, LLMTimeout
from synapse.domain.problem.graph_structure import fingerprint
from synapse.domain.problem.models import Interval, ProblemDraft, SolutionGraph
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

RANGE_DRAFT = ProblemDraft(
    id="P_DERIV_003",
    text="已知函数 f(x)=e^x-a x，a∈R。若 f(x)≥0 对任意 x∈R 恒成立，求 a 的取值范围。",
)


def _range_payload(answer: dict[str, Any], *, expression: str = "exp(x) - a*x") -> dict[str, Any]:
    payload = copy.deepcopy(_VALID)
    payload["claim"] = {
        "kind": "parameter_range",
        "parameter": "a",
        "variable": "x",
        "variable_domain": "(-inf,+inf)",
        "constraint": {"expression": expression, "relation": ">="},
        "answer": [answer],
    }
    return payload


def _range_json(*, lower_inclusive: bool, expression: str = "exp(x) - a*x") -> str:
    return json.dumps(
        _range_payload(
            {
                "lower": "0",
                "upper": "E",
                "lower_inclusive": lower_inclusive,
                "upper_inclusive": True,
            },
            expression=expression,
        ),
        ensure_ascii=False,
    )


def _answer_json(*, lower_inclusive: bool) -> str:
    """The answer-only reply the claim repair asks for (no graph, no claim block)."""
    return json.dumps(
        {
            "answer": [
                {
                    "lower": "0",
                    "upper": "E",
                    "lower_inclusive": lower_inclusive,
                    "upper_inclusive": True,
                }
            ]
        },
        ensure_ascii=False,
    )


class FakeClient:
    def __init__(self, *replies: str | Exception, latency_ms: int = 42) -> None:
        self.replies = list(replies)
        self.calls: list[LLMRequest] = []
        self.timeouts: list[float] = []
        self.latency_ms = latency_ms

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        self.timeouts.append(timeout_s)
        self.calls.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(
            text=reply,
            model="fake-1",
            latency_ms=self.latency_ms,
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
    assert result.repairs == ("evidence_calibrated",)
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
    assert entry.prompt_version == "graph-v9"
    assert entry.graph_fingerprint == result.fingerprint
    # No claim in the reply: the build is fine, the answer is just unverified.
    assert entry.verification_status == "unknown"
    assert result.verification is not None
    assert result.verification.status == "unknown"


def test_bad_json_is_retried_with_feedback() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient("这不是 JSON", VALID)

    result = _generator(client, auditor).generate(DRAFT)

    assert result.attempts == 2
    assert len(client.calls) == 2
    assert "未通过校验" in client.calls[1].user
    # The retry is the second half of the budget: it must ask for the smallest
    # graph that still passes the rules, not a richer one.
    assert "最小可用图" in client.calls[1].user
    assert "最小可用图" not in client.calls[0].user
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
    # The model wrote |w|≤0.45, so graph-wide calibration doubles every weight:
    # signs and ratios are preserved, the strongest one reaches 0.90.
    assert probe["evidence"] == {
        "A": {"H_L2": -0.8, "H_L1": 0.4},
        "B": {"H_L2": 0.9, "H_L1": -0.2},
        "C": {"H_L1": 0.6},
    }
    second = payload["nodes"][3]["probes"][0]
    assert second["evidence"]["B"] == {"H_L4": 0.8, "H_L2": -0.3}


def test_prompt_asks_for_full_scale_evidence() -> None:
    client = FakeClient(VALID)

    _generator(client).generate(DRAFT)

    assert "±0.8~1.0" in client.calls[0].system


PHYSICS_DRAFT = ProblemDraft(
    id="P_PHYS_001",
    text="质量为 2 kg 的物块在水平面上受 10 N 拉力，动摩擦因数 0.2，求加速度。",
    subject="physics",
)


def test_physics_uses_its_own_prompt_and_audit_version() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(VALID)

    result = _generator(client, auditor).generate(PHYSICS_DRAFT)

    assert "高中物理解法图" in client.calls[0].system
    assert "不要输出 claim" in client.calls[0].system
    assert "恒成立" not in client.calls[0].system
    assert result.graph.claim is None
    (entry,) = auditor.entries
    assert entry.prompt_version == "graph-v9-physics"


def test_physics_claim_is_dropped_instead_of_certified() -> None:
    payload = copy.deepcopy(_VALID)
    payload["claim"] = {"kind": "parameter_range"}
    result = _generator(FakeClient(json.dumps(payload, ensure_ascii=False))).generate(PHYSICS_DRAFT)

    assert result.graph.claim is None
    assert "claim_dropped_unsupported" in result.repairs
    assert result.verification is not None
    assert result.verification.status == "unknown"


CHINESE_DRAFT = ProblemDraft(
    id="P_CN_001",
    text="文中两次写到“灯”，请结合全文简要分析其作用。",
    subject="chinese",
)

_CHINESE: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "READ", "text": "读题干，圈出限制语与分值", "demand": {"V": 0.2}},
        {
            "id": "n2",
            "type": "CONDITION",
            "text": "定位原文区间，勾出依据句",
            "demand": {"WM": 0.4},
        },
        {"id": "n3", "type": "COMPUTE", "text": "分点组织答案，写完整句子", "demand": {"Gf": 0.5}},
        {"id": "n4", "type": "CHECK", "text": "检查扣题与分值对应", "demand": {"M": 0.3}},
    ],
    "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
}


def test_chinese_uses_its_own_prompt_and_needs_no_probes() -> None:
    """S7: a NONE-tier graph is steps only, so ``no_probes`` must not fail it."""

    auditor = InMemoryCallAuditor()
    client = FakeClient(json.dumps(_CHINESE, ensure_ascii=False))

    result = _generator(client, auditor).generate(CHINESE_DRAFT)

    assert "高中语文" in client.calls[0].system
    assert "不要输出探针" in client.calls[0].system
    assert "不要输出 claim" in client.calls[0].system
    assert result.graph.probes() == ()
    assert result.graph.claim is None
    assert "no_probes" not in result.repairs
    assert result.repairs == ()
    (entry,) = auditor.entries
    assert entry.schema_ok is True
    assert entry.prompt_version == "graph-v6-chinese"
    assert entry.verification_status == "unknown"


def test_chinese_drops_probes_a_model_still_writes() -> None:
    payload = copy.deepcopy(_CHINESE)
    payload["nodes"][1]["probes"] = [
        {
            "id": "p1",
            "question": "先定位原文还是先概括？",
            "options": ["先定位", "先概括"],
            "targets": ["H_L2", "H_L1"],
            "evidence": {"A": {"H_L2": 0.9, "H_L1": -0.4}, "B": {"H_L1": 0.9, "H_L2": -0.4}},
        }
    ]
    payload["claim"] = {"kind": "parameter_range"}

    result = _generator(FakeClient(json.dumps(payload, ensure_ascii=False))).generate(CHINESE_DRAFT)

    assert result.graph.probes() == ()
    assert result.graph.claim is None
    assert "probes_dropped_unsupported" in result.repairs
    assert "claim_dropped_unsupported" in result.repairs


def test_full_scale_evidence_is_left_alone() -> None:
    payload = copy.deepcopy(_VALID)
    payload["nodes"][2]["probes"][0]["evidence"]["B"]["H_L2"] = 0.95
    result = _generator(FakeClient(json.dumps(payload, ensure_ascii=False))).generate(DRAFT)

    assert "evidence_calibrated" not in result.repairs
    assert result.graph.probes()[0].evidence["B"]["H_L2"] == 0.95


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
    assert model.for_probe("p1")["A"] == {"H_L2": -0.8, "H_L1": 0.4}
    assert model.for_probe("p2")["B"] == {"H_L4": 0.8, "H_L2": -0.3}


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


def test_a_wrong_answer_range_is_repaired_without_regenerating_the_graph() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(_range_json(lower_inclusive=False), _answer_json(lower_inclusive=True))

    result = _generator(client, auditor).generate(RANGE_DRAFT)

    assert result.attempts == 2
    assert len(client.calls) == 2
    # The repair must not regenerate the graph: a full graph completion is what
    # used to push the tail past 7.5s (ADR-0004 §5.4).
    assert client.calls[1].purpose == "graph_claim_repair"
    assert "nodes" not in client.calls[1].system
    assert client.calls[1].max_tokens is not None
    assert client.calls[1].max_tokens < GRAPH_MAX_TOKENS
    # The counterexample itself goes back to the model: a=0 works but is
    # excluded by the first answer.
    assert "verification_counterexample" in client.calls[1].user
    assert "a=0" in client.calls[1].user
    assert result.verification is not None
    assert result.verification.status == "pass"
    assert result.graph.claim is not None
    assert result.graph.claim.expression == "exp(x) - a*x"
    assert result.graph.claim.intervals == (
        Interval(lower="0", upper="E", lower_inclusive=True, upper_inclusive=True),
    )
    assert "claim_repaired" in result.repairs
    first, second = auditor.entries
    assert first.fallback_reason == "counterexample"
    assert first.verification_status == "fail"
    assert second.verification_status == "pass"
    assert second.retried is True


def test_the_repair_cannot_change_the_formalised_constraint() -> None:
    # A model that ignores "answer only" and rewrites the whole claim must not
    # dodge the counterexample by silently changing f(x) to fit its answer.
    full = _range_payload(
        {
            "lower": "0",
            "upper": "E",
            "lower_inclusive": True,
            "upper_inclusive": True,
        },
        expression="exp(x) - b*x",
    )
    client = FakeClient(_range_json(lower_inclusive=False), json.dumps(full, ensure_ascii=False))

    result = _generator(client).generate(RANGE_DRAFT)

    assert result.graph.claim is not None
    assert result.graph.claim.expression == "exp(x) - a*x"
    assert result.graph.claim.parameter == "a"


def test_an_answer_range_that_keeps_failing_loses_its_claim_but_not_the_graph() -> None:
    client = FakeClient(_range_json(lower_inclusive=False), _answer_json(lower_inclusive=False))

    result = _generator(client).generate(RANGE_DRAFT)

    assert result.attempts == 2
    assert len(client.calls) == 2
    # The graph's probes are what the dialogue uses; the refuted answer is the
    # part that must not be treated as checked.
    assert result.graph.claim is None
    assert "claim_dropped_refuted" in result.repairs
    assert "claim_repair_refuted" in result.repairs
    assert result.verification is not None
    assert result.verification.status == "fail"
    assert result.verification.counterexample is not None
    assert "no_claim" in result.notes
    assert "claim" not in to_payload(result.graph)


def test_a_repair_that_declines_the_range_drops_the_claim() -> None:
    client = FakeClient(_range_json(lower_inclusive=False), json.dumps({"answer": None}))

    result = _generator(client).generate(RANGE_DRAFT)

    assert result.graph.claim is None
    assert "claim_dropped_refuted" in result.repairs
    assert "claim_repair_declined" in result.repairs


def test_a_repair_timeout_drops_the_claim_instead_of_the_build() -> None:
    auditor = InMemoryCallAuditor()
    client = FakeClient(_range_json(lower_inclusive=False), LLMTimeout("slow"))

    result = _generator(client, auditor).generate(RANGE_DRAFT)

    assert result.graph.claim is None
    assert "claim_retry_timeout" in result.repairs
    assert result.attempts == 2
    last = auditor.entries[-1]
    assert last.fallback_reason == "timeout"
    assert last.retried is True


def test_a_malformed_repair_is_discarded_without_a_third_call() -> None:
    client = FakeClient(_range_json(lower_inclusive=False), "这不是 JSON")

    result = _generator(client).generate(RANGE_DRAFT)

    assert len(client.calls) == 2
    assert result.graph.claim is None
    assert "claim_dropped_refuted" in result.repairs
    assert "claim_retry_malformed" in result.repairs


def test_only_one_claim_repair_is_attempted() -> None:
    client = FakeClient(
        _range_json(lower_inclusive=False),
        _answer_json(lower_inclusive=False),
        _answer_json(lower_inclusive=True),
    )

    result = _generator(client, max_attempts=3).generate(RANGE_DRAFT)

    # A repair that fails is not retried again: the answer is optional metadata,
    # and a third call would exist only to chase it.
    assert len(client.calls) == 2
    assert result.graph.claim is None


def test_the_repair_is_bounded_by_the_remaining_first_question_budget() -> None:
    client = FakeClient(_range_json(lower_inclusive=False), _answer_json(lower_inclusive=True))

    _generator(client, graph_retry_budget_s=2.0).generate(RANGE_DRAFT)

    # The repair may only use what is left of the 8s budget, so it cannot turn a
    # slow first attempt into a timeout far past the SLO.
    assert 1.0 <= client.timeouts[1] <= 2.0


def test_a_slow_refutation_skips_the_repair_instead_of_blowing_the_budget() -> None:
    wrong = _range_json(lower_inclusive=False)
    client = FakeClient(wrong, wrong, latency_ms=4000)

    result = _generator(client, graph_retry_budget_s=1.0).generate(RANGE_DRAFT)

    # A repair that cannot finish inside the budget is not started: the graph is
    # served, the refuted answer is dropped, the skip is recorded.
    assert len(client.calls) == 1
    assert result.graph.claim is None
    assert "claim_dropped_refuted" in result.repairs
    assert "retry_skipped_budget" in result.repairs


def test_a_malformed_claim_is_rewritten_with_a_syntax_hint() -> None:
    client = FakeClient(
        _range_json(lower_inclusive=True, expression="exp(x) - b*x"),
        _range_json(lower_inclusive=True),
    )

    result = _generator(client).generate(RANGE_DRAFT)

    assert result.attempts == 2
    assert client.calls[1].purpose == "graph_claim_repair"
    assert "verification_malformed" in client.calls[1].user
    assert result.graph.claim is not None
    assert result.graph.claim.expression == "exp(x) - a*x"


def test_the_claim_is_serialised_and_conforms_to_the_spec() -> None:
    result = _generator(FakeClient(_range_json(lower_inclusive=True))).generate(RANGE_DRAFT)

    payload = to_payload(result.graph)

    assert payload["claim"] == {
        "kind": "parameter_range",
        "parameter": "a",
        "variable": "x",
        "variable_domain": "(-inf,+inf)",
        "constraint": {"expression": "exp(x) - a*x", "relation": ">="},
        "answer": [
            {
                "lower": "0",
                "upper": "E",
                "lower_inclusive": True,
                "upper_inclusive": True,
            }
        ],
    }
    assert validate_payload(payload) == ()


def test_a_top_level_probe_list_is_rejected_with_a_placement_hint() -> None:
    # graph-v3 regression: the model flattened probes out of the nodes, so no
    # probe had an owner. The retry must say which field is wrong.
    flattened = copy.deepcopy(_VALID)
    probes = [probe for node in flattened["nodes"] for probe in node.pop("probes", [])]
    flattened["probes"] = probes

    client = FakeClient(json.dumps(flattened, ensure_ascii=False), VALID)

    result = _generator(client).generate(DRAFT)

    assert result.attempts == 2
    assert "probes_top_level" in client.calls[1].user
    assert len(result.graph.probes()) == 2


def test_a_claim_that_is_not_an_object_is_rejected() -> None:
    payload = copy.deepcopy(_VALID)
    payload["claim"] = "a∈[0,e]"

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(json.dumps(payload), json.dumps(payload))).generate(RANGE_DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "claim" in info.value.detail


def test_an_interval_without_endpoints_is_rejected() -> None:
    payload = _range_payload({"lower": "0", "lower_inclusive": True})
    bad = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(GraphBuildFailed) as info:
        _generator(FakeClient(bad, bad)).generate(RANGE_DRAFT)

    assert info.value.reason == "schema_invalid"
    assert "claim.answer[0].upper" in info.value.detail
