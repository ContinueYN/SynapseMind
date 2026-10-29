"""S5 ②: a submitted stem becomes a servable problem, or an explicit 422."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.application.errors import ProblemNotSupported
from synapse.application.graph import GraphBuildFailed, GraphBuildResult
from synapse.application.problem_resolver import ProblemResolver, generated_id
from synapse.application.subject import SubjectRegistry
from synapse.domain.problem.models import (
    Probe,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.in_memory import InMemoryProblemRepository
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.seed import SAMPLE_PROBLEM

UNSEEN = "已知函数 g(x)=x^2-a x+1，对任意 x∈R 有 g(x)>0，求 a 的取值范围。"


class _FakeGenerator:
    """Builds the same tiny graph every time; counts calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        self.calls.append(draft.id)
        graph = SolutionGraph(
            problem_id=draft.id,
            version="v1",
            stem=draft.text,
            nodes=(
                SolutionNode(id="n1", type="READ", text="确认条件：对所有 x∈R 成立。"),
                SolutionNode(
                    id="n2",
                    type="CONDITION",
                    text="按 a≤0 / a>0 分类讨论。",
                    probes=(
                        Probe(
                            id="p1",
                            question="a=0 这个边界要不要单独检查？",
                            options=("要，a=0 也在 a≤0 这一支里", "不要，a>0 已经覆盖"),
                            targets=("H_L2", "H_L1"),
                            evidence={"A": {"H_L2": 0.6, "H_L1": -0.3}, "B": {"H_L1": 0.6}},
                        ),
                    ),
                ),
                SolutionNode(
                    id="n3",
                    type="CHECK",
                    text="检验端点 a=±2 是否可取。",
                    probes=(
                        Probe(
                            id="p2",
                            question="检验端点时，代入 a=2 得到什么？",
                            options=("左边等于 0，端点不可取", "左边大于 0，端点可取"),
                            targets=("H_L2", "H_L4"),
                            evidence={"A": {"H_L2": 0.7, "H_L4": -0.4}, "B": {"H_L4": 0.7}},
                        ),
                    ),
                ),
            ),
            edges=(("n1", "n2"), ("n2", "n3")),
        )
        return GraphBuildResult(graph=graph, fingerprint="fake", attempts=1)


class _BrokenGenerator:
    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        del draft
        raise GraphBuildFailed("schema_invalid", detail="claim answer is empty")


def _resolver(generator: object | None) -> tuple[ProblemResolver, InMemoryProblemRepository]:
    problems = InMemoryProblemRepository()
    from synapse.infrastructure.subjects.math import MathPlugin

    problems.set_plugins(
        SubjectRegistry(
            (MathPlugin(problems.catalog, generator=generator),)  # type: ignore[arg-type]
        )
    )
    return ProblemResolver(problems, problems.plugins, store=problems), problems


def test_a_generated_id_is_stable_and_matches_the_draft_contract() -> None:
    assert generated_id(UNSEEN) == generated_id(f"  {UNSEEN}  ")
    assert generated_id(UNSEEN).startswith("P_GEN_")
    assert generated_id(UNSEEN) != generated_id(UNSEEN + "。")


def test_an_unseen_stem_is_generated_and_stored_unannotated() -> None:
    resolver, problems = _resolver(_FakeGenerator())

    problem = resolver.resolve(UNSEEN, None)

    assert problem.annotated is False
    assert problem.id.startswith("P_GEN_")
    assert problems.get(problem.id) is problem
    # The annotated set must not grow: the aligner and the card key off it.
    assert problem.id not in problems.annotated_ids
    assert SAMPLE_PROBLEM.id in problems.annotated_ids


def test_the_same_stem_is_generated_once() -> None:
    generator = _FakeGenerator()
    resolver, _ = _resolver(generator)

    first = resolver.resolve(UNSEEN, None)
    second = resolver.resolve(UNSEEN, None)

    assert first.id == second.id
    assert len(generator.calls) == 1


