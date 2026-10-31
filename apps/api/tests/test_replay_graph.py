"""A recorded graph reply runs the real generator without a network or key."""

from __future__ import annotations

from pathlib import Path

from synapse.domain.problem.models import ProblemDraft
from synapse.infrastructure.llm.graph import LLMGraphGenerator, build_request
from synapse.infrastructure.llm.replay import ReplayLLMClient, request_key
from synapse.infrastructure.llm.settings import LLMSettings

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "math_graph.json"
CHINESE_FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "chinese_graph.json"
DRAFT = ProblemDraft(
    id="P_REPLAY_001",
    text="已知函数 f(x)=x^3-3x^2+2，求 f(x) 的单调区间与极值。",
    subject="math",
)
CHINESE_DRAFT = ProblemDraft(
    id="P_REPLAY_CN",
    text="阅读下面的文字，完成题目：文中两次写到“灯”，请结合全文简要分析其作用。",
    subject="chinese",
)


def test_a_recorded_graph_reply_is_replayed_deterministically() -> None:
    client = ReplayLLMClient(
        {request_key(build_request(DRAFT)): FIXTURE.read_text(encoding="utf-8")}
    )
    generator = LLMGraphGenerator(
        client,
        settings=LLMSettings(mode="on", api_key="replay"),
    )

    result = generator.generate(DRAFT)

    assert result.graph.problem_id == DRAFT.id
    assert len(result.graph.probes()) == 2
    assert result.graph.claim is None
    assert result.attempts == 1
    assert result.cached is False


def test_the_same_recorded_reply_is_served_from_the_process_cache() -> None:
    client = ReplayLLMClient(
        {request_key(build_request(DRAFT)): FIXTURE.read_text(encoding="utf-8")}
    )
    generator = LLMGraphGenerator(
        client,
        settings=LLMSettings(mode="on", api_key="replay"),
    )

    first = generator.generate(DRAFT)
    second = generator.generate(DRAFT)

    assert second.cached is True
    assert second.fingerprint == first.fingerprint


def test_a_recorded_chinese_graph_needs_no_probes_or_claim() -> None:
    client = ReplayLLMClient(
        {request_key(build_request(CHINESE_DRAFT)): CHINESE_FIXTURE.read_text(encoding="utf-8")}
    )
    generator = LLMGraphGenerator(
        client,
        settings=LLMSettings(mode="on", api_key="replay"),
    )

    result = generator.generate(CHINESE_DRAFT)

    assert result.graph.problem_id == CHINESE_DRAFT.id
    assert result.graph.probes() == ()
    assert result.graph.claim is None
    assert len(result.graph.nodes) == 4
