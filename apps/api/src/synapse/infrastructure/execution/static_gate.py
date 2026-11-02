"""Static gate for explicitly submitted Python.

The gate is intentionally conservative and readable. It is *not* the security
boundary by itself; the subprocess, audit hook and OS limits sit behind it. Its
job is to reject the obvious things before spending a process on them, and to
leave a finding the caller can show:

* imports whose root is not on the small standard-library allowlist;
* calls such as ``eval``/``exec``/``open``/``__import__``;
* attribute paths used to climb back to imports or frames;
* syntax errors and oversized submissions.

Rejecting a submission is an honest ``rejected`` result, never a failed test.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from synapse.application.execution.service import ExecutionFinding, ExecutionFindingCode

_ALLOWED_IMPORTS = frozenset(
    {
        "abc",
        "array",
        "bisect",
        "collections",
        "contextlib",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "json",
        "main",
        "math",
        "numbers",
        "operator",
        "pprint",
        "random",
        "re",
        "statistics",
        "string",
        "sys",
        "textwrap",
        "time",
        "traceback",
        "typing",
        "unittest",
        "warnings",
    }
)

_FORBIDDEN_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "help",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)

_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "__class__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__dict__",
        "__mro__",
        "__bases__",
        "__code__",
        "__closure__",
        "__loader__",
        "__spec__",
        "__getattribute__",
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "vars",
        "builtins",
        "importlib",
        "subprocess",
        "ctypes",
        "cffi",
        "multiprocessing",
        "threading",
        "asyncio",
        "_socket",
        "os",
        "sys",
        "resource",
        "signal",
        "gc",
        "inspect",
        "pathlib",
        "shutil",
        "tempfile",
        "urllib",
        "http",
        "modules",
        "path",
        "meta_path",
        "path_hooks",
        "path_importer_cache",
        "settrace",
        "setprofile",
        "f_globals",
        "f_builtins",
        "f_back",
        "f_locals",
        "gi_frame",
        "cr_frame",
        "ag_frame",
        "_getframe",
        "_current_frames",
        "system",
        "popen",
        "spawn",
        "fork",
        "execv",
        "execve",
        "connect",
        "socket",
        "urlopen",
    }
)

# ``sys`` is allowed for stdin/stdout/exit, but these attributes lead back to
# the import system or to frames, so they are rejected explicitly.
_FORBIDDEN_SYS_ATTRIBUTES = frozenset(
    {
        "modules",
        "path",
        "meta_path",
        "path_hooks",
        "path_importer_cache",
        "__dict__",
        "settrace",
        "setprofile",
        "_getframe",
        "_current_frames",
    }
)

_MAX_FINDINGS = 5


@dataclass(frozen=True, slots=True)
class GateResult:
    findings: tuple[ExecutionFinding, ...]
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.findings


def check_source(source: str, label: str, *, max_bytes: int) -> GateResult:
    findings: list[ExecutionFinding] = []

    size = len(source.encode("utf-8"))
    if size > max_bytes:
        findings.append(
            ExecutionFinding(
                code="too_large",
                message=f"{label} 有 {size} 字节，超过 {max_bytes} 字节上限。",
            )
        )
        return GateResult(tuple(findings))

    try:
        tree = ast.parse(source, filename=f"{label}.py")
    except SyntaxError as exc:
        line = exc.lineno or 0
        findings.append(
            ExecutionFinding(
                code="syntax_error",
                message=f"{label} 第 {line} 行语法错误：{exc.msg}。",
            )
        )
        return GateResult(tuple(findings))

    visitor = _GateVisitor(label, findings)
    visitor.visit(tree)
    return GateResult(tuple(_unique(findings, _MAX_FINDINGS)))


class _GateVisitor(ast.NodeVisitor):
    def __init__(self, label: str, findings: list[ExecutionFinding]) -> None:
        self._label = label
        self._findings = findings

    def _add(self, code: ExecutionFindingCode, message: str) -> None:
        self._findings.append(ExecutionFinding(code=code, message=message))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self._add(
                "forbidden_import",
                f"{self._label} 第 {node.lineno} 行使用了相对导入；只允许标准库白名单。",
            )
            return
        if node.module:
            if any(alias.name == "*" for alias in node.names):
                self._add(
                    "forbidden_import",
                    f"{self._label} 第 {node.lineno} 行使用了 import *；执行器要求显式导入。",
                )
                return
            self._check_import(node.module, node.lineno)
            if node.module == "unittest" and any(alias.name == "mock" for alias in node.names):
                self._add(
                    "forbidden_import",
                    f"{self._label} 第 {node.lineno} 行导入了 unittest.mock；"
                    "测试只允许普通 unittest，mock 会加载线程/异步模块。",
                )
            if node.module.split(".", 1)[0] == "sys":
                for alias in node.names:
                    if alias.name in _FORBIDDEN_SYS_ATTRIBUTES:
                        self._add(
                            "forbidden_attribute",
                            (
                                f"{self._label} 第 {node.lineno} 行从 sys 导入了 "
                                f"{alias.name}；只允许 sys 的输入输出与退出。"
                            ),
                        )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_CALLS:
            self._add(
                "forbidden_call",
                (
                    f"{self._label} 第 {node.lineno} 行引用了 {node.id}；"
                    "执行器不允许这类内置入口（包括先赋值给别名）。"
                ),
            )
        elif node.id == "__builtins__":
            self._add(
                "forbidden_attribute",
                (
                    f"{self._label} 第 {node.lineno} 行引用了 __builtins__；"
                    "执行器不允许访问内置命名空间。"
                ),
            )
        self.generic_visit(node)

    def _check_import(self, name: str, line: int) -> None:
        if name == "unittest.mock" or name.startswith("unittest.mock."):
            self._add(
                "forbidden_import",
                f"{self._label} 第 {line} 行导入了 unittest.mock；"
                "测试只允许普通 unittest，mock 会加载线程/异步模块。",
            )
            return
        root = name.split(".", 1)[0]
        if root not in _ALLOWED_IMPORTS:
            self._add(
                "forbidden_import",
                f"{self._label} 第 {line} 行导入了 {name}；只允许受限的标准库白名单。",
            )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
            self._add(
                "forbidden_call",
                f"{self._label} 第 {node.lineno} 行调用了 {node.func.id}；执行器不允许这类调用。",
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr in _FORBIDDEN_ATTRIBUTES:
            self._add(
                "forbidden_attribute",
                (
                    f"{self._label} 第 {node.lineno} 行访问了 .{attr}；"
                    "这属于执行器禁止的反射/进程入口。"
                ),
            )
        self.generic_visit(node)


def _unique(findings: list[ExecutionFinding], limit: int) -> list[ExecutionFinding]:
    seen: set[tuple[str, str]] = set()
    result: list[ExecutionFinding] = []
    for finding in findings:
        key = (finding.code, finding.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
        if len(result) >= limit:
            break
    return result
