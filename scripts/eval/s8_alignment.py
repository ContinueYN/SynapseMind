"""M2.5 S8: clause-level alignment, measured against the old aligner per graph.

S7 measured the gap and left it open: a Chinese node is one long multi-clause
sentence, and the whole-node 3-gram backstop called a student who wrote only the
first action ``missing``. S8 adds ``ClauseCueAligner`` plus a plugin port so the
NONE tier opts in without moving math/physics.

This report is deliberately **not** "语文诊断更准了" — it cannot be, because
there is no verifiable truth for 语文. It checks four things:

* the service reaches the clause aligner through ``SubjectPlugin.aligner_for``
  (the hint statuses equal a direct ``ClauseCueAligner`` call on the same graph);
* on the *same* generated graph, the new aligner turns "only the first clause"
  into ``partial`` instead of ``missing``;
* a blank process does not become covered or partial (the false-positive guard);
* the NONE contract still holds: schema v0.2, zero probes, zero cards, CLOSED.

Comparing both aligners on the same graph is the whole point: a fresh graph per
run would confound alignment with graph-generation variance.

Usage::

    python scripts/eval/s8_alignment.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from jsonschema import Draft202012Validator  # noqa: E402
from s5_session import PASS_BAR, cell, pct  # noqa: E402
from s7_none_tier import (  # noqa: E402
    ANSWER,
    Case,
    _validator,
    load_cases,
    run_case,
)

from synapse.api.deps import build_container  # noqa: E402
from synapse.domain.problem.alignment import ClauseCueAligner, TypeCueAligner  # noqa: E402
from synapse.domain.problem.models import AlignmentResult, Problem, StudentAttempt  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402

VARIANTS = ("partial", "full", "blank")


@dataclass(frozen=True)
class Compare:
    case: Case
    variant: str
    problem_id: str
    steps: int
    old_covered: int
    old_missing: int
    new_covered: int
    new_partial: int
    new_missing: int
    focus: str
    one_line: str
    service_matches: bool
    spec_ok: bool
    closed: bool = False
    detail: str = ""
    hint_json: dict[str, Any] | None = None

    @property
    def old_weighted(self) -> float:
        # The old aligner has no middle state, so a half-written step scores 0.
        return float(self.old_covered)

    @property
    def new_weighted(self) -> float:
        return self.new_covered + 0.5 * self.new_partial


def _statuses(alignment: AlignmentResult) -> dict[str, str]:
    result: dict[str, str] = {}
    result.update({node_id: "covered" for node_id in alignment.matched_node_ids})
    result.update({node_id: "partial" for node_id in alignment.partial_node_ids})
    result.update({node_id: "missing" for node_id in alignment.missing_node_ids})
    return result


def _counts(alignment: AlignmentResult) -> tuple[int, int, int]:
    return (
        len(alignment.matched_node_ids),
        len(alignment.partial_node_ids),
        len(alignment.missing_node_ids),
    )


def compare_case(
    container: Any,
    case: Case,
    validator: Draft202012Validator,
    variant: str,
) -> Compare:
    row = run_case(container, case, validator, variant)
    base = Compare(
        case=case,
        variant=variant,
        problem_id=row.problem_id,
        steps=row.steps,
        old_covered=0,
        old_missing=0,
        new_covered=0,
        new_partial=0,
        new_missing=0,
        focus=row.focus,
        one_line=str((row.hint_json or {}).get("one_line", "")),
        service_matches=False,
        spec_ok=row.spec_ok,
        closed=row.state == "CLOSED",
        detail=row.detail,
        hint_json=row.hint_json,
    )
    if not row.created or row.hint_json is None:
        return base

    problem: Problem | None = container.problems.get(row.problem_id)
    if problem is None:
        return Compare(**{**base.__dict__, "detail": "图不在仓储里"})

    attempt = StudentAttempt(answer=ANSWER, work=case.work_for(variant))
    old = TypeCueAligner().align(problem, attempt)
    new = ClauseCueAligner().align(problem, attempt)
    old_covered, _, old_missing = _counts(old)
    new_covered, new_partial, new_missing = _counts(new)
    service_map = {str(step["node_id"]): str(step["status"]) for step in row.hint_json["steps"]}
    service_matches = service_map == _statuses(new)
    detail = row.detail
    if not service_matches:
        detail = "服务返回的 hint 与直接调用 ClauseCueAligner 不一致"

    return Compare(
        case=case,
        variant=variant,
        problem_id=row.problem_id,
        steps=row.steps,
        old_covered=old_covered,
        old_missing=old_missing,
        new_covered=new_covered,
        new_partial=new_partial,
        new_missing=new_missing,
        focus=row.focus,
        one_line=str(row.hint_json.get("one_line", "")),
        service_matches=service_matches,
        spec_ok=row.spec_ok,
        closed=row.state == "CLOSED",
        detail=detail,
        hint_json=row.hint_json,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "chinese-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s8-clause-alignment.md"),
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    load_dotenv()
    settings = LLMSettings.from_env()
    if not settings.api_key:
        print("! 需要 DEEPSEEK_API_KEY（仓库根 .env 或环境变量）")
        return 2
    if settings.mode == "off":
        from dataclasses import replace as dc_replace

        settings = dc_replace(settings, mode="on")

    cases = load_cases(Path(args.problems))
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("! 评测集为空")
        return 2

    validator = _validator()
    container = build_container(settings)
    started = time.perf_counter()
    rows = [
        compare_case(container, case, validator, variant) for case in cases for variant in VARIANTS
    ]
    elapsed = time.perf_counter() - started

    total = len(rows)
    built = sum(1 for row in rows if row.hint_json is not None)
    spec_ok = sum(1 for row in rows if row.spec_ok and row.hint_json is not None)
    matches = sum(1 for row in rows if row.service_matches)
    closed = sum(1 for row in rows if row.closed)
    violations = [row for row in rows if row.detail]

    by_case: dict[str, dict[str, Compare]] = {}
    for row in rows:
        by_case.setdefault(row.case.id, {})[row.variant] = row

    monotone = [
        full.new_weighted >= partial.new_weighted
        for entry in by_case.values()
        if (partial := entry.get("partial")) is not None and (full := entry.get("full")) is not None
    ]
    full_ge_old = [
        full.new_weighted >= full.old_weighted
        for entry in by_case.values()
        if (full := entry.get("full")) is not None
    ]
    blank_clean = [
        blank.new_covered == 0 and blank.new_partial == 0 and blank.new_missing == blank.steps
        for entry in by_case.values()
        if (blank := entry.get("blank")) is not None
    ]
    improved = [
        full.new_weighted > full.old_weighted
        for entry in by_case.values()
        if (full := entry.get("full")) is not None
    ]

    old_full = [row.old_covered for row in rows if row.variant == "full"]
    new_full_cov = [row.new_covered for row in rows if row.variant == "full"]
    new_full_partial = [row.new_partial for row in rows if row.variant == "full"]
    new_full_weighted = [row.new_weighted for row in rows if row.variant == "full"]

    lines: list[str] = [
        "# M2.5 S8 分句级对齐报告（NONE 档：语文；同一张图对比旧/新对齐器）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}-chinese`；"
        f"模式：`{settings.mode}`",
        f"- 数据集：`{Path(args.problems).name}`（{len(cases)} 题 × "
        f"{len(VARIANTS)} 段过程 = {total} 次建会话）",
        f"- 建会话成功：{built}/{total}（{pct(built, total)}，门槛 ≥{PASS_BAR:.0%}）",
        f"- 出结构提示：{built}/{built}；符合 `structure-hint.schema.json` v0.2："
        f"{spec_ok}/{built}；服务 hint 与直接 `ClauseCueAligner` 一致：{matches}/{built}",
        f"- 出卡点卡：0/{built}（按设计）；出探针：0/{built}（按设计）；"
        f"停在 CLOSED：{closed}/{built}",
        f"- 承诺/接线违例：{len(violations)}；总耗时 {elapsed:.1f}s",
        "",
        "> 这是**对齐器**的验收，不是“语文诊断准确率”。同一道题只用一张生成图，"
        "旧/新两个对齐器读同一段过程；这样差异只可能来自匹配策略，不会混进建图随机性。",
        "",
        "| 题号 | 过程 | 节点 | 旧 covered | 新 covered | 新 partial | 新 missing | "
        "新加权 | focus | 一句话 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {id} | {variant} | {steps} | {old} | {new} | {partial} | {missing} | "
            "{weighted:.1f} | {focus} | {one_line} |".format(
                id=cell(row.case.topic or row.problem_id or "?"),
                variant=row.variant,
                steps=row.steps,
                old=row.old_covered,
                new=row.new_covered,
                partial=row.new_partial,
                missing=row.new_missing,
                weighted=row.new_weighted,
                focus=cell(row.focus or "-"),
                one_line=cell(row.one_line[:80]),
            )
        )

    lines += [
        "",
        f"- 旧对齐器 full 的 covered 均值：{_mean([float(value) for value in old_full]):.1f}",
        f"- 新对齐器 full：covered 均值 {_mean([float(value) for value in new_full_cov]):.1f}、"
        f"partial 均值 {_mean([float(value) for value in new_full_partial]):.1f}、"
        f"加权均值 {_mean(new_full_weighted):.1f}（partial 记 0.5）",
        f"- full ≥ partial（加权）：{sum(monotone)}/{len(monotone)}；"
        f"full 新 ≥ 旧：{sum(full_ge_old)}/{len(full_ge_old)}；"
        f"full 有提升：{sum(improved)}/{len(improved)}（门槛 ≥4/6）；"
        f"blank 全 missing：{sum(blank_clean)}/{len(blank_clean)}",
    ]

    if violations:
        lines += ["", "违例："]
        lines += [
            f"- `{row.problem_id or row.case.id}` / {row.variant}：{row.detail}"
            for row in violations
        ]

    sample = next(
        (
            row
            for row in rows
            if row.variant == "full" and row.new_partial > 0 and row.hint_json is not None
        ),
        None,
    )
    if sample is not None:
        lines += [
            "",
            f"## 样例（原样输出，未改写）：`{sample.case.topic}` / {sample.variant}",
            "",
            f"题号 `{sample.problem_id}` · 过程「{sample.case.work_for(sample.variant)}」",
            "",
            "```json",
            json.dumps(sample.hint_json, ensure_ascii=False, indent=2),
            "```",
        ]

    lines += [
        "",
        "## 读法与边界",
        "",
        (
            "- **同一张图对比**：每题只建一次图，旧/新对齐器读同一段过程；"
            "差异来自分句匹配，不来自模型重新建图。"
        ),
        (
            "- **分句匹配不是语义匹配**：按 `，；。：、` 切分，取与过程文本的最长连续公共子串；"
            "换一种说法、没有共同字面时仍会 `missing`。"
        ),
        (
            "- **`partial` 不是“写错”**：它只表示节点里至少一个小句在过程里出现；"
            "不判断这一半对不对，也不生成卡点卡/探针。"
        ),
        (
            "- **阈值固定**：小句 ≥4 字、公共段 ≥4 字、覆盖 ≥75% 为 covered、≥15% 为 partial；"
            "由 `test_clause_alignment.py` 锁住，不按本报告结果回调。"
        ),
        (
            "- **数学/物理没有 opt-in**：它们仍走 `TypeCueAligner`，S5/S6 的卡点节点与数字不变；"
            "`ClauseCueAligner` 只由 `ChinesePlugin.aligner_for()` 返回。"
        ),
        (
            "- 本报告衡量“只写前半句能不能被看见”和接线是否成立，不衡量语文诊断准确率；"
            "语文仍没有可自动验证的标准答案。"
        ),
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"\n建会话 {built}/{total}，合规 {spec_ok}/{built}，"
        f"服务一致 {matches}/{built}，违例 {len(violations)}"
    )
    print(f"报告：{out}")

    passed = (
        built == total
        and spec_ok == total
        and matches == total
        and closed == total
        and not violations
        and all(monotone)
        and all(full_ge_old)
        and all(blank_clean)
        and sum(improved) >= 4
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
