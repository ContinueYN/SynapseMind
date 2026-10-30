"""M2.5 S4 exit report: build a solution graph for 20 unseen problems.

    cd apps/api
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s4_graph_build.py

The bar is chapter 13 §13.7 S4: at least 80% of unseen problems must yield a
graph that passes every structural rule and the published JSON schema. The
report also keeps the failing attempts, the mechanical repairs, latency and
token use, so a regression is visible rather than felt.

Only *mechanical* validity is judged here. Whether a valid graph actually
decomposes the problem correctly is a human review; the script writes each
graph to ``eval/reports/s4-graphs/`` for that pass and never claims it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from synapse.application.graph import GraphBuildFailed, GraphBuildResult  # noqa: E402
from synapse.domain.problem.models import ProblemDraft, SolutionGraph  # noqa: E402
from synapse.infrastructure.llm.audit import InMemoryCallAuditor  # noqa: E402
from synapse.infrastructure.llm.client import OpenAICompatibleClient  # noqa: E402
from synapse.infrastructure.llm.graph import LLMGraphGenerator, to_payload  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402

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
        default=str(ROOT / "eval" / "reports" / "m2.5-s4-graph-build.md"),
    )
    parser.add_argument(
        "--graphs-dir",
        default=str(ROOT / "eval" / "reports" / "s4-graphs"),
    )
    parser.add_argument("--limit", type=int, default=0, help="only the first N problems")
    args = parser.parse_args()

    load_dotenv()
    settings = LLMSettings.from_env()
    if not settings.api_key:
        print("! 需要 DEEPSEEK_API_KEY（仓库根 .env 或环境变量）")
        return 2
    if settings.mode == "off":
        # Graph building is not a served path yet; this harness is the only
        # caller, so an explicit key is enough to opt into live generation.
        settings = replace(settings, mode="on")

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
    generator = LLMGraphGenerator(client, settings=settings, auditor=auditor)

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
                print(f"FAIL {case.draft.id} {exc.reason}: {exc.detail[:120]}")
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
            print(
                f"PASS {case.draft.id} nodes={len(result.graph.nodes)} "
                f"edges={len(result.graph.edges)} probes={len(result.graph.probes())} "
                f"attempts={result.attempts} repairs={','.join(result.repairs) or '-'}"
            )
    finally:
        client.close()

    total_ms = int((time.perf_counter() - started) * 1000)
    passed = sum(1 for row in rows if row.ok)
    rate = passed / len(rows)
    report = _render(
        rows=rows,
        passed=passed,
        rate=rate,
        total_ms=total_ms,
        settings=settings,
        dataset=Path(args.problems),
        entries=auditor.entries,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"report: {out}")
    print(f"graphs: {graphs_dir}")
    return 0 if rate >= PASS_BAR else 1


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
    payload = {
        "id": case.draft.id,
        "topic": case.topic,
        "attempts": result.attempts,
        "repairs": list(result.repairs),
        "notes": list(result.notes),
        "fingerprint": result.fingerprint,
        "graph": to_payload(result.graph),
    }
    path = directory / f"{case.draft.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _evidence_coverage(graph: SolutionGraph) -> str:
    probes = graph.probes()
    weighted = sum(len(probe.evidence) for probe in probes)
    options = sum(len(probe.options) for probe in probes)
    return f"{weighted}/{options}"


def _has_contrast(evidence: Mapping[str, Mapping[str, float]]) -> bool:
    weights = [weight for option in evidence.values() for weight in option.values()]
    return any(weight > 0 for weight in weights) and any(weight < 0 for weight in weights)


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(ratio * len(ordered)) - 1)]


def _render(
    *,
    rows: list[Row],
    passed: int,
    rate: float,
    total_ms: int,
    settings: LLMSettings,
    dataset: Path,
    entries: tuple[Any, ...],
) -> str:
    latencies = [int(entry.latency_ms) for entry in entries if int(entry.latency_ms) > 0]
    prompt_tokens = sum(int(entry.prompt_tokens) for entry in entries)
    completion_tokens = sum(int(entry.completion_tokens) for entry in entries)
    retried = sum(1 for entry in entries if entry.retried)
    repairs = Counter(code for row in rows if row.ok and row.result for code in row.result.repairs)
    node_counts = [len(row.result.graph.nodes) for row in rows if row.result]
    edge_counts = [len(row.result.graph.edges) for row in rows if row.result]
    probe_counts = [len(row.result.graph.probes()) for row in rows if row.result]
    probes = [probe for row in rows if row.result for probe in row.result.graph.probes()]
    weighted_options = sum(len(probe.evidence) for probe in probes)
    covered_probes = sum(1 for probe in probes if len(probe.evidence) == len(probe.options))
    contrast_probes = sum(1 for probe in probes if _has_contrast(probe.evidence))

    lines = [
        f"# M2.5 S4 建图报告（{len(rows)} 道未见题）",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}`",
        f"- 数据集：`{_relative(dataset)}`（{len(rows)} 题）",
        f"- 建图成功：{passed}/{len(rows)}（{rate:.0%}，门槛 ≥{PASS_BAR:.0%}）",
        f"- 总耗时：{total_ms / 1000:.1f}s；单题平均 {total_ms / len(rows) / 1000:.1f}s",
        f"- 模型调用：{len(entries)} 次，重试 {retried} 次",
        f"- 延迟：p50 {_percentile(latencies, 0.50)} ms，p95 {_percentile(latencies, 0.95)} ms",
        f"- Token：prompt {prompt_tokens} / completion {completion_tokens}",
        f"- 证据：{covered_probes}/{len(probes)} 个探针的每个选项都有权重"
        f"（共 {weighted_options} 个选项权重）；"
        f"{contrast_probes}/{len(probes)} 个探针的权重有正有负",
        "",
        "> “成功”只代表**结构合法 + 证据完整**：schema、无环、依赖连通、探针可区分两个假设、"
        "每个选项都有非零权重。图是否真的拆对了题、权重方向是否合理，见同目录的人工抽查记录 "
        "`m2.5-s4-graph-review.md`；抽查不通过的题按 S4 口径不计入成功率。",
        "",
        "| 题号 | 主题 | 结果 | 尝试 | 节点 | 边 | 探针 | 证据选项 | 自动修复 | 耗时(ms) | 指纹 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for row in rows:
        if row.ok and row.result:
            lines.append(
                "| {id} | {topic} | PASS | {attempts} | {nodes} | {edges} | {probes} | "
                "{evidence} | {repairs} | {elapsed} | `{fingerprint}` |".format(
                    id=row.case.draft.id,
                    topic=row.case.topic or "-",
                    attempts=row.attempts,
                    nodes=len(row.result.graph.nodes),
                    edges=len(row.result.graph.edges),
                    probes=len(row.result.graph.probes()),
                    evidence=_evidence_coverage(row.result.graph),
                    repairs="、".join(row.result.repairs) or "-",
                    elapsed=row.elapsed_ms,
                    fingerprint=row.result.fingerprint,
                )
            )
        else:
            lines.append(
                f"| {row.case.draft.id} | {row.case.topic or '-'} | FAIL（{row.reason}） | "
                f"{row.attempts} | - | - | - | - | - | {row.elapsed_ms} | - |"
            )

    lines += ["", "## 规模与修复", ""]
    if node_counts:
        lines.append(
            f"- 节点数：平均 {sum(node_counts) / len(node_counts):.1f}，"
            f"范围 {min(node_counts)}–{max(node_counts)}"
        )
        lines.append(
            f"- 边数：平均 {sum(edge_counts) / len(edge_counts):.1f}；"
            f"探针数：平均 {sum(probe_counts) / len(probe_counts):.1f}"
        )
    if repairs:
        lines.append(
            "- 自动修复：" + "、".join(f"`{code}`×{count}" for code, count in repairs.most_common())
        )
    else:
        lines.append("- 自动修复：无")

    failures = [row for row in rows if not row.ok]
    if failures:
        lines += ["", "## 失败明细", ""]
        for row in failures:
            lines.append(
                f"- `{row.case.draft.id}`（{row.reason}，{row.attempts} 次调用）：{row.detail}"
            )

    lines += [
        "",
        "## 口径与已知边界",
        "",
        "- 判定见 `apps/api/src/synapse/domain/problem/graph_structure.py` 与 "
        "`specs/solution-graph.schema.json`；修复只做机械动作（重编号、删悬空边、断环、截断），"
        "不改写步骤含义。",
        "- 每个探针必须指向 `H_L1`/`H_L2`/`H_L4` 中至少两个，且每个选项都带 log-odds 权重："
        "诊断层仍是 M1 的三个假设（S5 只把权重来源换成生成图，假设体系没有扩）。"
        "权重方向是否合理需要人工抽查，结构规则只能保证“每个选项都会更新后验、只更新 targets 里的假设、同一探针有正有负”。",
        "- 生成结果按 `(题目 id, 文本, 模型, prompt 版本)` 缓存在进程内；同一进程重跑不重复计费。",
        f"- {len(rows)} 条题只用于验收，不按单题调 prompt；若某类题系统性失败，只改 prompt 的通用规则，"
        "并在报告里记录 prompt 版本变化。",
        "- 人工抽查由开发代理执行，不等同于教师复核；正式对外前仍需教师抽样。",
        "",
    ]
    return "\n".join(lines)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
