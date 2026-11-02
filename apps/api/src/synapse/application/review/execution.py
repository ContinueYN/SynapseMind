"""Compose the code reproduction branch of a generic review (T4).

This is the only place where an ``ExecutionResult`` becomes a product card. It
does not run anything and does not decide what to run: the route already
received one explicit submission, and ``application/execution/service.py`` owns the
bounded local run. The job here is the honest mapping:

* ``pass`` means the process exited 0 or the submitted tests passed. The card
  says exactly that and never that the code is correct;
* ``fail`` carries the first failure (from stderr, falling back to the
  executor's own detail) and one ``test_failure`` finding;
* ``timeout`` stays a timeout: no failure is invented, and no pass either;
* ``rejected`` means the static gate refused the code before it ran, so the card
  carries no stdout and no failure. The domain model enforces that as well;
* ``skipped`` (``SYNAPSE_EXEC=off``) records that nothing ran. It is not a run
  result, so it has no evidence record and no finding.

Every finding cites ``source="execution"``, ``ref="run"`` — the one run record
this card describes. Findings are never extracted from the problem statement or
the attempt, and the card is not a diagnosis: ``not_checked`` always names the
things that were not checked, starting with correctness itself.
"""

from __future__ import annotations

import re

from synapse.application.execution.service import ExecutionResult
from synapse.domain.problem.generic_review import (
    EvidenceSource,
    ExecutionStatus,
    FindingSeverity,
    GenericEvidence,
    GenericFinding,
    GenericReview,
    ReviewDomain,
    ReviewExecution,
    ReviewKind,
    ReviewVerification,
)

_MESSAGE_SKIPPED = "没有运行：本地执行开关关闭（SYNAPSE_EXEC=off）。"

_MAX_HEADLINE = 200
_MAX_SUMMARY = 240
_MAX_NOT_CHECKED = 240
_MAX_NEXT_STEP = 240
_MAX_DISCLAIMER = 300
_MAX_EXCERPT = 200
_MAX_FAILURE = 300
_MAX_STDOUT = 400
_MAX_DOMAIN = 40

# The first line that names the failing test or the raised exception. unittest
# prints "FAIL: test_x (...)" / "ERROR: ..." before the traceback, and an
# AssertionError line is the next most useful summary.
_FAILURE_HEADER = re.compile(r"^(FAIL|ERROR):\s*\S")
_EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Failure|Warning):")

_RUN_REF = "run"

_NOT_CHECKED_CORRECTNESS = "没有判断代码是否正确，也没有运行你提交以外的隐藏测试。"

_NOT_CHECKED_BY_STATUS: dict[ExecutionStatus, tuple[str, ...]] = {
    ExecutionStatus.PASS: ("没有检查题意、边界输入和复杂度；通过不等于符合要求。",),
    ExecutionStatus.FAIL: ("没有区分是实现写错、测试写错，还是环境差异；也没有定位到具体行。",),
    ExecutionStatus.TIMEOUT: ("没有分析是哪一步没有结束；超时不表示代码正确或错误。",),
    ExecutionStatus.REJECTED: ("代码没有运行，所以没有退出码、输出或失败信息。",),
    ExecutionStatus.SKIPPED: ("代码没有运行，所以没有退出码、输出或失败信息。",),
}

_DISCLAIMER_BY_STATUS: dict[ExecutionStatus, str] = {
    ExecutionStatus.PASS: (
        "这是代码复现卡，不是诊断结论。pass 只表示退出码 0 或提交的测试通过，"
        "不表示代码正确或完整。执行器是受限本地执行，不是容器级安全沙箱。"
    ),
    ExecutionStatus.FAIL: (
        "这是代码复现卡，不是诊断结论。这次运行没有通过；它只记录本次的退出码与"
        "首个失败，不表示已经找到根因。执行器是受限本地执行，不是容器级安全沙箱。"
    ),
    ExecutionStatus.TIMEOUT: (
        "这是代码复现卡，不是诊断结论。timeout 只表示这次执行没有在时限内结束，"
        "不表示代码正确或错误。执行器是受限本地执行，不是容器级安全沙箱。"
    ),
    ExecutionStatus.REJECTED: (
        "这是代码复现卡，不是诊断结论。rejected 表示代码被静态闸门拒绝、根本没有"
        "运行；这不是一次运行结果。执行器是受限本地执行，不是容器级安全沙箱。"
    ),
    ExecutionStatus.SKIPPED: (
        "这是代码复现卡，不是诊断结论。skipped 只表示这次没有运行，不表示代码"
        "正确或通过。执行器是受限本地执行，不是容器级安全沙箱。"
    ),
}

