"""Phase 2: executable verification is explicit, bounded and honest.

These tests run real child processes. They pin the properties that matter more
than a happy path:

* no tests means "the program exited 0", not "the answer is correct";
* a submitted test suite can fail, and a timeout is reported as a timeout;
* the static gate rejects network/process/reflection before spawning;
* output is capped and the pass detail never claims more than it checked.
"""

from __future__ import annotations

import time
import unittest

from synapse.application.execution import (
    ExecutionBusy,
    ExecutionFinding,
    ExecutionResult,
    RunCodeCommand,
)
from synapse.infrastructure.execution import ExecutionLimits, LocalPythonExecutor
from synapse.infrastructure.execution.static_gate import check_source

LIMITS = ExecutionLimits(timeout_s=1.0, memory_mb=128, max_output_bytes=2000)


def _run(code: str, tests: str = "") -> ExecutionResult:
    return LocalPythonExecutor(LIMITS).run(
        RunCodeCommand(language="python", code=code, tests=tests)
    )


class TestStaticGate(unittest.TestCase):
    def test_network_import_is_rejected(self) -> None:
        result = _run("import socket\nprint('never')\n")
        assert result.status == "rejected"
        assert result.exit_code is None
        assert any(f.code == "forbidden_import" for f in result.findings)
        assert "socket" in result.findings[0].message

    def test_eval_is_rejected(self) -> None:
        result = _run("eval('1+1')\n")
        assert result.status == "rejected"
        assert any(f.code == "forbidden_call" for f in result.findings)

    def test_sys_modules_is_rejected(self) -> None:
        result = _run("import sys\nprint(sys.modules)\n")
        assert result.status == "rejected"
        assert any(f.code == "forbidden_attribute" for f in result.findings)

    def test_sys_alias_and_star_import_cannot_reach_modules(self) -> None:
        for code in (
            "import sys as s\nprint(s.modules)\n",
            "from sys import *\nprint(modules)\n",
            "import sys\nsys.settrace(None)\n",
            "import sys\ng = getattr\ng(sys, 'modules')\n",
            "from sys import settrace\nsettrace(None)\n",
            "from sys import __dict__\nprint(__dict__)\n",
        ):
            result = _run(code)
            assert result.status == "rejected", code
            assert any(
                f.code in {"forbidden_attribute", "forbidden_import", "forbidden_call"}
                for f in result.findings
            )

    def test_mock_and_queue_are_rejected_instead_of_failing_at_runtime(self) -> None:
        for code in ("import queue\n", "import unittest.mock\n", "from unittest import mock\n"):
            result = _run(code)
            assert result.status == "rejected", code
            assert any(f.code == "forbidden_import" for f in result.findings)

    def test_syntax_error_is_a_finding_not_a_crash(self) -> None:
        result = _run("def broken(:\n")
        assert result.status == "rejected"
        assert any(f.code == "syntax_error" for f in result.findings)

    def test_gate_does_not_need_a_subprocess(self) -> None:
        gate = check_source("x = 1\n", "code", max_bytes=100)
        assert gate.ok


class TestRunner(unittest.TestCase):
    def test_a_program_that_exits_zero_is_only_a_run(self) -> None:
        result = _run("print(1 + 1)\n")
        assert result.status == "pass"
        assert result.exit_code == 0
        assert result.stdout.strip() == "2"
        assert "不证明答案正确" in result.detail

    def test_a_runtime_error_is_a_failure_with_stderr(self) -> None:
        result = _run("raise ValueError('boom')\n")
        assert result.status == "fail"
        assert result.exit_code != 0
        assert "ValueError" in result.stderr

    def test_submitted_tests_can_pass(self) -> None:
        code = "def add(a, b):\n    return a + b\n"
        tests = (
            "import unittest\n"
            "from main import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
        )
        result = _run(code, tests)
        assert result.status == "pass"
        assert "提交的测试全部通过" in result.detail
        assert "不证明代码正确" in result.detail

    def test_submitted_tests_can_fail(self) -> None:
        code = "def add(a, b):\n    return a - b\n"
        tests = (
            "import unittest\n"
            "from main import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
        )
        result = _run(code, tests)
        assert result.status == "fail"
        assert result.exit_code != 0
        assert "测试未全部通过" in result.detail

    def test_a_timeout_is_not_a_failure_verdict(self) -> None:
        result = _run("while True:\n    pass\n")
        assert result.status == "timeout"
        assert result.exit_code is None
        assert "墙钟" in result.detail

    def test_memory_limit_is_enforced(self) -> None:
        result = _run("x = bytearray(512 * 1024 * 1024)\n")
        assert result.status == "fail"
        assert result.exit_code != 0

    def test_output_is_capped_and_marked(self) -> None:
        result = _run("print('x' * 5000)\n")
        assert result.status == "pass"
        assert result.truncated is True
        assert len(result.stdout) <= 2000
        assert "截断" in result.detail

    def test_no_tests_discovered_is_a_failure(self) -> None:
        result = _run("print('ok')\n", "import unittest\n")
        assert result.status == "fail"
        assert result.exit_code == 2
        assert "没有发现" in result.detail

    def test_one_execution_slot_is_exclusive(self) -> None:
        executor = LocalPythonExecutor(LIMITS)
        # Acquire the only slot the same way ``run`` would, without relying on
        # timing a background thread.
        assert executor._slots.acquire(blocking=False)
        try:
            with self.assertRaises(ExecutionBusy):
                executor.run(RunCodeCommand(language="python", code="print(1)\n"))
        finally:
            executor._slots.release()

    def test_findings_are_capped(self) -> None:
        code = "import socket\nimport os\nimport subprocess\nimport ctypes\nimport sys\n"
        result = _run(code)
        assert result.status == "rejected"
        assert 1 <= len(result.findings) <= 5
        assert all(isinstance(f, ExecutionFinding) for f in result.findings)

    def test_timeout_wall_clock_is_bounded(self) -> None:
        started = time.monotonic()
        _run("while True:\n    pass\n")
        assert time.monotonic() - started < 5
