"""M2.5 S5 exit report: does a generated graph survive its own answer check?

    cd apps/api
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_verify.py

S4 measured structure. S5 adds the only thing that can catch a wrong *answer*:
the graph must state its answer as a machine-checkable claim, and the SymPy
verifier tries to refute it. This harness runs the 20 unseen problems through
the whole build (generate -> repair -> structure -> schema -> verify -> one
retry) and reports, per problem:

- whether the model produced a claim at all (coverage, not a gate);
- ``pass`` / ``fail`` / ``unknown`` and the counterexample when there is one;
- how many calls the verdict cost.

It also runs two *deliberately wrong* mutations of every claim the verifier
accepted (answer = the whole line; answer widened by one unit). A verifier that
accepts those is not checking anything, so the self-test is part of the report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from synapse.application.graph import GraphBuildFailed, GraphBuildResult  # noqa: E402
from synapse.application.verification import describe_claim  # noqa: E402
from synapse.domain.problem.models import (  # noqa: E402
    Interval,
    ProblemDraft,
    SolutionGraph,
    VerificationClaim,
)
from synapse.infrastructure.llm.audit import InMemoryCallAuditor  # noqa: E402
from synapse.infrastructure.llm.client import OpenAICompatibleClient  # noqa: E402
from synapse.infrastructure.llm.graph import (  # noqa: E402
    LLMGraphGenerator,
    to_payload,
)
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402
from synapse.infrastructure.seed import SAMPLE_PROBLEM  # noqa: E402
from synapse.infrastructure.verification.sympy_verifier import SymPyVerifier  # noqa: E402

PASS_BAR = 0.80


@dataclass(frozen=True, slots=True)
class Case:
    draft: ProblemDraft
    topic: str


@dataclass
class Row:
    case: Case
    ok: bool
    elapsed_ms: int
    attempts: int = 0
    result: GraphBuildResult | None = None
    reason: str = ""
    detail: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "unseen-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s5-verification.md"),
    )
    parser.add_argument(
        "--graphs-dir",
        default=str(ROOT / "eval" / "reports" / "s5-graphs"),
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    load_dotenv()
    settings = LLMSettings.from_env()
    if not settings.api_key:
        print("! 需要 DEEPSEEK_API_KEY（仓库根 .env 或环境变量）")
        return 2
    if settings.mode == "off":
        settings = replace(settings, mode="on")

    verifier = SymPyVerifier()
    cases = load_cases(Path(args.problems))
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("! 评测集为空")
        return 2

    graphs_dir = Path(args.graphs_dir)
    graphs_dir.mkdir(parents=True, exist_ok=True)
    auditor = InMemoryCallAuditor()
    client = OpenAICompatibleClient(settings)
    generator = LLMGraphGenerator(
        client,
        settings=settings,
        auditor=auditor,
        verifier=verifier,
    )

    seed_verdict = verifier.verify(SAMPLE_PROBLEM.graph)

    started = time.perf_counter()
    rows: list[Row] = []
    try:
        for case in cases:
            row_started = time.perf_counter()
            try:
                result = generator.generate(case.draft)
            except GraphBuildFailed as exc:
                rows.append(
                    Row(
                        case=case,
                        ok=False,
                        elapsed_ms=int((time.perf_counter() - row_started) * 1000),
                        attempts=exc.attempts,
                        reason=exc.reason,
                        detail=exc.detail,
                    )
                )
                print(f"FAIL {case.draft.id} {exc.reason}: {exc.detail[:160]}")
                continue
            rows.append(
                Row(
                    case=case,
                    ok=True,
                    elapsed_ms=int((time.perf_counter() - row_started) * 1000),
                    attempts=result.attempts,
                    result=result,
                )
            )
            _write_graph(graphs_dir, case, result)
            status = result.verification.status if result.verification else "-"
            claim = "claim" if result.graph.claim is not None else "no-claim"
            print(
                f"PASS {case.draft.id} attempts={result.attempts} {claim} "
                f"verify={status} nodes={len(result.graph.nodes)} "
                f"probes={len(result.graph.probes())}"
            )
    finally:
        client.close()

    total_ms = int((time.perf_counter() - started) * 1000)
    mutations, mutation_source = _mutation_self_test(rows, verifier)
    report = _render(
        rows=rows,
        total_ms=total_ms,
        settings=settings,
        dataset=Path(args.problems),
        entries=auditor.entries,
        seed_verdict=seed_verdict,
        mutations=mutations,
        mutation_source=mutation_source,
        control=_positive_control(verifier),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"report: {out}")
    print(f"graphs: {graphs_dir}")

    built = sum(1 for row in rows if row.ok)
    return 0 if built / len(rows) >= PASS_BAR else 1


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: 每一行必须是 JSON 对象")
        cases.append(
            Case(
                draft=ProblemDraft(
                    id=str(payload["id"]),
                    text=str(payload["text"]),
                    subject=str(payload.get("subject", "math")),
                    grade=str(payload.get("grade", "high_school")),
                ),
                topic=str(payload.get("topic", "")),
            )
        )
    return cases


def _write_graph(directory: Path, case: Case, result: GraphBuildResult) -> None:
    verification = result.verification
    payload = {
        "id": case.draft.id,
        "topic": case.topic,
        "attempts": result.attempts,
        "repairs": list(result.repairs),
        "notes": list(result.notes),
        "fingerprint": result.fingerprint,
        "verification": {
            "status": verification.status if verification else "",
            "reason": verification.reason if verification else "",
            "detail": verification.detail if verification else "",
            "parameter_samples": verification.parameter_samples if verification else 0,
            "point_checks": verification.point_checks if verification else 0,
        },
        "graph": to_payload(result.graph),
    }
    path = directory / f"{case.draft.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --- self-test --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mutation:
    case_id: str
    label: str
    caught: bool
    detail: str


def _mutation_self_test(rows: list[Row], verifier: SymPyVerifier) -> tuple[list[Mutation], str]:
    """Two deliberately wrong answers per claim; both must be rejected.

    When no generated claim survived verification the seed graph stands in, so
    the self-test always has a target: a verifier that cannot reject an
    obviously wrong answer is not checking anything.
    """
    targets: list[tuple[str, SolutionGraph]] = [
        (row.case.draft.id, row.result.graph)
        for row in rows
        if row.ok and row.result is not None and row.result.graph.claim is not None
    ]
    source = "生成图"
    if not targets:
        targets = [(SAMPLE_PROBLEM.id, SAMPLE_PROBLEM.graph)]
        source = "种子图（本批次没有通过验证的生成图）"

    mutations: list[Mutation] = []
    for case_id, graph in targets:
        claim = graph.claim
        assert claim is not None
        whole_line = replace(claim, intervals=(Interval(lower=None, upper=None),))
        mutations.append(_probe(verifier, graph, case_id, "答案写成全实轴", whole_line))

        widened = _widen(claim)
        if widened is not None:
            mutations.append(_probe(verifier, graph, case_id, "区间端点放宽 1", widened))
    return mutations, source


def _positive_control(verifier: SymPyVerifier) -> list[Mutation]:
    """Same problem, two answers one interval apart; the verdict must flip."""
    truth = VerificationClaim(
        kind="parameter_range",
        parameter="a",
        variable="x",
        variable_domain="(-inf,+inf)",
        expression="exp(x) - a*x",
        relation=">=",
        intervals=(Interval(lower="0", upper="E", lower_inclusive=True, upper_inclusive=True),),
    )
    wrong = replace(
        truth,
        intervals=(Interval(lower=None, upper="E", lower_inclusive=False, upper_inclusive=True),),
    )
    graph = replace(SAMPLE_PROBLEM.graph, claim=truth)
    accepted = verifier.verify(graph)
    rejected = verifier.verify(replace(graph, claim=wrong))
    return [
        Mutation(
            case_id="P_DERIV_003",
            label="正确答案 [0,E]",
            caught=accepted.status != "fail",
            detail=f"{accepted.status}/{accepted.reason}，没找到反例"
            if accepted.ok
            else accepted.detail,
        ),
        Mutation(
            case_id="P_DERIV_003",
            label="模型答案 (-∞,E]",
            caught=rejected.status == "fail",
            detail=rejected.detail if rejected.status == "fail" else "未被拒绝",
        ),
    ]


def _probe(
    verifier: SymPyVerifier,
    graph: SolutionGraph,
    case_id: str,
    label: str,
    mutated: VerificationClaim,
) -> Mutation:
    result = verifier.verify(replace(graph, claim=mutated))
    caught = result.status == "fail"
    detail = result.detail if caught else f"未被拒绝：{result.status}/{result.reason}"
    return Mutation(case_id=case_id, label=label, caught=caught, detail=detail)


def _widen(claim: VerificationClaim) -> VerificationClaim | None:
    intervals = list(claim.intervals)
    first, last = intervals[0], intervals[-1]
    if last.upper is not None:
        intervals[-1] = replace(last, upper=f"({last.upper})+1")
    elif first.lower is not None:
        intervals[0] = replace(first, lower=f"({first.lower})-1")
    else:
        return None
    return replace(claim, intervals=tuple(intervals))


# --- report -----------------------------------------------------------------


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(ratio * len(ordered)) - 1)]


def _render(
    *,
    rows: list[Row],
    total_ms: int,
    settings: LLMSettings,
    dataset: Path,
    entries: tuple[Any, ...],
    seed_verdict: Any,
    mutations: list[Mutation],
    mutation_source: str,
    control: list[Mutation],
) -> str:
    built = [row for row in rows if row.ok and row.result is not None]
    latencies = [entry.latency_ms for entry in entries if entry.latency_ms > 0]
    retried = sum(1 for entry in entries if entry.retried)
    tokens_in = sum(entry.prompt_tokens for entry in entries)
    tokens_out = sum(entry.completion_tokens for entry in entries)

    claims = [row.result.graph.claim for row in built if row.result and row.result.graph.claim]
    statuses = Counter(
        row.result.verification.status if row.result and row.result.verification else "-"
        for row in built
    )
    refuted = [row for row in built if row.result and "claim_dropped_refuted" in row.result.repairs]
    dropped = [
        row.case.draft.id
        for row in built
        if row.result is not None and "claim_dropped_unsupported" in row.result.repairs
    ]
    repaired = [
        (row.case.draft.id, ", ".join(row.result.repairs))
        for row in built
        if row.result is not None and row.result.repairs
    ]

    lines = [
        "# M2.5 S5 验证报告（20 道未见题）",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}`",
        f"- 数据集：`{_relative(dataset)}`（{len(rows)} 题）",
        f"- 建图成功：{len(built)}/{len(rows)}"
        f"（{len(built) / len(rows):.0%}，门槛 ≥{PASS_BAR:.0%}）",
        f"- claim：被接受 {len(claims)} 题；被反例推翻 {len(refuted)} 题"
        + (f"（{', '.join(row.case.draft.id for row in refuted)}）" if refuted else "")
        + f"；形状不支持丢弃 {len(dropped)} 题"
        + (f"（{', '.join(dropped)}）" if dropped else "")
        + f"；其余 {len(built) - len(claims) - len(refuted) - len(dropped)} 题没有 claim",
        f"- 验证结论：pass {statuses.get('pass', 0)} / fail {statuses.get('fail', 0)} / "
        f"unknown {statuses.get('unknown', 0)}",
        f"- 总耗时：{total_ms / 1000:.1f}s；单题平均 {total_ms / len(rows) / 1000:.1f}s",
        f"- 模型调用：{len(entries)} 次，重试 {retried} 次；"
        f"Token：prompt {tokens_in} / completion {tokens_out}",
        f"- 延迟：p50 {_percentile(latencies, 0.50)} ms，p95 {_percentile(latencies, 0.95)} ms",
        f"- 种子图 claim 自检：`{seed_verdict.status}`（{seed_verdict.reason}）",
        "",
        "> “pass”是**反例搜索的通过**，不是证明：固定网格 + 黄金分割细化在定义域上找违反约束的 x、",
        "> 以及答案区间外满足约束的参数值。找不到反例记 `pass`，找不到结论记 `unknown`；",
        "> `fail` 一定带具体反例，会作为反馈让模型重试一次，仍失败则**丢弃 claim**（图保留，",
        "> 答案不再被当作已核对），反例留在结果里。",
        "",
        "| 题号 | 主题 | 建图 | 尝试 | claim | 验证 | 参数样本 | 取值 | 耗时(ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for row in rows:
        if row.ok and row.result:
            verification = row.result.verification
            if "claim_dropped_refuted" in row.result.repairs:
                claim = "推翻"
            elif row.result.graph.claim is not None:
                claim = "有"
            else:
                claim = "无"
            status = verification.status if verification else "-"
            samples = verification.parameter_samples if verification else 0
            checks = verification.point_checks if verification else 0
            lines.append(
                f"| {row.case.draft.id} | {row.case.topic or '-'} | PASS | {row.attempts} | "
                f"{claim} | {status} | {samples} | {checks} | {row.elapsed_ms} |"
            )
        else:
            lines.append(
                f"| {row.case.draft.id} | {row.case.topic or '-'} | FAIL（{row.reason}） | "
                f"{row.attempts} | - | - | - | - | {row.elapsed_ms} |"
            )

    if repaired:
        lines += ["", "机械修复（不改写步骤含义，全部记录）：", ""]
        for case_id, codes in repaired:
            lines.append(f"- `{case_id}`：{codes}")

    lines += ["", "## claim 与验证明细", ""]
    if not claims:
        lines.append("- 没有 claim 通过验证。")
    for row in built:
        if row.result is None or row.result.graph.claim is None:
            continue
        assert row.result.verification is not None
        lines += [
            f"### `{row.case.draft.id}`",
            "",
            f"- 声明：`{describe_claim(row.result.graph.claim)}`",
            f"- 结果：`{row.result.verification.status}`（{row.result.verification.reason}）"
            f" — {row.result.verification.detail}",
        ]
        counter = row.result.verification.counterexample
        if counter is not None:
            witness = ""
            if counter.variable_value:
                witness = f"，{counter.variable}={counter.variable_value}"
            lines.append(f"- 反例：{counter.parameter}={counter.parameter_value}{witness}")
        lines.append("")

    if refuted:
        lines += ["## 被反例推翻的 claim（图保留，答案不再认证）", ""]
        for row in refuted:
            assert row.result is not None and row.result.verification is not None
            lines.append(
                f"- `{row.case.draft.id}`（{row.attempts} 次调用）："
                f"{row.result.verification.detail}"
            )
        lines.append("")

    lines += ["## 变形自检（验证器本身会不会放水）", ""]
    if mutations:
        caught = sum(1 for mutation in mutations if mutation.caught)
        lines.append(
            f"对 {mutation_source} 的 claim 做两个**必然错误**的变形"
            f"（答案写成全实轴、端点放宽 1），验证器拒绝 {caught}/{len(mutations)}。"
        )
        lines.append("")
        lines.append("| 题号 | 变形 | 是否拒绝 | 说明 |")
        lines.append("|---|---|---|---|")
        for mutation in mutations:
            lines.append(
                f"| {mutation.case_id} | {mutation.label} | "
                f"{'是' if mutation.caught else '**否**'} | {_escape(mutation.detail)[:120]} |"
            )
    else:
        lines.append("- 没有可用的 claim，无法做变形自检。")

    if control:
        lines += ["", "## 正向对照（同一题，只差一个区间）", ""]
        lines.append("| 题号 | 答案 | 结果 | 说明 |")
        lines.append("|---|---|---|---|")
        for item in control:
            lines.append(
                f"| {item.case_id} | {item.label} | {_escape(item.detail)[:60]} | "
                f"{'符合预期' if item.caught else '**不符合预期**'} |"
            )

    lines += [
        "",
        "## 口径与已知边界",
        "",
        "- claim 只覆盖“对所有 x∈D 有 f(x,a) rel 0 ⇒ a∈区间”这一种形状。求一个值、求方程/不等式",
        "  的解集、证明题没有 claim（`unknown`/`no_claim`），**不视为失败**，也不算已验证。",
        "  覆盖率是观测指标，不是门槛：这 20 题里只有 `P_DERIV_003` 属于该形状。",
        "- 验证是反例搜索：定义域上固定网格（线性 + 十二个数量级 + 边界加密）加黄金分割细化，",
        "  参数内点/外点各取样最多 24 个。找不到反例 → `pass`；",
        "  无定义或落在 1e-9 容差带 → `unknown`。",
        "  这能给出具体反例，但不能证明命题为真；正式对外前仍需教师抽样。",
        "- 表达式解析有字符白名单、`__builtins__` 置空的 SymPy 命名空间和自由符号检查；",
        "  未知符号、区间倒置/重叠、无穷一端写成闭区间都会判 `malformed` 并让模型重试一次。",
        "- 验证失败会带着反例重试一次（`max_attempts`）；仍失败则**丢弃 claim**",
        "  （`claim_dropped_refuted`），图保留、答案不再被当作已核对，",
        "  反例留在 `GraphBuildResult.verification` 里。",
        "  S4 里 `P_DERIV_003` 漏 `a=0` 那种错误现在会被反例点名，而不是悄悄发到学生面前。",
        "- claim 的 kind/relation/符号冲突属于“形状不支持”，直接丢弃",
        "  （`claim_dropped_unsupported`），不浪费一次重试；只有能读懂但读不通的 claim",
        "  （表达式解析失败、端点为空）才判 `fail` 重试。",
        "",
    ]
    return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
