"""M2.5 S5 ②: 20 unseen stems through ALIGN -> PROBE -> card.

This is the end-to-end counterpart of ``s5_verify.py``: that script measured
graph building and claim verification; this one measures the *request path* the
student would hit — submit a stem nobody annotated, get probes, answer them,
get a card.

Deliberate simplifications, because this measures plumbing and not diagnosis
quality:

* the submitted work is a fixed partial solution ("确认条件，按参数分类讨论"),
  which mentions enough to be a plausible attempt but never a full solution;
* the "student" answers with the option whose in-graph evidence most supports
  the hypothesis layer the alignment already pointed at (``--policy aligned``),
  or always the first option (``--policy first``). The aligned policy is the
  interesting one: it asks "if the answers agree with the aligned gap, does the
  card land on a node of *this* graph?";
* it stops after the diagnosis / close / turn cap, whichever comes first.

Usage::

    python scripts/eval/s5_session.py [--limit N] [--policy aligned|first]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from synapse.api.deps import build_container
from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand
from synapse.application.errors import ProblemNotSupported
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv

PASS_BAR = 0.80
SAMPLE_WORK = {
    "math": "先确认题目的条件，再按参数分类讨论。",
    "physics": "先读题，标出已知量和单位，再选择物理模型。",
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
    notices: list[str] = field(default_factory=list)
    turns: int = 0
    card: dict[str, Any] | None = None
    node_in_graph: bool = False
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


def _aligned_option(
    container: Any, session_id: str, problem: Any, options: list[str], layer: str
) -> str:
    """Pick the option that best supports the layer the alignment pointed at.

    The layer is fixed at session start (it comes from the aligned gap), not
    re-read each turn: a simulated student who keeps answering in the aligned
    direction, instead of one who chases whatever hypothesis is momentarily on
    top. That distinction matters — the second policy flips the leading
    hypothesis every turn and never accumulates a margin.
    """

    try:
        session = container.sessions.get(session_id)
        probe_id = session.current_probe_id if session else None
        probe = problem.graph.probe(probe_id) if probe_id else None
    except (KeyError, AttributeError):
        return "A"
    if probe is None or not probe.evidence or len(probe.options) != len(options):
        return "A"
    best_index = 0
    best_weight = float("-inf")
    for index in range(len(probe.options)):
        # ``Probe.evidence`` is keyed by option letter, not by option text.
        weights = probe.evidence.get("ABCDEFGH"[index]) or {}
        weight = sum(
            value
            for hypothesis_id, value in weights.items()
            if session.hypotheses.states[hypothesis_id].hypothesis.layer == layer
        )
        if weight > best_weight:
            best_index, best_weight = index, weight
    return "ABCDEFGH"[best_index]


def run_case(container: Any, case: Case, *, policy: str) -> Row:
    started = time.perf_counter()
    row = Row(case=case)
    service = container.service
    try:
        view = service.start(
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

    row.created = True
    row.elapsed_ms = int((time.perf_counter() - started) * 1000)
    row.problem_id = view.session.problem_id
    problem = container.problems.get(row.problem_id)
    row.annotated = bool(problem and problem.annotated)
    top_id, _ = view.session.hypotheses.top()
    # The gap the aligner found, frozen at session start (see _aligned_option).
    target_layer = view.session.hypotheses.states[top_id].hypothesis.layer
    if view.notice:
        row.notices.append(view.notice)

    while view.prompt is not None and row.turns < view.session.max_turns:
        prompt = view.prompt
        row.turns += 1
        option_id = "A"
        if policy == "aligned" and problem is not None:
            option_id = _aligned_option(
                container,
                view.session.session_id,
                problem,
                list(prompt.options),
                target_layer,
            )
        index = "ABCDEFGH".find(option_id)
        answer = prompt.options[index] if 0 <= index < len(prompt.options) else prompt.options[0]
        try:
            view = service.submit(
                view.session.session_id,
                SubmitAnswerCommand(answer=answer, option_id=option_id),
            )
        except (ProblemNotSupported, ValueError) as exc:
            row.detail = f"turn {row.turns}: {exc}"
            break
        if view.notice:
            row.notices.append(view.notice)

    if view.diagnosis is not None:
        card = view.diagnosis
        node_ids = {node.id for node in problem.graph.nodes} if problem else set()
        row.card = {
            "layer": card.layer,
            "label": card.label,
            "node_id": card.node_id,
            "one_line": card.one_line,
            "confidence": card.confidence,
            "concept_id": str(card.next_action.get("concept_id", "")),
        }
        row.node_in_graph = card.node_id in node_ids
    return row


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def probe_stats(container: Any, rows: list[Row]) -> dict[str, Any]:
    """How much evidence the graphs actually offered.

    The card gate is ``0.80 + 0.25``; whether a session can clear it depends on
    how many probes a graph has and how large their weights are, so report both
    instead of only the card count.
    """

    probes = 0
    weights: list[float] = []
    per_problem: list[int] = []
    for row in rows:
        problem = container.problems.get(row.problem_id) if row.created else None
        if problem is None:
            continue
        graph_probes = problem.graph.probes()
        per_problem.append(len(graph_probes))
        probes += len(graph_probes)
        for probe in graph_probes:
            for option_weights in (probe.evidence or {}).values():
                weights.extend(option_weights.values())
    return {
        "probes": probes,
        "weights": len(weights),
        "max_weight": max((abs(value) for value in weights), default=0.0),
        "bold_weights": sum(1 for value in weights if abs(value) >= 0.8),
        "probes_min": min(per_problem, default=0),
        "probes_max": max(per_problem, default=0),
        "probes_mean": (sum(per_problem) / len(per_problem)) if per_problem else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "unseen-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s5-session.md"),
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
    rows: list[Row] = []
    for case in cases:
        row = run_case(container, case, policy=args.policy)
        rows.append(row)
        if row.created:
            card = row.card or {}
            print(
                f"OK   {row.problem_id} turns={row.turns} "
                f"{row.elapsed_ms}ms card={card.get('layer', '-')}/{card.get('node_id', '-')}"
            )
        else:
            print(f"FAIL {cell(case.topic)[:16]} {row.detail[:120]}")
    elapsed = time.perf_counter() - started

    created = sum(1 for row in rows if row.created)
    with_card = [row for row in rows if row.card]
    node_ok = sum(1 for row in rows if row.node_in_graph)
    latencies = [row.elapsed_ms for row in rows if row.created]
    annotated = sum(1 for row in rows if row.annotated)
    turns_total = sum(row.turns for row in rows)
    ratio = created / len(rows)
    stats = probe_stats(container, rows)
    card_rate = len(with_card) / created if created else 0.0
    card_layers = Counter(str(row.card.get("layer", "-")) for row in with_card)

    lines: list[str] = [
        "# M2.5 S5 ②/③ 请求链路报告（未见题 → ALIGN → PROBE → 卡点卡）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}`；模式：`{settings.mode}`",
        f"- 数据集：`{Path(args.problems).name}`（{len(rows)} 题）；作答策略：`{args.policy}`",
        f"- 建会话成功：{created}/{len(rows)}（{pct(created, len(rows))}，门槛 ≥{PASS_BAR:.0%}）",
        f"- 其中标注库命中：{annotated}（其余为现场生成，`annotated=False`）",
        f"- 出卡：{len(with_card)}/{created}（{pct(len(with_card), created)}）；"
        f"卡点节点属于该图：{node_ok}/{len(with_card)}",
        f"- 卡点层分布：{dict(card_layers) or '-'}",
        (
            f"- 图提供的证据：{stats['probes']} 个探针（每题 {stats['probes_min']}–"
            f"{stats['probes_max']} 个，均值 {stats['probes_mean']:.1f}），"
            f"{stats['weights']} 条权重，max|w|={stats['max_weight']:.2f}，"
            f"|w|≥0.8 的有 {stats['bold_weights']} 条"
        ),
        (
            f"- 总耗时：{elapsed:.1f}s；建会话 p50 {percentile(latencies, 0.50)} ms / "
            f"p95 {percentile(latencies, 0.95)} ms；总探针轮数：{turns_total}"
        ),
        "",
        (
            "> 每题提交的是一段固定的部分过程（“先确认题目的条件，再按参数分类讨论。”）。"
            "`aligned` 策略下，作答模拟“学生的回答与对齐发现的缺口一致”——只有这种作答才可能"
            "走到卡点卡，因此它检验的是**生成图是否足以支撑 ALIGN → PROBE → 卡点卡**，"
            "而不是诊断准确率（那需要真实学生作答，属 M2.5 之后的评测集扩容）。"
        ),
        "",
        "| 题号 | 建会话 | 生成/标注 | 轮数 | 卡点 | 节点在图内 | 一句话 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        card = row.card or {}
        lines.append(
            "| {id} | {ok} | {kind} | {turns} | {layer}/{node} | {node_ok} | {one_line} | {note} |".format(
                id=cell(row.problem_id or row.case.topic[:12]),
                ok="是" if row.created else "否",
                kind="生成"
                if row.created and not row.annotated
                else ("标注" if row.created else "-"),
                turns=row.turns,
                layer=cell(str(card.get("layer", "-"))),
                node=cell(str(card.get("node_id", "-"))),
                node_ok="是" if row.node_in_graph else ("-" if not card else "否"),
                one_line=cell(str(card.get("one_line", ""))[:80]),
                note=cell(row.detail[:120] or ("；".join(row.notices)[:60] or "")),
            )
        )

    reading: list[str] = [
        "",
        "## 出卡率怎么读",
        "",
        (
            f"卡点卡的门槛是后验 ≥0.80 且领先第二名 ≥0.25，与 M2 的种子题完全相同。"
            f"本轮图提供 {stats['probes']} 个探针、{stats['weights']} 条权重，"
            f"max|w|={stats['max_weight']:.2f}，|w|≥0.8 的有 {stats['bold_weights']} 条。"
        ),
    ]
    if card_rate < 0.5:
        reading += [
            "",
            (
                "出卡率偏低说明探针/权重还不够强：即使作答方向与对齐结论一致，"
                "后验也会在几轮里被来回推动、攒不出领先 0.25 的差距，最后按设计收束为"
                "「低置信、不硬判卡点」。这属于 S5 ③ 的校准问题，不是链路问题——"
                "建会话与「卡点节点属于该图」两项才是接线判据。"
            ),
        ]
    else:
        reading += [
            "",
            (
                f"出卡率 {pct(len(with_card), created)} 说明 S5 ③ 的权重校准生效："
                "prompt v4 要求每个探针至少有一个权重达到 ±0.8~1.0，同一假设在不同选项上"
                "拉开 ≥1.0 的差距；图构建器还会在模型写得偏弱时按全图统一系数放大到 0.90，"
                "不改符号也不改相对强弱。"
            ),
        ]
    if card_layers:
        layers = "、".join(f"{layer} {count}" for layer, count in card_layers.most_common())
        reading.append(
            f"卡点层分布：{layers}。`aligned` 策略在会话开始时把目标层固定为对齐缺口所在层，"
            "所以这一列只说明探针把后验推到了哪个方向，不是「这批题都该诊断成同一层」。"
        )
    reading += [
        "",
        (
            "**出卡率不是诊断准确率**：`aligned` 策略是构造出来的学生（按「与对齐结论一致」作答），"
            "它回答的是「生成图在理想作答下能不能走到卡点卡」；真实学生作答的准确率需要单独评测集。"
        ),
        "",
        "## 口径与已知边界",
        "",
        (
            "- 建会话含**一次图生成调用**（p50 约 4s，见 `m2.5-s5-verification.md`），"
            "所以这里的延迟是“首问 + 建图”，不是 M2 口径的单次改写延迟；首问预算 8s 仍然够，"
            "但余量比标注库路径小。"
        ),
        (
            "- `annotated=False` 的题没有存储答案，泄漏守卫退化为通用短语检查（见 `guards.py`）；"
            "模型仍被 prompt 要求不给答案，但 n-gram 规则在这一支上不能生效。"
        ),
        (
            "- 通用对齐只判断“这一步有没有被提到”，不判断对错；因此卡点卡在无探针证据时"
            "只说“过程里没有出现这一步”，不臆断误解。"
        ),
        (
            "- `aligned` 策略是**构造出来的学生**：按“与对齐结论一致”作答，因此出卡率描述的是"
            "“链路在理想作答下能走到哪”，不是模型诊断的准确率；`first` 策略（一律选第一项）"
            "用于对照，它经常停在低置信收束，说明阈值没有被绕开。"
        ),
    ]
    lines += reading

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n建会话 {created}/{len(rows)}，出卡 {len(with_card)}，节点在图内 {node_ok}")
    print(f"报告：{out}")
    return 0 if ratio >= PASS_BAR else 1


if __name__ == "__main__":
    raise SystemExit(main())
