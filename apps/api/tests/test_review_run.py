"""T4: the code reproduction card, mapped from one explicit run.

The card is allowed to be useful without being a diagnosis. These tests pin the
boundaries that keep it honest:

* only an explicit ``code``/``tests`` submission is run, and only for an
  ``EXECUTABLE`` session; the problem statement is never executed;
* ``SYNAPSE_EXEC=off`` returns ``skipped`` without calling the executor, not a
  fake run and certainly not a pass;
* ``fail``/``timeout``/``rejected`` keep their own meaning; ``rejected`` means
  the code never ran, so it has no stdout and no first failure;
* no finding is invented without ``source="execution"``, ``ref="run"``;
* the session is not written and the answer store is not read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.execution.service import (
    ExecutionBusy,
    ExecutionFinding,
    ExecutionResult,
    RunCodeCommand,
)
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.in_memory import InMemoryAnswerStore

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "generic-review.schema.json"

CODE_PROBLEM = "我的 Python 脚本报错了：IndexError: list index out of range，应该怎么修？"
DECISION = "我应该接受北京的工作机会，还是留在上海陪家人？"
MATH = "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"

UNITTEST_STDERR = """F
======================================================================
FAIL: test_sort (__main__.TestSort.test_sort)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "test_sort.py", line 6, in test_sort
    self.assertEqual(sort([3, 1, 2]), [1, 2, 3])
