"""M2.5 S6: physics through the *unchanged* dialogue pipeline.

This is the second-subject counterpart of ``s5_session.py``. The only new
ingredient is the subject declaration and the physics prompt; the aligner,
state machine, diagnosis gate and card builder are the same objects.

The report deliberately separates two claims:

* **plumbing** — a physics stem can be generated, aligned, probed and carded;
* **diagnosis quality** — not measured here (the simulated student answers in
  the direction the alignment points at, exactly like S5).

Usage::

    python scripts/eval/s6_physics.py [--limit N] [--policy aligned|first]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from s5_session import (  # noqa: E402
    PASS_BAR,
    cell,
    load_cases,
    pct,
    percentile,
    probe_stats,
    run_case,
)

from synapse.api.deps import build_container  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402
from synapse.infrastructure.subjects.physics import (  # noqa: E402
    PHYSICS_HYPOTHESIS_LABELS,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "physics-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s6-physics.md"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--policy", choices=("aligned", "first"), default="aligned")
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

    container = build_container(settings)
    started = time.perf_counter()
    rows = [run_case(container, case, policy=args.policy) for case in cases]
    elapsed = time.perf_counter() - started

    created = sum(1 for row in rows if row.created)
    with_card = [row for row in rows if row.card]
    node_ok = sum(1 for row in rows if row.node_in_graph)
    latencies = [row.elapsed_ms for row in rows if row.created]
    turns_total = sum(row.turns for row in rows)
    stats = probe_stats(container, rows)
    card_rate = len(with_card) / created if created else 0.0
    card_layers = Counter(str(row.card.get("layer", "-")) for row in with_card)
    physics_label_set = set(PHYSICS_HYPOTHESIS_LABELS.values())
    physics_labels = sum(
        1 for row in with_card if str(row.card.get("label", "")) in physics_label_set
    )
    nodes = []
    claims = 0
    for row in rows:
        problem = container.problems.get(row.problem_id) if row.created else None
        if problem is not None:
            nodes.append(len(problem.graph.nodes))
            claims += 1 if problem.graph.claim is not None else 0

    lines: list[str] = [
        "# M2.5 S6 物理接入报告（同一状态机 → ALIGN → PROBE → 卡点卡）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}-physics`；"
        f"模式：`{settings.mode}`",
        f"- 数据集：`{Path(args.problems).name}`（{len(rows)} 题）；作答策略：`{args.policy}`",
        f"- 建会话成功：{created}/{len(rows)}（{pct(created, len(rows))}，门槛 ≥{PASS_BAR:.0%}）",
        f"- 出卡：{len(with_card)}/{created}（{pct(len(with_card), created)}）；"
        f"卡点节点属于该图：{node_ok}/{len(with_card)}",
        f"- 物理词表卡面：{physics_labels}/{len(with_card)}；"
        f"卡点层分布：{dict(card_layers) or '-'}",
        (
            f"- 图规模：{stats['probes']} 个探针（每题 {stats['probes_min']}–"
            f"{stats['probes_max']} 个），节点均值 "
            f"{(sum(nodes) / len(nodes)) if nodes else 0:.1f}；"
            f"{stats['weights']} 条权重，max|w|={stats['max_weight']:.2f}，"
            f"|w|≥0.8 的有 {stats['bold_weights']} 条"
        ),
        (
            f"- 总耗时：{elapsed:.1f}s；建会话 p50 {percentile(latencies, 0.50)} ms / "
            f"p95 {percentile(latencies, 0.95)} ms；总探针轮数：{turns_total}"
        ),
        f"- claim：物理图本轮写出 {claims}/{created} 条；按设计一律丢弃，"
        "`verification.status` 为 `unknown`，不是“已核对”。",
        "",
        "> 这是**接线验收**：物理题走的是与数学完全相同的 `SessionService` / "
        "`DialogueSession` / `HypothesisSet` / `build_diagnosis_card`。"
        "`aligned` 策略模拟“作答与对齐缺口一致”，只回答“生成图能不能支撑到卡点卡”，"
        "不回答“物理诊断准不准”。",
        "",
        "| 题号 | 建会话 | 轮数 | 卡点 | 节点在图内 | 一句话 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        card = row.card or {}
        lines.append(
            "| {id} | {ok} | {turns} | {layer}/{node} | {node_ok} | {one_line} | {note} |".format(
                id=cell(row.problem_id or row.case.topic[:12]),
                ok="是" if row.created else "否",
                turns=row.turns,
                layer=cell(str(card.get("layer", "-"))),
                node=cell(str(card.get("node_id", "-"))),
                node_ok="是" if row.node_in_graph else ("-" if not card else "否"),
                one_line=cell(str(card.get("one_line", ""))[:80]),
                note=cell(row.detail[:120] or ("；".join(row.notices)[:60] or "")),
            )
        )

    lines += [
        "",
        "## 读法与边界",
        "",
        (
            "- **零状态机改动**：本次没有新增状态、事件或转移；物理只是 `SubjectRegistry` 里的"
            "第二个插件，`SessionFactory` 用同一套 `INGEST → ALIGN → PROBE → DIAGNOSE`。"
        ),
        (
            "- **标签不是评分**：物理插件只替换 H_L1/H_L2/H_L4 的可读文案"
            "（物理模型/条件转译、概念/公式条件不清、执行/计算错误）；先验、log-odds、"
            "0.80+0.25 门槛完全复用。"
        ),
        (
            "- **PARTIAL 验证**：`PhysicsPlugin.verify()` 目前对纯文本步骤返回 `unknown`；"
            "量纲/单位与数值回代需要结构化的步骤输入，不能在自由文本上假装核对。"
        ),
        (
            "- **出卡率不是诊断准确率**：`aligned` 是构造出来的学生；真实物理诊断准确率"
            "需要另建带学生作答的评测集。"
        ),
        (
            "- 生成物理题没有存储答案，泄漏守卫退化为通用短语表；图上也没有 claim，"
            "所以任何“答案已验证”的说法都不成立。"
        ),
    ]
    if card_rate < 0.5:
        lines += [
            "",
            (
                "出卡率偏低时先看探针/权重与题的开放度，不要调低 0.80+0.25 门槛；"
                "S6 的硬判据是建会话与卡点节点属于该图。"
            ),
        ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n建会话 {created}/{len(rows)}，出卡 {len(with_card)}，节点在图内 {node_ok}")
    print(f"报告：{out}")
    return 0 if created / len(rows) >= PASS_BAR else 1


if __name__ == "__main__":
    raise SystemExit(main())
