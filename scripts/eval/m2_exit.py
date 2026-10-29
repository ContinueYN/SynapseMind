"""M2 exit-condition report (T7).

Replays every golden case through the real state machine and writes the
``(turn, top1, margin, kind)`` table from chapter 12 §12.3.

    python scripts/eval/m2_exit.py                    # rule baseline (off)
    python scripts/eval/m2_exit.py --live-shadow      # compare against DeepSeek

In ``shadow`` mode the report also carries the audit-log numbers §12.6 asks
for (JSON validity, latency, retries, token use). Exit code is 0 only when the
pass rate clears the §2.4 bar (>= 8/10).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from synapse.api.deps import build_container  # noqa: E402
from synapse.application.replay import (  # noqa: E402
    GoldenCase,
    ReplayResult,
    judge,
    load_cases,
    replay_case,
)
from synapse.infrastructure.llm.settings import LLMSettings  # noqa: E402

PASS_BAR = 8
MAX_DIFF_SAMPLES = 6


@dataclass
class AuditStats:
    calls: int = 0
    schema_ok: int = 0
    retried: int = 0
    fallbacks: int = 0
    shadow_rows: int = 0
    differs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies: list[int] = field(default_factory=list)
    models: Counter[str] = field(default_factory=Counter)
    pairs: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def valid_rate(self) -> float:
        return self.schema_ok / self.calls if self.calls else 0.0

    def percentile(self, ratio: float) -> int:
        if not self.latencies:
            return 0
        ordered = sorted(self.latencies)
        index = max(0, math.ceil(ratio * len(ordered)) - 1)
        return ordered[index]

    @property
    def p50(self) -> int:
        return self.percentile(0.50)

    @property
    def p95(self) -> int:
        return self.percentile(0.95)

    @property
    def worst(self) -> int:
        return max(self.latencies) if self.latencies else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        default=str(ROOT / "eval" / "golden" / "golden-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2-exit-v0.1.md"),
    )
    parser.add_argument(
        "--live-shadow",
        action="store_true",
        help="run with SYNAPSE_LLM_MODE=shadow (needs a key; results unchanged)",
    )
    args = parser.parse_args()

    settings = LLMSettings.from_env()
    if args.live_shadow and settings.mode == "off":
        settings = LLMSettings.from_env({"SYNAPSE_LLM_MODE": "shadow"})
    if settings.mode != "off" and not settings.llm_enabled:
        print("! model mode requested but no API key; running the rule baseline")
        settings = LLMSettings.from_env({"SYNAPSE_LLM_MODE": "off"})

    container = build_container(settings)
    cases = load_cases(Path(args.golden))

    audit_path = Path(settings.audit_path)
    offset = audit_path.stat().st_size if audit_path.is_file() else 0

    rows: list[tuple[GoldenCase, ReplayResult, bool, str]] = []
    for case in cases:
        result = replay_case(container.service, case)
        verdict = judge(case, result)
        rows.append((case, result, verdict.passed, verdict.reason))

    passed = sum(1 for _, _, ok, _ in rows if ok)
    mean_turns = sum(result.last_turn for _, result, _, _ in rows) / len(rows)
    leaks = sum(result.leak_fallbacks for _, result, _, _ in rows)

    stats = _read_audit(audit_path, offset) if settings.llm_enabled else None
    table = _render(
        cases=rows,
        passed=passed,
        mean_turns=mean_turns,
        leaks=leaks,
        mode=settings.mode,
        stats=stats,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table, encoding="utf-8")
    print(table)
    print(f"report: {out}")
    return 0 if passed >= PASS_BAR else 1


def _read_audit(path: Path, offset: int) -> AuditStats | None:
    """Aggregate the entries this run appended; never the whole file."""
    try:
        payload = path.read_bytes()[offset:]
    except OSError:
        return None
    records = []
    for line in payload.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))

    stats = AuditStats()
    seen_probes: set[str] = set()
    for record in records:
        kind = record.get("kind")
        if kind == "llm_call":
            stats.calls += 1
            stats.prompt_tokens += int(record.get("prompt_tokens") or 0)
            stats.completion_tokens += int(record.get("completion_tokens") or 0)
            stats.latencies.append(int(record.get("latency_ms") or 0))
            if record.get("schema_ok"):
                stats.schema_ok += 1
            if record.get("retried"):
                stats.retried += 1
            if record.get("model"):
                stats.models[str(record["model"])] += 1
        elif kind == "fallback":
            stats.fallbacks += 1
        elif kind == "shadow":
            stats.shadow_rows += 1
            baseline = str(record.get("baseline") or "")
            candidate = str(record.get("candidate") or "")
            if candidate and candidate != baseline:
                stats.differs += 1
                probe_id = str(record.get("probe_id") or "")
                if probe_id not in seen_probes and len(stats.pairs) < MAX_DIFF_SAMPLES:
                    seen_probes.add(probe_id)
                    stats.pairs.append((probe_id, baseline, candidate))
    return stats


def _render(
    *,
    cases: list[tuple[GoldenCase, ReplayResult, bool, str]],
    passed: int,
    mean_turns: float,
    leaks: int,
    mode: str,
    stats: AuditStats | None,
) -> str:
    lines = [
        "# M2 退出判定报告（10 条 golden）",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- LLM 模式：`{mode}`（默认 `off`；判定口径与模式无关）",
        f"- 通过：{passed}/{len(cases)}（要求 ≥ {PASS_BAR}/10）",
        f"- 平均轮数：{mean_turns:.2f}（§12.6 目标 4–6，上限 6）",
        f"- 泄漏降级：{leaks}（要求 0）",
    ]
    if stats is None:
        lines.append("- 模型调用：`off` 模式无调用（JSON 合法率不适用）")
    else:
        models = "、".join(f"`{name}`({count})" for name, count in stats.models.items())
        lines += [
            f"- 模型调用：{stats.calls} 次，JSON 合法 {stats.schema_ok}/{stats.calls}"
            f"（{stats.valid_rate:.0%}，§12.6 要求 ≥99%）",
            f"- 重试 {stats.retried} 次；降级 {stats.fallbacks} 次",
            f"- 延迟：p50 {stats.p50} ms，p95 {stats.p95} ms，max {stats.worst} ms"
            "（首问预算 8s）",
            f"- Token：prompt {stats.prompt_tokens} / completion {stats.completion_tokens}",
            f"- shadow 差异：{stats.differs}/{stats.shadow_rows} 条（只记录，不改变返回结果）",
        ]
        if models:
            lines.append(f"- 实际服务模型：{models}")

    lines += [
        "",
        "| case | 类别 | 期望 | 标注 | 轮次 | top1 | margin | kind | 判定 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for case, result, ok, reason in cases:
        last = result.turns[-1] if result.turns else None
        kind = "-"
        if last is not None:
            kind = last.kind if last.kind == result.outcome else f"{last.kind}→{result.outcome}"
        lines.append(
            "| {case} | {category} | {expect} | {layer} | {turn} | {top1} | {margin} | {kind} | {verdict} |".format(
                case=case.case_id,
                category=case.category,
                expect=case.expect,
                layer=case.label_layer,
                turn=result.last_turn or "-",
                top1=last.top1 if last else "-",
                margin=f"{last.margin:.2f}" if last else "-",
                kind=kind,
                verdict=("PASS" if ok else "FAIL") + f"（{reason}）",
            )
        )

    lines += [
        "",
        "## 逐轮轨迹（判定口径与 §12.3 同源）",
        "",
    ]
    for case, result, _, _ in cases:
        trace = " → ".join(
            f"t{row.turn} {row.probe_id} {row.top1}={row.posterior:.2f} "
            f"margin={row.margin:.2f} {row.kind}"
            for row in result.turns
        )
        lines.append(f"- `{case.case_id}`：{trace or '（未提问）'}")
        if case.notes:
            lines.append(f"  - 标注说明：{case.notes}")

    if stats is not None and stats.pairs:
        lines += ["", "## shadow 差异样本（每类探针取一条，供人工判读）", ""]
        for probe_id, baseline, candidate in stats.pairs:
            lines += [
                f"- `{probe_id}`",
                f"  - 规则：{baseline}",
                f"  - 模型：{candidate}",
            ]

    lines += [
        "",
        "## 已知边界（M2 不做，M2.5 处理）",
        "",
        "- 当前只有一道种子题（`P_FUNC_001`），所有 case 共享同一张解法图。",
        "- 证据表 `EVIDENCE` 只覆盖 `p_a0_derivative` / `p_boundary_check` / `p_max_value`；"
        "在现有权重下只有 `H_L2`（参数分类）能越过 0.80 + 0.25 的判定线。",
        "- 因此 `L1` / `L4` 案例按“低置信不硬判”记为 `expect=stop`；"
        "它们验证的是安全收束，不是区分能力。",
        f"- 本轮平均 {mean_turns:.2f} 轮低于 §12.6 的 4–6：单图证据在第 2 轮就饱和，"
        "不是追问变少，而是没有更多可区分的探针。扩图后需要重测。",
        "- 扩题与更细的证据标定属于 M2.5（学科插件），不在 M2 的措辞替换范围里。",
        "- shadow 的“差异”只说明措辞变了，不说明变好了：判定要人工读样本或加前提保留检查。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())