_NEXT_STEP_BY_STATUS: dict[ExecutionStatus, str] = {
    ExecutionStatus.PASS: (
        "补一个会失败的用例，或把输入缩到最小，确认这次运行真的覆盖了你要验证的行为。"
    ),
    ExecutionStatus.FAIL: "先把输入缩到最小，修好第一个失败，再重新提交同一段代码。",
    ExecutionStatus.TIMEOUT: "缩小输入或加日志，找出没有结束的那一步，再重新提交。",
    ExecutionStatus.REJECTED: "先移除被静态闸门拒绝的导入或调用，再重新提交。",
    ExecutionStatus.SKIPPED: (
        "需要复现时，先设置 SYNAPSE_EXEC=on 再重新提交这段代码；也可以先看工具轨迹里的结构线索。"
    ),
}


def build_skipped_execution_review(
    *,
    session_id: str,
    problem_id: str,
    domain_name: str,
    domain_label: str,
    tests_submitted: bool = False,
) -> GenericReview:
    """Record that the switch is off; nothing ran and nothing becomes a pass."""

    return _build(
        session_id=session_id,
        problem_id=problem_id,
        domain_name=domain_name,
        domain_label=domain_label,
        status=ExecutionStatus.SKIPPED,
        execution=ReviewExecution(status=ExecutionStatus.SKIPPED, tests_submitted=tests_submitted),
        first_failure=None,
        findings=(),
        evidence=(),
    )


def build_execution_review(
    *,
    session_id: str,
    problem_id: str,
    domain_name: str,
    domain_label: str,
    result: ExecutionResult,
    tests_submitted: bool,
) -> GenericReview:
    """Map one run result onto the published execution card."""

    status = ExecutionStatus(result.status)
    if status is ExecutionStatus.SKIPPED:
        raise ValueError(
            "a skipped execution has no run result; use build_skipped_execution_review"
        )

    first_failure = _first_failure(result) if status is ExecutionStatus.FAIL else None
    stdout_excerpt = _stdout_excerpt(result, status)
    execution = ReviewExecution(
        status=status,
        first_failure=first_failure,
        stdout_excerpt=stdout_excerpt,
        tests_submitted=tests_submitted,
    )
    evidence = _run_evidence(result, status)
    findings = _findings(status, result, first_failure, evidence.id)
    return _build(
        session_id=session_id,
        problem_id=problem_id,
        domain_name=domain_name,
        domain_label=domain_label,
        status=status,
        execution=execution,
        first_failure=first_failure,
        findings=findings,
        evidence=(evidence,),
    )


def _build(
    *,
    session_id: str,
    problem_id: str,
    domain_name: str,
    domain_label: str,
    status: ExecutionStatus,
    execution: ReviewExecution,
    first_failure: str | None,
    findings: tuple[GenericFinding, ...],
    evidence: tuple[GenericEvidence, ...],
) -> GenericReview:
    return GenericReview(
        session_id=session_id,
        problem_id=problem_id,
        kind=ReviewKind.EXECUTION,
        domain=ReviewDomain(
            name=_clip(domain_name, _MAX_DOMAIN),
            label=_clip(domain_label, _MAX_DOMAIN),
            verification=ReviewVerification.EXECUTABLE,
        ),
        headline=_headline(status, first_failure, execution.tests_submitted),
        findings=findings,
        evidence=evidence,
        not_checked=_not_checked(status),
        next_step=_clip(_NEXT_STEP_BY_STATUS[status], _MAX_NEXT_STEP),
        disclaimer=_clip(_DISCLAIMER_BY_STATUS[status], _MAX_DISCLAIMER),
        execution=execution,
    )


