"""Phase 1b: a generated generic graph, its limits and its verifier wiring.

The graph here is system-generated, so the tests police two things at once:

* the structure contract (nodes, goal, two options for a decision, no
  recommendation, the public JSON schema);
* the honesty boundary — a formal claim is only read from an answer the student
  already wrote, an empirical claim only from structured input, and a failed
  build degrades to the Phase 0 intake instead of inventing a graph.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from synapse.application.audit import AuditEntry
from synapse.application.domains import IntakeFramework, VerificationMode
from synapse.application.generic_graph import (
    GenericGraphBuildFailed,
    GenericGraphDraft,
)
from synapse.application.llm import LLMRequest, LLMResponse
from synapse.domain.problem.generic import (
    ClaimCheck,
    EmpiricalClaim,
    GenericGraph,
    GenericNode,
    NodeKind,
)
from synapse.domain.problem.models import Problem
from synapse.infrastructure.llm.audit import InMemoryCallAuditor
from synapse.infrastructure.llm.generic_graph import (
    LLMGenericGraphGenerator,
    build_request,
)
from synapse.infrastructure.llm.replay import ReplayLLMClient, request_key
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.snapshots import decode_problem, encode_problem

ON = LLMSettings(mode="on", api_key="test", max_attempts=2)
OFF = LLMSettings(mode="off", api_key="test")


def _draft(
    *,
    answer: str = "我觉得应该去北京，因为机会更多。",
    structured: dict[str, object] | None = None,
    framework: IntakeFramework = IntakeFramework.DECISION,
    verification: VerificationMode = VerificationMode.ARGUMENTATIVE,
) -> GenericGraphDraft:
    return GenericGraphDraft(
        id="P_GEN_GENERIC_001",
        text="我应该接受北京的工作，还是留在上海陪家人？",
        label="决策",
        verification=verification,
        framework=framework,
        answer=answer,
        work="",
        structured=structured,
    )


def _json(nodes: list[dict[str, Any]], **extra: Any) -> str:
    return json.dumps({"nodes": nodes, **extra}, ensure_ascii=False)


DECISION_NODES: list[dict[str, Any]] = [
    {"id": "g1", "kind": "goal", "text": "决定下一份工作在哪里"},
    {"id": "g2", "kind": "constraint", "text": "不想长期两地分居"},
    {"id": "g3", "kind": "decision", "text": "接受北京的工作"},
    {"id": "g4", "kind": "decision", "text": "留在上海陪家人"},
    {"id": "g5", "kind": "risk", "text": "换城市后收入可能下降"},
]


class _Client:
    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        self.requests.append(request)
        if not self._texts:
            raise AssertionError("unexpected extra model call")
        return LLMResponse(text=self._texts.pop(0), model="stub-1", latency_ms=3)


class _FormalStub:
    def __init__(self, check: ClaimCheck) -> None:
        self.check = check
        self.claims: list[Any] = []

    def verify(self, claim: Any) -> ClaimCheck:
        self.claims.append(claim)
        return self.check


class _EmpiricalStub:
    def __init__(self, check: ClaimCheck) -> None:
        self.check = check
        self.claims: list[Any] = []

    def verify(self, claim: Any) -> ClaimCheck:
        self.claims.append(claim)
        return self.check


class TestBuild:
    def test_a_decision_graph_is_system_owned_and_has_no_claim(self) -> None:
        generator = LLMGenericGraphGenerator(
            _Client(_json(DECISION_NODES)),
            settings=ON,
        )

        result = generator.generate(_draft())

        assert result.graph.version == "g2"
        assert all(node.source == "system" for node in result.graph.nodes)
        assert result.graph.formal is None
        assert result.graph.empirical is None
        assert result.checks == ()
        assert result.attempts == 1
        assert result.cached is False
        # A decision graph is structure only; it never recommends an option.
        assert result.graph.of_kind(NodeKind.DECISION)[0].text == "接受北京的工作"

    def test_a_decision_with_one_option_is_degenerate(self) -> None:
        nodes = DECISION_NODES[:2] + [
            {"id": "g3", "kind": "decision", "text": "接受北京的工作"},
        ]
        generator = LLMGenericGraphGenerator(_Client(_json(nodes), _json(nodes)), settings=ON)

        with pytest.raises(GenericGraphBuildFailed) as caught:
            generator.generate(_draft())

        assert caught.value.reason == "degenerate"
        assert "decision_options_too_few" in caught.value.detail
        assert caught.value.attempts == 2

    def test_a_recommendation_is_rejected_not_rendered(self) -> None:
        nodes = DECISION_NODES + [
            {"id": "g6", "kind": "next", "text": "建议选北京，因为机会更多"},
        ]
        generator = LLMGenericGraphGenerator(_Client(_json(nodes), _json(nodes)), settings=ON)

        with pytest.raises(GenericGraphBuildFailed) as caught:
            generator.generate(_draft())

        assert caught.value.reason == "degenerate"
        assert "recommendation_in_node" in caught.value.detail

    def test_bad_json_is_retried_once_then_fails(self) -> None:
        client = _Client("not json", "still not json")
        generator = LLMGenericGraphGenerator(client, settings=ON)

        with pytest.raises(GenericGraphBuildFailed) as caught:
            generator.generate(_draft())

        assert caught.value.reason == "bad_json"
        assert len(client.requests) == 2
        # The retry carries concrete errors, not the previous output.
        assert "bad_json" in client.requests[1].user

    def test_a_schema_error_can_be_fixed_on_the_retry(self) -> None:
        bad = [dict(node) for node in DECISION_NODES]
        bad[0]["kind"] = "wish"
        client = _Client(_json(bad), _json(DECISION_NODES))
        generator = LLMGenericGraphGenerator(client, settings=ON)

        result = generator.generate(_draft())

        assert result.attempts == 2
        assert len(result.graph.nodes) == 5

    def test_probes_are_outside_the_generic_contract(self) -> None:
        payload = _json(DECISION_NODES, probes=[{"question": "先做哪一步？"}])
        generator = LLMGenericGraphGenerator(_Client(payload, payload), settings=ON)

        with pytest.raises(GenericGraphBuildFailed) as caught:
            generator.generate(_draft())

        assert caught.value.reason == "schema_invalid"
        assert "probes_unsupported" in caught.value.detail

    def test_disabled_mode_refuses_without_calling_the_model(self) -> None:
        client = _Client(_json(DECISION_NODES))
        generator = LLMGenericGraphGenerator(client, settings=OFF)

        with pytest.raises(GenericGraphBuildFailed) as caught:
            generator.generate(_draft())

        assert caught.value.reason == "disabled"
        assert client.requests == []

    def test_the_same_draft_is_served_from_the_process_cache(self) -> None:
        client = _Client(_json(DECISION_NODES))
        generator = LLMGenericGraphGenerator(client, settings=ON)

        first = generator.generate(_draft())
        second = generator.generate(_draft())

        assert second.cached is True
        assert second.graph == first.graph
        assert len(client.requests) == 1

    def test_a_recorded_reply_plays_back_through_the_real_generator(self) -> None:
        draft = _draft()
        payload = _json(DECISION_NODES)
        client = ReplayLLMClient({request_key(build_request(draft)): payload})
        generator = LLMGenericGraphGenerator(client, settings=ON)

        result = generator.generate(draft)

        assert result.graph.problem_id == draft.id
        assert len(result.graph.nodes) == 5


class TestClaims:
    FORMAL_DRAFT = _draft(
        answer="a∈[1,+∞)",
        framework=IntakeFramework.FORMAL,
        verification=VerificationMode.FORMAL,
    )
    FORMAL_JSON = _json(
        [
            {"id": "g1", "kind": "goal", "text": "求参数 a 的取值范围"},
            {"id": "g2", "kind": "given", "text": "对任意 x>0 有 f(x)≤0"},
            {"id": "g3", "kind": "constraint", "text": "x 的定义域是 x>0"},
            {"id": "g4", "kind": "check", "text": "检查端点是否包含"},
        ],
        formal={
            "kind": "parameter_range",
            "parameter": "a",
            "variable": "x",
            "variable_domain": "(0,+inf)",
            "constraint": {"expression": "log(x) - a*x", "relation": "<="},
            "answer": [
                {
                    "lower": "1/E",
                    "upper": None,
                    "lower_inclusive": True,
                    "upper_inclusive": False,
                }
            ],
        },
    )

    def test_a_formal_claim_formalises_the_students_own_answer(self) -> None:
        stub = _FormalStub(ClaimCheck(kind="formal", status="fail", detail="反例：a=1 时 x=2"))
        generator = LLMGenericGraphGenerator(_Client(self.FORMAL_JSON), settings=ON, formal=stub)

        result = generator.generate(self.FORMAL_DRAFT)

        assert result.graph.formal is not None
        assert result.graph.formal.parameter == "a"
        assert stub.claims and stub.claims[0].parameter == "a"
        # A refuted student answer is diagnostic evidence, not a build failure.
        assert result.checks[0].status == "fail"

    def test_a_formal_claim_without_a_student_answer_is_dropped(self) -> None:
        draft = replace(self.FORMAL_DRAFT, answer="")
        stub = _FormalStub(ClaimCheck(kind="formal", status="pass"))
        generator = LLMGenericGraphGenerator(_Client(self.FORMAL_JSON), settings=ON, formal=stub)

        result = generator.generate(draft)

        assert result.graph.formal is None
        assert "formal_dropped_unsupported" in result.repairs
        assert stub.claims == []
        assert result.checks[0].status == "unknown"

    def test_an_unsure_answer_is_not_formalised(self) -> None:
        draft = replace(self.FORMAL_DRAFT, answer="暂时不确定")
        stub = _FormalStub(ClaimCheck(kind="formal", status="pass"))
        generator = LLMGenericGraphGenerator(_Client(self.FORMAL_JSON), settings=ON, formal=stub)

        result = generator.generate(draft)

        assert result.graph.formal is None
        assert "formal_dropped_unsupported" in result.repairs
        assert stub.claims == []

    def test_empirical_without_structured_input_is_dropped(self) -> None:
        draft = _draft(
            answer="",
            framework=IntakeFramework.EMPIRICAL,
            verification=VerificationMode.EMPIRICAL,
        )
        payload = _json(
            DECISION_NODES,
            empirical={
                "equation": "v = d/t",
                "units": {"v": "m/s", "d": "m", "t": "s"},
            },
        )
        stub = _EmpiricalStub(ClaimCheck(kind="empirical", status="pass"))
        generator = LLMGenericGraphGenerator(
            _Client(payload),
            settings=ON,
            empirical=stub,
        )

        result = generator.generate(draft)

        assert result.graph.empirical is None
        assert "empirical_dropped_unsupported" in result.repairs
        assert result.checks[0].status == "unknown"

    def test_empirical_runs_when_the_caller_supplies_structured_input(self) -> None:
        draft = _draft(
            answer="",
            framework=IntakeFramework.EMPIRICAL,
            verification=VerificationMode.EMPIRICAL,
            structured={"equation": "v = d/t"},
        )
        payload = _json(
            DECISION_NODES,
            empirical={
                "equation": "v = d/t",
                "units": {"v": "m/s", "d": "m", "t": "s"},
            },
        )
        stub = _EmpiricalStub(ClaimCheck(kind="empirical", status="pass", detail="量纲一致"))
        generator = LLMGenericGraphGenerator(
            _Client(payload),
            settings=ON,
            empirical=stub,
        )

        result = generator.generate(draft)

        assert isinstance(result.graph.empirical, EmpiricalClaim)
        assert stub.claims and stub.claims[0].equation == "v = d/t"
        assert result.checks[0].status == "pass"


class TestAudit:
    def test_a_generic_build_is_audited_without_student_text(self) -> None:
        auditor = InMemoryCallAuditor()
        generator = LLMGenericGraphGenerator(
            _Client(_json(DECISION_NODES)),
            settings=ON,
            auditor=auditor,
        )

        generator.generate(_draft())

        entries: list[AuditEntry] = auditor.entries
        assert [entry.kind for entry in entries] == ["generic_graph_build"]
        assert entries[0].schema_ok is True
        assert entries[0].prompt_version == ON.generic_graph_prompt_version
        serialised = json.dumps(entries[0].as_dict(), ensure_ascii=False)
        assert "北京" not in serialised


class TestPersistence:
    def test_a_problem_snapshot_round_trips_the_generic_graph_and_checks(self) -> None:
        generic = GenericGraph(
            problem_id=SAMPLE_PROBLEM.id,
            version="g2",
            nodes=(
                GenericNode(id="g1", kind=NodeKind.GOAL, text="目标", source="system"),
                GenericNode(id="g2", kind=NodeKind.RISK, text="风险", source="system"),
            ),
            formal=None,
            empirical=None,
        )
        problem = replace(
            SAMPLE_PROBLEM,
            generic=generic,
            generic_checks=(ClaimCheck(kind="formal", status="unknown", detail="没有声明"),),
        )

        assert decode_problem(encode_problem(problem)) == problem

    def test_old_problem_rows_still_decode_without_a_generic_graph(self) -> None:
        snapshot = encode_problem(SAMPLE_PROBLEM)
        data = snapshot["data"]
        assert isinstance(data, dict)
        data.pop("generic")
        data.pop("generic_checks")

        decoded: Problem = decode_problem(snapshot)

        assert decoded.generic is None
        assert decoded.generic_checks == ()
