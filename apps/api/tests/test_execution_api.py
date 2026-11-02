from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.deps import build_container, build_executor
from synapse.api.main import create_app
from synapse.application.execution.service import (
    ExecutionBusy,
    ExecutionFinding,
    ExecutionResult,
    RunCodeCommand,
)
from synapse.infrastructure.execution import ExecutionLimits, LocalPythonExecutor
from synapse.infrastructure.features import FeatureFlags

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "code-execution.schema.json"


class _PassThrough:
    def __init__(self) -> None:
        self.commands: list[RunCodeCommand] = []

    def run(self, command: RunCodeCommand) -> ExecutionResult:
        self.commands.append(command)
        return ExecutionResult(
            status="pass",
            detail="提交的测试全部通过；这只说明测试跑过，不证明代码正确或覆盖完整。",
            exit_code=0,
            duration_ms=7,
            stdout="ok\n",
            stderr="",
        )


class _Busy:
    def run(self, command: RunCodeCommand) -> ExecutionResult:
        raise ExecutionBusy("本地执行位正忙，请等当前这次结束再提交。")


class _Exploding:
    def run(self, command: RunCodeCommand) -> ExecutionResult:
        raise AssertionError("the off switch must not reach the executor")


def _client(features: FeatureFlags, executor: object | None = None) -> TestClient:
    return TestClient(
        create_app(
            build_container(
                features=features,
                executor=executor,  # type: ignore[arg-type]
            )
        )
    )


def test_the_execution_flag_defaults_off_and_is_explicit() -> None:
    assert FeatureFlags.from_env({}).execution is False
    assert FeatureFlags.from_env({"SYNAPSE_EXEC": "on"}).execution is True
    assert FeatureFlags.from_env({"SYNAPSE_EXEC": "off"}).execution is False
    assert build_executor(FeatureFlags(execution=False)) is None
    assert build_executor(FeatureFlags(execution=True)) is not None
    with pytest.raises(ValueError, match="SYNAPSE_EXEC"):
        FeatureFlags.from_env({"SYNAPSE_EXEC": "onn"})


def test_the_endpoint_is_off_by_default() -> None:
    client = _client(FeatureFlags(execution=False))

    response = client.post("/api/v1/executions", json={"language": "python", "code": "print(1)"})

    assert response.status_code == 403
    assert "SYNAPSE_EXEC=on" in response.json()["detail"]


def test_enabled_endpoint_returns_the_executor_result() -> None:
    executor = _PassThrough()
    client = _client(FeatureFlags(execution=True), executor)

    response = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print('ok')"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.1"
    assert payload["status"] == "pass"
    assert payload["exit_code"] == 0
    assert payload["stdout"] == "ok\n"
    assert payload["findings"] == []
    assert executor.commands[0].code == "print('ok')"


def test_response_matches_the_public_schema() -> None:
    executor = _PassThrough()
    client = _client(FeatureFlags(execution=True), executor)
    schema = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    payload = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print(1)"},
    ).json()

    Draft202012Validator(schema).validate(payload)


def test_a_rejected_run_matches_the_public_schema() -> None:
    schema = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    result = LocalPythonExecutor(
        ExecutionLimits(timeout_s=1.0, memory_mb=128, max_output_bytes=2000)
    ).run(RunCodeCommand(language="python", code="import socket\n"))
    container = build_container(
        features=FeatureFlags(execution=True),
        executor=LocalPythonExecutor(
            ExecutionLimits(timeout_s=1.0, memory_mb=128, max_output_bytes=2000)
        ),
    )
    client = TestClient(create_app(container))

    payload = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "import socket\n"},
    ).json()

    assert result.status == "rejected"
    assert payload["status"] == "rejected"
    assert payload["exit_code"] is None
    Draft202012Validator(schema).validate(payload)


def test_busy_is_429_with_retry_after() -> None:
    client = _client(FeatureFlags(execution=True), _Busy())

    response = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print(1)"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def test_oversized_submission_is_422_before_the_executor() -> None:
    executor = _Exploding()
    client = _client(FeatureFlags(execution=True), executor)

    response = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "x" * 20001},
    )

    assert response.status_code == 422


def test_findings_are_mapped_with_codes() -> None:
    class _Rejected:
        def run(self, command: RunCodeCommand) -> ExecutionResult:
            return ExecutionResult(
                status="rejected",
                detail="提交没有运行：静态检查拒绝了代码。",
                exit_code=None,
                duration_ms=0,
                findings=(ExecutionFinding("forbidden_import", "不能导入 socket。"),),
            )

    client = _client(FeatureFlags(execution=True), _Rejected())
    payload = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "import socket\n"},
    ).json()

    assert payload["findings"] == [{"code": "forbidden_import", "message": "不能导入 socket。"}]
