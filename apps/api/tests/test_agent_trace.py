"""Phase 4: a bounded tool trace, never a second diagnosis.

The trace is allowed to be useful without being magical: it runs at most three
read-only tools, does not advance the session, does not read the answer store,
and says "not executed" rather than inventing a run. These tests pin the
boundaries that make that claim true.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.execution import (
    ExecutionResult,
    RunCodeCommand,
)
from synapse.application.knowledge import KnowledgeService, KnowledgeUnavailable
from synapse.domain.knowledge.models import (
    KnowledgeCard,
    KnowledgeHit,
    KnowledgeSource,
)
from synapse.infrastructure.features import FeatureFlags

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "agent-trace.schema.json"
CODE = "我的 Python 脚本报错了：IndexError: list index out of range，列表里明明有元素，应该怎么修？"
DECISION = "我应该接受北京的工作机会，还是留在上海陪家人？"
MATH = "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"


def _start(client: TestClient, text: str, answer: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": text},
            "attempt": {"answer": answer, "work": "", "self_report": "unsure"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _client(
    *,
    knowledge: KnowledgeService | None = None,
    executor: object | None = None,
    execution: bool = False,
) -> TestClient:
    return TestClient(
        create_app(
            build_container(
                features=FeatureFlags(execution=execution),
                knowledge=knowledge,
                executor=executor,  # type: ignore[arg-type]
            )
        )
    )


class _Retriever:
    def __init__(self, hits: tuple[KnowledgeHit, ...]) -> None:
        self._hits = hits
        self.queries: list[str] = []

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        verification: str | None = None,
        limit: int = 3,
    ) -> tuple[KnowledgeHit, ...]:
        self.queries.append(query)
        return self._hits


class _BrokenRetriever:
    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        verification: str | None = None,
        limit: int = 3,
    ) -> tuple[KnowledgeHit, ...]:
        raise KnowledgeUnavailable("model missing")


class _Executor:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.commands: list[RunCodeCommand] = []

    def run(self, command: RunCodeCommand) -> ExecutionResult:
        self.commands.append(command)
        return self.result


def _card() -> KnowledgeHit:
    return KnowledgeHit(
        card=KnowledgeCard(
            id="K_CODE_TEST_FIRST",
            kind="method",
            subject="programming",
            verifications=("executable",),
            title="先写一个最小可复现测试",
            body="把失败输入缩成一个最小例子，再写断言。",
            tags=("测试", "最小复现"),
            source=KnowledgeSource(
                title="Python 文档：unittest",
                url="https://docs.python.org/3/library/unittest.html",
                license="PSF-2.0",
            ),
        ),
        score=0.91,
    )


def test_trace_is_read_only_bounded_and_schema_valid(client: TestClient) -> None:
    created = _start(client, CODE, "我想让它跑起来。")
    session_id = created["session_id"]
    before = client.get(f"/api/v1/sessions/{session_id}").json()

    response = client.get(f"/api/v1/sessions/{session_id}/agent")

    assert response.status_code == 200, response.text
    body = response.json()
    Draft202012Validator(json.loads(SPEC_PATH.read_text(encoding="utf-8"))).validate(body)
    assert body["version"] == "0.1"
    assert body["mode"] == "rules"
    assert body["steps"][0]["tool"] == "check_structure"
    assert len(body["steps"]) <= 3
    assert body["limits"] == {"max_steps": 3, "steps_used": len(body["steps"])}
    assert "答案" in body["notice"]

    after = client.get(f"/api/v1/sessions/{session_id}").json()
    assert after["state"] == before["state"]
    assert after["turn"] == before["turn"]
    assert after["intake"]["observed"] == before["intake"]["observed"]
    assert after["intake"]["gaps"] == before["intake"]["gaps"]


def test_trace_never_repeats_the_attempt(client: TestClient) -> None:
    secret = "SECRET_ATTEMPT_TOKEN"
    created = _start(client, CODE, f"{secret} 我想让它跑起来。")
    session_id = created["session_id"]

    response = client.get(f"/api/v1/sessions/{session_id}/agent")

    assert response.status_code == 200, response.text
    assert secret not in response.text


def test_decision_trace_lists_tradeoffs_without_ranking(client: TestClient) -> None:
    created = _start(
        client,
        DECISION,
        "我想两年内转做后端；要么留公司转岗，要么跳槽去小厂；但我怕收入下降。",
    )

    response = client.get(f"/api/v1/sessions/{created['session_id']}/agent")

    assert response.status_code == 200, response.text
    body = response.json()
    tools = [step["tool"] for step in body["steps"]]
    assert "compare_options" in tools
    compare = next(step for step in body["steps"] if step["tool"] == "compare_options")
    assert "不排序" in compare["output_summary"]
    assert any("不替你排序" in item["text"] for item in body["suggestions"])
    assert "你应该选" not in response.text
    assert "唯一正确答案" not in response.text


def test_rag_off_is_skipped_not_faked(client: TestClient) -> None:
    created = _start(client, CODE, "我想让它跑起来。")

    body = client.get(f"/api/v1/sessions/{created['session_id']}/agent").json()

    search = next(step for step in body["steps"] if step["tool"] == "search_patterns")
    assert search["status"] == "skipped"
    assert "RAG 未开启" in search["output_summary"]


def test_rag_hits_are_cited_and_query_is_a_label() -> None:
    retriever = _Retriever((_card(),))
    client = _client(knowledge=KnowledgeService(retriever))
    created = _start(client, CODE, "我想让它跑起来。")

    body = client.get(f"/api/v1/sessions/{created['session_id']}/agent").json()

    search = next(step for step in body["steps"] if step["tool"] == "search_patterns")
    assert search["status"] == "ok"
    assert search["citations"] == [
        {
            "card_id": "K_CODE_TEST_FIRST",
            "title": "先写一个最小可复现测试",
            "source_title": "Python 文档：unittest",
            "source_url": "https://docs.python.org/3/library/unittest.html",
            "license": "PSF-2.0",
        }
    ]
    assert retriever.queries and "SECRET" not in retriever.queries[0]
    assert any(item["source"] == "knowledge" for item in body["suggestions"])


def test_rag_failure_degrades_to_a_failed_step() -> None:
    client = _client(knowledge=KnowledgeService(_BrokenRetriever()))
    created = _start(client, CODE, "我想让它跑起来。")

    response = client.get(f"/api/v1/sessions/{created['session_id']}/agent")

    assert response.status_code == 200, response.text
    body = response.json()
    search = next(step for step in body["steps"] if step["tool"] == "search_patterns")
    assert search["status"] == "failed"
    assert "没有引用" in search["output_summary"]


def test_explicit_code_is_run_once_and_never_extracted() -> None:
    executor = _Executor(
        ExecutionResult(
            status="fail",
            detail="AssertionError: expected 2",
            exit_code=1,
            duration_ms=7,
            stdout="1\n",
        )
    )
    client = _client(
        knowledge=KnowledgeService(None),
        executor=executor,
        execution=True,
    )
    created = _start(client, CODE, "我想让它跑起来。")
    code = "def test_it():\n    assert 1 == 2\n"

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/agent/run",
        json={"code": code, "tests": "from x import test_it\n"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    run = next(step for step in body["steps"] if step["tool"] == "run_tests")
    assert run["status"] == "ok"
    assert "运行状态=fail" in run["output_summary"]
    assert executor.commands == [
        RunCodeCommand(
            language="python",
            code=code,
            tests="from x import test_it\n",
        )
    ]
    assert code not in response.text


def test_execution_off_says_not_run_and_does_not_call_the_executor() -> None:
    executor = _Executor(
        ExecutionResult(status="pass", detail="should not run", exit_code=0, duration_ms=1)
    )
    client = _client(
        knowledge=KnowledgeService(None),
        executor=executor,
        execution=False,
    )
    created = _start(client, CODE, "我想让它跑起来。")

    body = client.post(
        f"/api/v1/sessions/{created['session_id']}/agent/run",
        json={"code": "print(1)\n"},
    ).json()

    run = next(step for step in body["steps"] if step["tool"] == "run_code")
    assert run["status"] == "skipped"
    assert "没有运行" in run["output_summary"]
    assert executor.commands == []


def test_code_is_rejected_for_a_non_executable_framework(client: TestClient) -> None:
    created = _start(client, DECISION, "我想换工作。")

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/agent/run",
        json={"code": "print(1)\n"},
    )

    assert response.status_code == 422, response.text


def test_tests_without_code_are_rejected(client: TestClient) -> None:
    created = _start(client, CODE, "我想让它跑起来。")

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/agent/run",
        json={"tests": "assert True\n"},
    )

    assert response.status_code == 422, response.text


def test_trace_is_not_available_for_a_graph_session(client: TestClient) -> None:
    created = _start(client, MATH, "a≥1/e")

    response = client.get(f"/api/v1/sessions/{created['session_id']}/agent")

    assert response.status_code == 409, response.text


def test_replay_returns_the_same_tool_sequence(client: TestClient) -> None:
    created = _start(client, CODE, "我想让它跑起来。")
    first = client.get(f"/api/v1/sessions/{created['session_id']}/agent").json()
    second = client.get(f"/api/v1/sessions/{created['session_id']}/agent").json()

    def strip_duration(trace: dict[str, object]) -> dict[str, object]:
        copy = dict(trace)
        copy["steps"] = [
            {key: value for key, value in step.items() if key != "duration_ms"}
            for step in trace["steps"]  # type: ignore[union-attr]
        ]
        return copy

    assert strip_duration(first) == strip_duration(second)