AssertionError: Lists differ: [2, 1, 3] != [1, 2, 3]
----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)
"""


class _Executor:
    """A fake adapter that records the one command it was given."""

    def __init__(self, result: ExecutionResult | Exception) -> None:
        self.result = result
        self.commands: list[RunCodeCommand] = []

    def run(self, command: RunCodeCommand) -> ExecutionResult:
        self.commands.append(command)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(
    *,
    executor: object | None = None,
    execution: bool = False,
) -> TestClient:
    return TestClient(
        create_app(
            build_container(
                features=FeatureFlags(execution=execution),
                executor=executor,  # type: ignore[arg-type]
            )
        )
    )


def _start(
    client: TestClient,
    text: str,
    answer: str,
    *,
    subject: str | None = None,
) -> dict[str, object]:
    problem: dict[str, object] = {"text": text}
    if subject is not None:
        problem["subject"] = subject
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": problem,
            "attempt": {"answer": answer, "work": "", "self_report": "unsure"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _run(client: TestClient, session_id: object, **payload: object) -> dict[str, object]:
    response = client.post(
        f"/api/v1/sessions/{session_id}/review/run",
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    Draft202012Validator(json.loads(SPEC_PATH.read_text(encoding="utf-8"))).validate(body)
    return body


def _failure_result() -> ExecutionResult:
    return ExecutionResult(
        status="fail",
        detail="测试未全部通过（退出码 1）；只运行了提交的测试，没有运行隐藏测试。",
        exit_code=1,
        duration_ms=12,
        stdout="",
        stderr=UNITTEST_STDERR,
    )


def test_off_returns_a_skipped_card_without_calling_the_executor() -> None:
    executor = _Executor(ExecutionResult(status="pass", detail="", exit_code=0, duration_ms=1))
    client = _client(executor=executor, execution=False)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    body = _run(
        client,
        created["session_id"],
        code="print('SECRET_EXPLICIT_CODE')\n",
        tests="assert True\n",
    )

    assert body["kind"] == "execution"
    assert body["domain"]["verification"] == "executable"
    assert body["execution"] == {"status": "skipped", "tests_submitted": True}
    assert body["findings"] == []
    assert body["evidence"] == []
    assert "没有运行" in body["headline"]
    assert "通过" not in body["headline"]
    assert executor.commands == []
    assert any("SYNAPSE_EXEC=on" in item for item in body["not_checked"]) or (
        "SYNAPSE_EXEC=on" in body["next_step"]
    )
    assert "工具轨迹" in body["next_step"]
    assert any("没有判断代码是否正确" in item for item in body["not_checked"])
    assert "skipped 只表示这次没有运行" in body["disclaimer"]


def test_fail_maps_to_fail_with_the_first_failure() -> None:
    executor = _Executor(_failure_result())
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")
    code = "def sort(items):\n    return items\n"
    tests = "from solution import sort\n"

    body = _run(client, created["session_id"], code=code, tests=tests)

    assert body["execution"]["status"] == "fail"
    assert body["execution"]["tests_submitted"] is True
    assert "AssertionError: Lists differ" in body["execution"]["first_failure"]
    assert body["execution"]["first_failure"] in body["headline"]
    failure = body["findings"][0]
    assert failure["kind"] == "test_failure"
    assert failure["severity"] == "blocking"
    assert "AssertionError" in failure["summary"]
    # The finding points at the one run record, not at the problem text.
    assert failure["evidence_refs"] == ["ev1"]
    assert body["evidence"] == [
        {
            "id": "ev1",
            "source": "execution",
            "ref": "run",
            "excerpt": body["evidence"][0]["excerpt"],
        }
    ]
    assert body["evidence"][0]["excerpt"].startswith("运行状态=fail")
    assert code not in json.dumps(body, ensure_ascii=False)
    assert "没有判断代码是否正确" in body["not_checked"][0]
    assert executor.commands == [RunCodeCommand(language="python", code=code, tests=tests)]


def test_pass_does_not_claim_the_code_is_correct() -> None:
    executor = _Executor(
        ExecutionResult(
            status="pass",
            detail="提交的测试全部通过；这只说明测试跑过，不证明代码正确或覆盖完整。",
            exit_code=0,
            duration_ms=9,
            stdout="ok\n",
        )
    )
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    body = _run(client, created["session_id"], code="print('ok')\n")

    execution = body["execution"]
    assert execution["status"] == "pass"
    assert "first_failure" not in execution
    assert execution["tests_submitted"] is False
    assert body["findings"] == []
    assert "退出码 0" in body["headline"]
    assert "不说明" in body["disclaimer"] or "不表示" in body["disclaimer"]
    assert "pass 只表示退出码 0 或提交的测试通过" in body["disclaimer"]
    assert "没有判断代码是否正确" in body["not_checked"][0]
    # A pass is a run status, never a correctness claim.
    text = json.dumps(body, ensure_ascii=False)
    assert "你的代码正确" not in text
    assert "代码是正确的" not in text


def test_timeout_keeps_its_own_status_and_finding() -> None:
    executor = _Executor(
        ExecutionResult(
            status="timeout",
            detail="超过 5 秒墙钟上限，进程已被终止；没有结果。",
            exit_code=None,
            duration_ms=5000,
            stdout="start\n",
        )
    )
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    body = _run(client, created["session_id"], code="while True: pass\n")

    assert body["execution"]["status"] == "timeout"
    assert "first_failure" not in body["execution"]
    assert body["findings"][0]["kind"] == "execution_timeout"
    assert body["findings"][0]["evidence_refs"] == ["ev1"]
    assert body["evidence"][0]["source"] == "execution"
    assert body["evidence"][0]["ref"] == "run"
    assert "超时" in body["headline"]
    assert "通过" not in body["headline"]


def test_rejected_never_fabricates_output_or_a_failure() -> None:
    executor = _Executor(
        ExecutionResult(
            status="rejected",
            detail="提交没有运行：静态检查拒绝了代码。",
            exit_code=None,
            duration_ms=0,
            stderr="",
            findings=(ExecutionFinding("forbidden_import", "不能导入 socket。"),),
        )
    )
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    body = _run(client, created["session_id"], code="import socket\n")

    execution = body["execution"]
    assert execution["status"] == "rejected"
    assert "stdout_excerpt" not in execution
    assert "first_failure" not in execution
    assert body["findings"][0]["kind"] == "execution_rejected"
    assert "没有运行" in body["headline"]
    assert "rejected 表示代码被静态闸门拒绝" in body["disclaimer"]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        (DECISION, "我想换工作。"),
        (MATH, "a≥1/e"),
    ],
)
def test_a_non_executable_session_is_rejected_without_running(
    text: str,
    answer: str,
) -> None:
    executor = _Executor(ExecutionResult(status="pass", detail="", exit_code=0, duration_ms=1))
    client = _client(executor=executor, execution=True)
    created = _start(client, text, answer)

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/review/run",
        json={"code": "print(1)\n"},
    )

    assert response.status_code == 409, response.text
    assert "可执行验证" in response.json()["detail"]
    assert executor.commands == []


def test_the_problem_statement_is_never_executed() -> None:
    executor = _Executor(ExecutionResult(status="pass", detail="", exit_code=0, duration_ms=1))
    client = _client(executor=executor, execution=True)
    problem_code = "print('PROBLEM_TEXT_CODE')\n"
    created = _start(
        client,
        f"{CODE_PROBLEM} 这是我的代码：{problem_code}",
        f"我试过 {problem_code}，还是报错。",
    )

    # Creating the session and reloading it must not execute anything.
    assert executor.commands == []
    client.get(f"/api/v1/sessions/{created['session_id']}")
    assert executor.commands == []

    explicit = "print('EXPLICIT_SUBMISSION')\n"
    _run(client, created["session_id"], code=explicit)

    assert len(executor.commands) == 1
    assert executor.commands[0].code == explicit
    assert "PROBLEM_TEXT_CODE" not in executor.commands[0].code


def test_blank_tests_are_treated_as_not_submitted() -> None:
    executor = _Executor(
        ExecutionResult(status="pass", detail="", exit_code=0, duration_ms=1, stdout="ok\n")
    )
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    body = _run(client, created["session_id"], code="print(1)\n", tests="   \n")

    assert body["execution"]["tests_submitted"] is False
    assert executor.commands[0].tests == ""


def test_blank_code_is_422_before_the_executor() -> None:
    executor = _Executor(ExecutionResult(status="pass", detail="", exit_code=0, duration_ms=1))
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/review/run",
        json={"code": "   "},
    )

    assert response.status_code == 422
    assert executor.commands == []


def test_busy_is_429_with_retry_after() -> None:
    executor = _Executor(ExecutionBusy("本地执行位正忙。"))
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/review/run",
        json={"code": "print(1)\n"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def test_the_session_is_not_written_and_the_answer_store_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_: object, **__: object) -> str:
        raise AssertionError("the review run must not read the answer store")

    monkeypatch.setattr(InMemoryAnswerStore, "answer_for", _boom)
    monkeypatch.setattr(InMemoryAnswerStore, "solution_for", _boom)

    executor = _Executor(_failure_result())
    client = _client(executor=executor, execution=True)
    created = _start(client, CODE_PROBLEM, "我想让它跑起来。")
    before = client.get(f"/api/v1/sessions/{created['session_id']}").json()

    body = _run(client, created["session_id"], code="print(1)\n")

    after = client.get(f"/api/v1/sessions/{created['session_id']}").json()
    assert after == before
    assert "answer" not in body
    assert "solution" not in body