def _headline(
    status: ExecutionStatus,
    first_failure: str | None,
    tests_submitted: bool,
) -> str:
    if status is ExecutionStatus.PASS:
        passed = "提交的测试通过" if tests_submitted else "退出码 0"
        return _clip(f"这次运行通过：{passed}；这只说明这一次。", _MAX_HEADLINE)
    if status is ExecutionStatus.FAIL:
        detail = first_failure or "这次运行返回了非零退出码。"
        return _clip(f"这次运行没有通过：{detail}", _MAX_HEADLINE)
    if status is ExecutionStatus.TIMEOUT:
        return "这次运行超时：进程没有在时限内结束。"
    if status is ExecutionStatus.REJECTED:
        return "执行被拒绝：代码没有运行。"
    return _MESSAGE_SKIPPED


def _not_checked(status: ExecutionStatus) -> tuple[str, ...]:
    return (
        _clip(_NOT_CHECKED_CORRECTNESS, _MAX_NOT_CHECKED),
        *(_clip(item, _MAX_NOT_CHECKED) for item in _NOT_CHECKED_BY_STATUS[status]),
    )


def _findings(
    status: ExecutionStatus,
    result: ExecutionResult,
    first_failure: str | None,
    evidence_id: str,
) -> tuple[GenericFinding, ...]:
    if status is ExecutionStatus.PASS:
        return ()
    if status is ExecutionStatus.FAIL:
        kind, label = "test_failure", "首个失败"
        summary = first_failure or "这次运行没有通过，但没有拿到可读的失败信息。"
    elif status is ExecutionStatus.TIMEOUT:
        kind, label = "execution_timeout", "运行超时"
        summary = result.detail or "这次执行没有在时限内结束。"
    else:
        kind, label = "execution_rejected", "执行被拒绝"
        summary = _rejected_summary(result)
    return (
        GenericFinding(
            id="f1",
            kind=kind,
            label=label,
            severity=FindingSeverity.BLOCKING,
            summary=_clip(summary, _MAX_SUMMARY),
            evidence_refs=(evidence_id,),
        ),
    )


def _rejected_summary(result: ExecutionResult) -> str:
    if result.detail.strip():
        return result.detail
    messages = "；".join(item.message for item in result.findings)
    return messages or "执行器拒绝了这段代码，代码没有运行。"


def _run_evidence(result: ExecutionResult, status: ExecutionStatus) -> GenericEvidence:
    exit_code = "无" if result.exit_code is None else str(result.exit_code)
    excerpt = f"运行状态={status.value}；退出码={exit_code}；耗时={result.duration_ms}ms"
    if status is ExecutionStatus.REJECTED:
        excerpt = f"运行状态=rejected；代码没有运行；{result.detail}"
    return GenericEvidence(
        id="ev1",
        source=EvidenceSource.EXECUTION,
        ref=_RUN_REF,
        excerpt=_clip(excerpt, _MAX_EXCERPT),
    )


def _first_failure(result: ExecutionResult) -> str:
    """The first readable failure summary, falling back to the executor's detail.

    unittest prints the failing test's name first and the exception a few lines
    later; the card keeps both, because the header alone says *where* and the
    exception says *why*.
    """

    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _FAILURE_HEADER.match(line):
            exception = _next_exception(lines[index + 1 : index + 16])
            summary = line if exception is None else f"{line}：{exception}"
            return _clip(summary, _MAX_FAILURE)
    for line in lines:
        if _EXCEPTION_LINE.match(line):
            return _clip(line, _MAX_FAILURE)
    if result.detail.strip():
        return _clip(result.detail, _MAX_FAILURE)
    code = "" if result.exit_code is None else f"（退出码 {result.exit_code}）"
    return _clip(f"这次运行没有通过{code}，但没有输出可读的失败信息。", _MAX_FAILURE)


def _next_exception(lines: list[str]) -> str | None:
    for line in lines:
        if _FAILURE_HEADER.match(line):
            return None
        if _EXCEPTION_LINE.match(line):
            return line
    return None


def _stdout_excerpt(result: ExecutionResult, status: ExecutionStatus) -> str | None:
    # ``rejected`` never ran, so it has no stdout to quote. The domain model
    # rejects that pairing as well.
    if status is ExecutionStatus.REJECTED:
        return None
    text = result.stdout.strip()
    return _clip(text, _MAX_STDOUT) if text else None


def _clip(text: str, limit: int) -> str:
    """Collapse whitespace and fit the published schema's maxLength."""

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"
