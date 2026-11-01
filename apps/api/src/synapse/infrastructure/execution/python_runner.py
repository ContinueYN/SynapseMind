"""Bounded local Python execution (Phase 2).

This adapter is deliberately *not* described as a container sandbox. It runs
one explicitly submitted Python file in a fresh temporary directory, under a
short wall-clock limit, a memory cap, a single-process job, a static import/call
gate and a Python audit hook that denies network and process creation. That is
a useful local boundary for trusted exercises; it is not a defence against a
hostile machine owner. The API is therefore off by default and says so.

Only Python is supported in v0.1. There is no hidden test generation: the
caller supplies the tests, and ``pass`` means those tests passed.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from synapse.application.execution import (
    ExecutionBusy,
    ExecutionFinding,
    ExecutionResult,
    ExecutionStatus,
    RunCodeCommand,
)
from synapse.infrastructure.execution.static_gate import check_source

_DEFAULT_TIMEOUT_S = 5.0
_DEFAULT_MEMORY_MB = 256
_DEFAULT_OUTPUT_BYTES = 32_000
_DEFAULT_CODE_BYTES = 20_000
_MAX_TIMEOUT_S = 10.0
_MAX_MEMORY_MB = 1024
_MAX_OUTPUT_BYTES = 32_000
_MAX_CODE_BYTES = 50_000
_MAX_CONCURRENT = 2
_MAX_DETAIL = 1000
_MAX_FINDING = 300


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    timeout_s: float = _DEFAULT_TIMEOUT_S
    memory_mb: int = _DEFAULT_MEMORY_MB
    max_output_bytes: int = _DEFAULT_OUTPUT_BYTES
    max_code_bytes: int = _DEFAULT_CODE_BYTES
    max_concurrent: int = 1
    python: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ExecutionLimits:
        source = os.environ if env is None else env
        timeout = float(source.get("SYNAPSE_EXEC_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
        memory = int(source.get("SYNAPSE_EXEC_MEMORY_MB", _DEFAULT_MEMORY_MB))
        output = int(source.get("SYNAPSE_EXEC_MAX_OUTPUT", _DEFAULT_OUTPUT_BYTES))
        code = int(source.get("SYNAPSE_EXEC_MAX_CODE", _DEFAULT_CODE_BYTES))
        concurrent = int(source.get("SYNAPSE_EXEC_MAX_CONCURRENT", 1))
        if not 0.5 <= timeout <= _MAX_TIMEOUT_S:
            raise ValueError(f"SYNAPSE_EXEC_TIMEOUT_S={timeout!r}: expected 0.5–{_MAX_TIMEOUT_S:g}")
        if not 64 <= memory <= _MAX_MEMORY_MB:
            raise ValueError(f"SYNAPSE_EXEC_MEMORY_MB={memory!r}: expected 64–{_MAX_MEMORY_MB}")
        if not 1000 <= output <= _MAX_OUTPUT_BYTES:
            raise ValueError(
                f"SYNAPSE_EXEC_MAX_OUTPUT={output!r}: expected 1000–{_MAX_OUTPUT_BYTES}"
            )
        if not 1000 <= code <= _MAX_CODE_BYTES:
            raise ValueError(f"SYNAPSE_EXEC_MAX_CODE={code!r}: expected 1000–{_MAX_CODE_BYTES}")
        if not 1 <= concurrent <= _MAX_CONCURRENT:
            raise ValueError(
                f"SYNAPSE_EXEC_MAX_CONCURRENT={concurrent!r}: expected 1–{_MAX_CONCURRENT}"
            )
        return cls(
            timeout_s=timeout,
            memory_mb=memory,
            max_output_bytes=output,
            max_code_bytes=code,
            max_concurrent=concurrent,
            python=source.get("SYNAPSE_EXEC_PYTHON", "").strip(),
        )


def _default_python() -> str:
    """Prefer the base interpreter over a venv launcher.

    A Windows venv can be a small launcher that re-execs the base interpreter.
    A one-process job object would block that second process, so the child is
    started from the real base executable instead. The harness only needs the
    standard library.
    """

    base = getattr(sys, "_base_executable", "")
    if base and os.path.isfile(base):
        return str(base)
    return sys.executable


class LocalPythonExecutor:
    """One-at-a-time runner; no queue, no background job, no retry."""

    def __init__(
        self,
        limits: ExecutionLimits | None = None,
        *,
        python: str | None = None,
    ) -> None:
        self._limits = limits or ExecutionLimits.from_env()
        self._python = python or self._limits.python or _default_python()
        self._slots = threading.BoundedSemaphore(self._limits.max_concurrent)

    def run(self, command: RunCodeCommand) -> ExecutionResult:
        if command.language != "python":
            return _rejected(
                "只支持 Python（v0.1）。",
                [ExecutionFinding("forbidden_call", f"暂不支持语言 {command.language!r}。")],
            )

        code_gate = check_source(command.code, "code", max_bytes=self._limits.max_code_bytes)
        tests_gate = (
            check_source(command.tests, "tests", max_bytes=self._limits.max_code_bytes)
            if command.tests.strip()
            else None
        )
        findings = list(code_gate.findings)
        if tests_gate is not None:
            findings.extend(tests_gate.findings)
        if findings:
            return _rejected("提交没有运行：静态检查拒绝了代码。", findings)

        if not self._slots.acquire(blocking=False):
            raise ExecutionBusy("本地执行位正忙，请等当前这次结束再提交。")
        try:
            return self._run_gated(command)
        finally:
            self._slots.release()

    def _run_gated(self, command: RunCodeCommand) -> ExecutionResult:
        started = time.monotonic()
        has_tests = bool(command.tests.strip())
        root = Path(tempfile.mkdtemp(prefix="synapse-exec-"))
        proc: subprocess.Popen[bytes] | None = None
        job: _Job | None = None
        try:
            (root / "main.py").write_text(command.code, encoding="utf-8")
            if has_tests:
                (root / "test_main.py").write_text(command.tests, encoding="utf-8")
            (root / "runner.py").write_text(
                _runner_source(self._limits.timeout_s, self._limits.memory_mb),
                encoding="utf-8",
            )

            try:
                proc, job = _spawn(
                    self._python,
                    root,
                    memory_mb=self._limits.memory_mb,
                )
            except OSError as exc:
                return _rejected(
                    "本地执行器无法启动受限进程，未运行代码。",
                    [ExecutionFinding("sandbox_unavailable", _clip(str(exc), _MAX_FINDING))],
                )

            stdout = _Buffer(self._limits.max_output_bytes)
            stderr = _Buffer(self._limits.max_output_bytes)
            readers = [
                threading.Thread(target=stdout.consume, args=(proc.stdout,), daemon=True),
                threading.Thread(target=stderr.consume, args=(proc.stderr,), daemon=True),
            ]
            for reader in readers:
                reader.start()

            timed_out = False
            try:
                proc.wait(timeout=self._limits.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate(proc, job)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            finally:
                for reader in readers:
                    reader.join(timeout=2)
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()
                if job is not None:
                    job.close()
                    job = None

            duration_ms = min(60_000, max(0, int((time.monotonic() - started) * 1000)))
            out = stdout.text
            err = stderr.text
            truncated = stdout.truncated or stderr.truncated
            return _result(
                status="timeout" if timed_out else ("pass" if proc.returncode == 0 else "fail"),
                has_tests=has_tests,
                exit_code=None if timed_out else proc.returncode,
                duration_ms=duration_ms,
                stdout=out,
                stderr=err,
                truncated=truncated,
                timeout_s=self._limits.timeout_s,
            )
        finally:
            if proc is not None and proc.poll() is None:
                _terminate(proc, job)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=2)
            if job is not None:
                job.close()
            shutil.rmtree(root, ignore_errors=True)


class _Buffer:
    """Read a pipe without ever holding more than the configured cap."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: list[bytes] = []
        self._total = 0
        self.truncated = False

    def consume(self, stream: IO[bytes] | None) -> None:
        if stream is None:
            return
        while True:
            try:
                chunk = stream.read(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            if self._total < self._limit:
                take = chunk[: self._limit - self._total]
                self._chunks.append(take)
                self._total += len(take)
                if len(take) < len(chunk):
                    self.truncated = True
            else:
                self.truncated = True

    @property
    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


def _result(
    *,
    status: ExecutionStatus,
    has_tests: bool,
    exit_code: int | None,
    duration_ms: int,
    stdout: str,
    stderr: str,
    truncated: bool,
    timeout_s: float,
) -> ExecutionResult:
    findings: tuple[ExecutionFinding, ...] = ()
    if status == "timeout":
        detail = f"超过 {timeout_s:g} 秒墙钟上限，进程已被终止；没有结果。"
    elif status == "pass":
        detail = (
            "提交的测试全部通过；这只说明测试跑过，不证明代码正确或覆盖完整。"
            if has_tests
            else "进程退出码为 0；这只说明代码跑完，不证明答案正确。"
        )
    elif has_tests and exit_code == 2 and "NO_TESTS" in stderr:
        detail = "提交的测试文件里没有发现 unittest 测试；没有可判定的通过。"
    elif has_tests:
        detail = f"测试未全部通过（退出码 {exit_code}）；只运行了提交的测试，没有运行隐藏测试。"
    else:
        detail = f"进程退出码为 {exit_code}；不是可执行验证通过。"
    if truncated:
        detail = _clip(detail + " 输出已按上限截断。", _MAX_DETAIL)
    return ExecutionResult(
        status=status,
        detail=_clip(detail, _MAX_DETAIL),
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=_clip(stdout, _MAX_OUTPUT_BYTES),
        stderr=_clip(stderr, _MAX_OUTPUT_BYTES),
        truncated=truncated,
        findings=findings,
    )


def _rejected(detail: str, findings: list[ExecutionFinding]) -> ExecutionResult:
    clipped = tuple(
        ExecutionFinding(
            finding.code,
            _clip(finding.message, _MAX_FINDING) or "执行器拒绝运行。",
        )
        for finding in findings[:5]
    )
    return ExecutionResult(
        status="rejected",
        detail=_clip(detail, _MAX_DETAIL),
        exit_code=None,
        duration_ms=0,
        findings=clipped,
    )


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _spawn(
    python: str,
    root: Path,
    *,
    memory_mb: int,
) -> tuple[subprocess.Popen[bytes], _Job | None]:
    env = _env(root)
    if sys.platform == "win32":
        job = _WindowsJob(memory_mb)
        try:
            proc = subprocess.Popen(
                [python, "-I", "-B", "runner.py"],
                cwd=str(root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except BaseException:
            job.close()
            raise
        try:
            job.assign(proc)
        except OSError:
            proc.kill()
            proc.wait(timeout=2)
            job.close()
            raise
        return proc, job

    proc = subprocess.Popen(
        [python, "-I", "-B", "runner.py"],
        cwd=str(root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
    )
    return proc, None


def _env(root: Path) -> dict[str, str]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": str(root),
        "USERPROFILE": str(root),
        "TMP": str(root),
        "TEMP": str(root),
        "PATH": "",
    }
    for key in ("SYSTEMROOT", "WINDIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _terminate(proc: subprocess.Popen[bytes], job: _Job | None) -> None:
    if job is not None:
        job.terminate()
        return
    killpg = getattr(os, "killpg", None)
    if callable(killpg):
        try:
            killpg(proc.pid, 9)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    with contextlib.suppress(OSError):
        proc.kill()


def _runner_source(timeout_s: float, memory_mb: int) -> str:
    return _RUNNER.replace("__TIMEOUT__", f"{timeout_s:g}").replace(
        "__MEMORY_BYTES__", str(memory_mb * 1024 * 1024)
    )


class _Job:
    def terminate(self) -> None: ...

    def close(self) -> None: ...


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if callable(getter) else 0


class _WindowsJob(_Job):
    _KILL_ON_JOB_CLOSE = 0x00002000
    _ACTIVE_PROCESS = 0x00000008
    _PROCESS_MEMORY = 0x00000100
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self, memory_mb: int) -> None:
        if sys.platform != "win32":
            raise OSError("Windows job objects are unavailable")
        win_dll = getattr(ctypes, "WinDLL", None)
        if not callable(win_dll):
            raise OSError("ctypes.WinDLL is unavailable")
        self._kernel32: Any = win_dll("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self._kernel32.SetInformationJobObject.restype = ctypes.c_int
        self._kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        self._kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.TerminateJobObject.restype = ctypes.c_int
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_int
        self._handle: int | None = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(_last_error(), "CreateJobObjectW failed")
        try:
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = (
                self._KILL_ON_JOB_CLOSE | self._ACTIVE_PROCESS | self._PROCESS_MEMORY
            )
            info.BasicLimitInformation.ActiveProcessLimit = 1
            info.ProcessMemoryLimit = memory_mb * 1024 * 1024
            ok = self._kernel32.SetInformationJobObject(
                self._handle,
                self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                raise OSError(_last_error(), "SetInformationJobObject failed")
        except BaseException:
            self.close()
            raise

    def assign(self, proc: subprocess.Popen[bytes]) -> None:
        handle = getattr(proc, "_handle", None)
        if handle is None or self._handle is None:
            raise OSError("process/job handle unavailable")
        if not self._kernel32.AssignProcessToJobObject(self._handle, handle):
            raise OSError(_last_error(), "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None


_RUNNER = r'''"""Generated harness. Keep the audit hook ahead of all student code."""
import os
import runpy
import sys
import traceback
import unittest

# POSIX limits are applied by the child itself, before the audit hook. Doing
# this here (instead of ``preexec_fn``) avoids running Python code in the
# parent between fork and exec, which is unsafe in FastAPI's thread pool.
if sys.platform != "win32":
    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        for _name, _value in (
            ("RLIMIT_AS", __MEMORY_BYTES__),
            ("RLIMIT_DATA", __MEMORY_BYTES__),
            ("RLIMIT_CPU", int(__TIMEOUT__) + 2),
            ("RLIMIT_FSIZE", 1_000_000),
            ("RLIMIT_NOFILE", 64),
            ("RLIMIT_CORE", 0),
        ):
            _id = getattr(resource, _name, None)
            if _id is None:
                continue
            try:
                resource.setrlimit(_id, (_value, _value))
            except (OSError, ValueError):
                pass

ROOT = os.path.realpath(os.getcwd())
BASE = os.path.realpath(sys.base_prefix)
BLOCKED_IMPORTS = {
    "os", "nt", "posix", "subprocess", "socket", "_socket", "ctypes", "cffi",
    "importlib", "builtins", "pathlib", "shutil", "tempfile", "threading",
    "multiprocessing", "asyncio", "resource", "signal", "gc", "inspect",
    "pty", "tty", "termios", "fcntl", "mmap", "urllib", "http", "ftplib",
    "smtplib", "telnetlib", "xmlrpc", "requests", "httpx",
}
WRITE_FLAGS = 0
for _name in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"):
    WRITE_FLAGS |= getattr(os, _name, 0)


def _inside(path, root):
    try:
        candidate = os.path.normcase(os.path.realpath(path))
        boundary = os.path.normcase(os.path.realpath(root))
        return os.path.commonpath((boundary, candidate)) == boundary
    except (OSError, ValueError):
        return False


def audit(event, args):
    if event.startswith(("socket.", "subprocess.", "ctypes.")):
        raise PermissionError("network/process access is disabled")
    if event in {
        "os.system", "os.exec", "os.spawn", "os.fork", "os.forkpty",
        "os.posix_spawn", "os.chdir",
    }:
        raise PermissionError("process/filesystem mutation is disabled")
    if event.startswith("os.") and event in {
        "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.makedirs",
        "os.link", "os.symlink", "os.truncate", "os.chmod", "os.chown",
    }:
        raise PermissionError("filesystem mutation is disabled")
    if event == "import":
        name = str(args[0]).split(".", 1)[0]
        if name in BLOCKED_IMPORTS:
            raise PermissionError("import is disabled: " + name)
    if event == "open":
        path, mode, flags = args
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        target = os.fsdecode(path)
        if not os.path.isabs(target):
            target = os.path.join(ROOT, target)
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        if isinstance(flags, int) and flags & WRITE_FLAGS:
            writing = True
        if writing:
            if not _inside(target, ROOT):
                raise PermissionError("writes are limited to the run directory")
        elif not (_inside(target, ROOT) or _inside(target, BASE)):
            raise PermissionError("reads are limited to the run directory and the stdlib")


sys.addaudithook(audit)


def _run_tests():
    loader = unittest.TestLoader()
    suite = loader.discover(ROOT, pattern="test_main.py", top_level_dir=ROOT)
    if suite.countTestCases() == 0:
        print("NO_TESTS", file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def _main():
    if os.path.exists("test_main.py"):
        return _run_tests()
    runpy.run_path("main.py", run_name="__main__")
    return 0


try:
    code = _main()
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
except BaseException:
    traceback.print_exc()
    code = 1
sys.exit(code)
'''
