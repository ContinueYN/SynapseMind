"""M2 on:10 gate: measure the *first question* end to end.

``m2_exit.py`` measures a single probe rewrite against the annotated seed. It
does not include graph building, alignment, or probe planning. This script
measures what a student actually waits for on submit: one ``SessionService.start``
call, including an on-demand graph build for unseen stems.

Usage::

    python scripts/eval/m2_first_question.py
    python scripts/eval/m2_first_question.py --limit 5 --budget-ms 8000

The gate passes only when every submitted stem starts a session and the p95 is
inside the budget. A failed start is not counted as a fast sample.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from synapse.api.deps import build_container  # noqa: E402
from synapse.application.commands import StartSessionCommand  # noqa: E402
from synapse.application.errors import ProblemNotSupported  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402

DEFAULT_BUDGET_MS = 8000
SAMPLE_WORK = {
    "math": "先确认题目的条件，再按参数分类讨论。",
    "physics": "先读题，标出已知量和单位，再选择物理模型。",
    "chinese": "先读题干，再回原文找依据。",
}


@dataclass(frozen=True, slots=True)
class Case:
    text: str
    topic: str
    subject: str = "math"


@dataclass
class Row:
    case: Case
    created: bool = False
    elapsed_ms: int = 0
    problem_id: str = ""
    annotated: bool = False
    has_prompt: bool = False
    state: str = ""
    detail: str = ""


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"{path}:{line_number}: 每一行必须是 JSON 对象")
        cases.append(
            Case(
                text=str(payload["text"]),
                topic=str(payload.get("topic", "")),
                subject=str(payload.get("subject", "math")),
            )
        )
    return cases


def run_case(container: Any, case: Case) -> Row:
    started = time.perf_counter()
    row = Row(case=case)
    try:
        view = container.service.start(
            StartSessionCommand(
                problem_text=case.text,
                answer="",
                work=SAMPLE_WORK.get(case.subject, SAMPLE_WORK["math"]),
                subject=case.subject,
            )
        )
    except ProblemNotSupported as exc:
        row.elapsed_ms = int((time.perf_counter() - started) * 1000)
        row.detail = str(exc)
        return row
    except Exception as exc:  # noqa: BLE001 - the report needs the failure, not a traceback
        row.elapsed_ms = int((time.perf_counter() - started) * 1000)
        row.detail = f"{type(exc).__name__}: {exc}"
        return row

    row.elapsed_ms = int((time.perf_counter() - started) * 1000)
    row.created = True
    row.problem_id = view.session.problem_id
    problem = container.problems.get(row.problem_id)
    row.annotated = bool(problem and problem.annotated)
    row.has_prompt = view.prompt is not None
    row.state = str(getattr(view.session.state, "value", view.session.state))
    return row


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(
    rows: list[Row],
    *,
    budget_ms: int,
    mode: str,
    p50: int,
    p95: int,
    worst: int,
    passed: bool,
) -> str:
    created = sum(1 for row in rows if row.created)
    with_prompt = sum(1 for row in rows if row.has_prompt)
    generated = sum(1 for row in rows if row.created and not row.annotated)
    verdict = "PASS" if passed else "FAIL"

    lines = [
        "# M2 首问整体延迟门禁",
        "",
        f"- 结论：**{verdict}**（预算 {budget_ms} ms，p95 实测 {p95} ms）",
        f"- 样本：{len(rows)} 道题；建会话 {created}/{len(rows)}；"
        f"拿到首问 {with_prompt}/{len(rows)}；其中现场建图 {generated} 道",
        f"- 延迟：p50 **{p50} ms**、p95 **{p95} ms**、最慢 **{worst} ms**",
        f"- 模式：`{mode}`（真实模型；只测 `SessionService.start()`，不含前端网络与渲染）",
        "",
        "口径：一次 POST 交题到拿到第一问的总耗时，包含现场建图、对齐、"
        "探针规划。预算取 8s；建会话失败不计入延迟样本，但直接判失败。",
        "",
        "| # | problem_id | 类型 | 首问 | 状态 | ms | 备注 |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        kind = "标注" if row.annotated else ("生成" if row.created else "-")
        prompt = "有" if row.has_prompt else "-"
        state = row.state or "-"
        lines.append(
            f"| {index} | `{cell(row.problem_id) or '-'}` | {kind} | {prompt} | "
            f"`{cell(state)}` | {row.elapsed_ms} | {cell(row.detail) or '-'} |"
        )

    lines += [
        "",
        "## 怎么读",
        "",
        "- `建会话`失败会先被计为失败，即使失败得很快；门禁不允许用 422 换低延迟。",
        "- 现场建图路径包含一次模型调用（失败会按设计重试一次），"
        "所以尾延迟比标注种子题高；这正是 `on:10` 前要单独看的一支。",
        "- 这是服务端耗时，不含浏览器到 API 的网络、首屏渲染与前端 JS。"
        "对外承诺的 8s 首问还需要在前端侧另测一次。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "unseen-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2-first-question.md"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    args = parser.parse_args()

    load_dotenv()
    settings = LLMSettings.from_env()
    if not settings.api_key:
        print("! 需要 DEEPSEEK_API_KEY（仓库根 .env 或环境变量）")
        return 2
    if settings.mode == "off":
        settings = replace(settings, mode="on")

    cases = load_cases(Path(args.problems))
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("! 评测集为空")
        return 2

    container = build_container(settings)
    rows: list[Row] = []
    for case in cases:
        row = run_case(container, case)
        rows.append(row)
        status = "OK  " if row.created else "FAIL"
        print(f"{status} {row.elapsed_ms:5d}ms {row.problem_id or '-'} {row.detail}".rstrip())

    latencies = [row.elapsed_ms for row in rows if row.created]
    p50 = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)
    worst = max(latencies) if latencies else 0
    passed = len(latencies) == len(rows) and p95 <= args.budget_ms

    report = render(
        rows,
        budget_ms=args.budget_ms,
        mode=settings.mode,
        p50=p50,
        p95=p95,
        worst=worst,
        passed=passed,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\n首问 p50 {p50}ms / p95 {p95}ms / max {worst}ms，预算 {args.budget_ms}ms")
    print(f"门禁：{'PASS' if passed else 'FAIL'}；报告：{out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