def test_the_annotated_seed_is_still_served_as_is() -> None:
    resolver, _ = _resolver(_FakeGenerator())

    problem = resolver.resolve(SAMPLE_PROBLEM.text, "math")

    assert problem is SAMPLE_PROBLEM
    assert problem.annotated is True


def test_a_declared_subject_that_does_not_match_is_refused() -> None:
    resolver, _ = _resolver(_FakeGenerator())

    with pytest.raises(ProblemNotSupported, match="no annotated problem"):
        resolver.resolve(SAMPLE_PROBLEM.text, "physics")


@pytest.mark.parametrize("generator", [None, _BrokenGenerator()])
def test_generation_is_refused_explicitly_when_it_cannot_run(generator: object | None) -> None:
    resolver, problems = _resolver(generator)

    with pytest.raises(ProblemNotSupported):
        resolver.resolve(UNSEEN, None)

    assert problems.annotated_ids == frozenset({SAMPLE_PROBLEM.id})


def test_an_empty_stem_is_refused() -> None:
    resolver, _ = _resolver(_FakeGenerator())

    with pytest.raises(ProblemNotSupported, match="为空"):
        resolver.resolve("   ", None)


# --- end to end: an unseen stem survives a full session --------------------

GRAPH_PAYLOAD = {
    "problem": {"text": UNSEEN},
    "attempt": {"answer": "a∈(-2,2)", "work": "题目要求对所有 x∈R 成立。"},
    "mode": "learning",
}


@pytest.fixture
def generated_client() -> TestClient:
    from synapse.api.main import create_app

    app = create_app(
        build_container(
            LLMSettings(mode="off", api_key="test"),
            generator=_FakeGenerator(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app)


def test_an_unseen_stem_now_reaches_align_and_probe(generated_client: TestClient) -> None:
    response = generated_client.post("/api/v1/sessions", json=copy.deepcopy(GRAPH_PAYLOAD))

    assert response.status_code == 201
    body = response.json()
    assert body["problem_text"] == UNSEEN
    assert body["problem_title"].startswith("已知函数 g(x)")
    assert body["problem_id"].startswith("P_GEN_")
    # ALIGN ran on the generated graph: the probe comes from n2, the only node
    # the student's work did not mention.
    assert body["prompt"]["question"] == "a=0 这个边界要不要单独检查？"


def test_a_generated_session_produces_a_card_naming_the_graph_node(
    generated_client: TestClient,
) -> None:
    created = generated_client.post("/api/v1/sessions", json=copy.deepcopy(GRAPH_PAYLOAD))
    session_id = created.json()["session_id"]

    first = generated_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "要，a=0 也在 a≤0 这一支里", "option_id": "A"},
    )
    assert first.status_code == 200
    assert first.json()["prompt"]["question"] == "检验端点时，代入 a=2 得到什么？"

    response = generated_client.post(
        f"/api/v1/sessions/{session_id}/turns",
        json={"answer": "左边等于 0，端点不可取", "option_id": "A"},
    )

    assert response.status_code == 200
    diagnosis = response.json()["diagnosis"]
    assert diagnosis is not None
    card = diagnosis["card"]
    assert card["node_id"] in {"n2", "n3"}
    assert "条件转译" in card["label"] or "概念不清" in card["label"]
    assert card["next_action"]["concept_id"].startswith("node:")
    assert diagnosis["problem_id"] != SAMPLE_PROBLEM.id


def test_the_answer_is_never_in_a_generated_response(generated_client: TestClient) -> None:
    """No stored answer means the leak guard is degraded — still no leak."""

    created = generated_client.post("/api/v1/sessions", json=copy.deepcopy(GRAPH_PAYLOAD))
    body = created.json()

    assert "a∈(-2,2)" not in str(body.get("prompt"))
    assert "answer" not in str(body.get("prompt"))
