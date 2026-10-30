"""M2.5 S5 ⑤: 缺口定位探针 —— 真值构造出来，不要老师填。

问题：`s5_review.py` 的「命中率」是子串匹配，4 条真实作答里至少 2 条属于
「卡点指对了、关键词没对上」；而*准确率*只有老师填完 `人工判断` 列才算得出来。
本轮拿不到老师时间，于是换一个不依赖人工的真值：

    给模型看一张图的全部步骤，让它扮演学生写解题过程，
    **故意跳过第 k 步**，其余步骤用自己的话改写（不许照抄）。

这样「哪一步该算没写」由构造决定，于是能量两件事：

1. **存在性检查的漏判率**：其余步骤都写了，对齐器有没有认出来（写了却判
   `missing` 就是漏判）；
2. **缺口定位**：卡点节点是不是被跳过的那一步。

它测的是**对齐器**（`TypeCueAligner`）在自然语言改写上的准确率，不是端到端
诊断准确率——探针作答仍由 `aligned` 策略代答。但它比子串命中率硬：真值不是
措辞，是指定的节点 id。

用法（需真实 key）::

    cd apps/api
    $env:SYNAPSE_LLM_MODE='on'
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_gap_probe.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from s5_session import Case, _aligned_option, cell, load_cases, pct, percentile  # noqa: E402

from synapse.api.deps import build_container  # noqa: E402
from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand  # noqa: E402
from synapse.application.llm import LLMRequest  # noqa: E402
from synapse.infrastructure.llm.client import OpenAICompatibleClient  # noqa: E402
from synapse.infrastructure.llm.settings import load_dotenv  # noqa: E402

PLACEHOLDER_WORK = "我先看一下题目，把条件抄一遍。"
MAX_TURNS = 6
LEAK_CHARS = 6

SYSTEM = "你在模拟一名中国高三学生做题。只输出 JSON 对象，不要解释。"

USER = """题目：
{text}

老师版解法（学生看不到，这里只是告诉你这题有哪几步）：
{steps}

请用**学生自己的口吻**写一段这题的解题过程，要求：

1. 覆盖上面**除第 {omit} 步之外**的每一步；不许照抄原句，用自己的话改写；
2. **完全不要提第 {omit} 步**：不要写它的意思，也不要写它涉及的概念；
3. 步骤之间可以合并、换顺序，但要能看出是同一套思路；
4. 结尾写出最终答案（写清楚，不要只说「所以答案选 B」之外的含糊话）。

`kept` 写你**真的写进过程里**的步骤编号（合并或省略的不要列），必须不含第 {omit} 步。
只输出：{{"work": "解题过程", "answer": "最终答案", "kept": [1, 2, 4]}}"""


@dataclass
class Gap:
    case: Case
    problem_id: str = ""
    node_count: int = 0
    omitted_id: str = ""
    omitted_text: str = ""
    omitted_type: str = ""
    work: str = ""
    answer: str = ""
    leaked: bool = False
    kept: list[int] = field(default_factory=list)
    written: int = 0
    matched_written: int = 0
    false_negatives: list[str] = field(default_factory=list)
    gap_detected: bool = False
    first_missing: str = ""
    gap_first_hit: bool = False
    card_layer: str = ""
    card_node: str = ""
    card_one_line: str = ""
    card_hit: bool = False
    elapsed_ms: int = 0
    detail: str = ""

    @property
    def recall(self) -> float:
        return self.matched_written / self.written if self.written else 0.0


def _nodes(problem: Any) -> list[Any]:
    return list(problem.graph.nodes)


def _steps_block(nodes: list[Any]) -> str:
    return "\n".join(f"{index}. {node.text}" for index, node in enumerate(nodes, start=1))


def _longest_common(a: str, b: str) -> int:
    """Longest common substring length (small inputs; no third-party deps)."""

    if not a or not b:
        return 0
    best = 0
    previous = [0] * (len(b) + 1)
    for ch_a in a:
        current = [0] * (len(b) + 1)
        for index, ch_b in enumerate(b, start=1):
            if ch_a == ch_b:
                current[index] = previous[index - 1] + 1
                if current[index] > best:
                    best = current[index]
        previous = current
    return best


def _ask_student(
    client: OpenAICompatibleClient,
    case: Case,
    nodes: list[Any],
    omit_index: int,
) -> tuple[str, str, list[int], str]:
    request = LLMRequest(
        purpose="student_simulation",
        system=SYSTEM,
        user=USER.format(
            text=case.text,
            steps=_steps_block(nodes),
            omit=omit_index + 1,
        ),
        schema_name=None,
        json_schema=None,
        max_tokens=800,
    )
    response = client.complete(request, timeout_s=90.0)
    try:
        payload: Any = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"学生模拟返回的不是 JSON：{response.text[:120]}") from exc
    if not isinstance(payload, dict):
        raise ValueError("学生模拟返回的不是 JSON 对象")
    raw_kept: Any = payload.get("kept", [])
    kept: list[int] = []
    if isinstance(raw_kept, list):
        for item in raw_kept:
            try:
                kept.append(int(item))
            except (TypeError, ValueError):
                continue
    return (
        str(payload.get("work", "")).strip(),
        str(payload.get("answer", "")).strip(),
        kept,
        response.text,
    )


def _run_session(
    container: Any,
    text: str,
    work: str,
    answer: str,
    *,
    cap: int = MAX_TURNS,
) -> tuple[Any, Any, dict[str, Any] | None]:
    """Start a session, answer probes with the aligned policy, return card."""

    service = container.service
    view = service.start(
        StartSessionCommand(problem_text=text, answer=answer, work=work, subject="math")
    )
    alignment = view.session.alignment
    problem = container.problems.get(view.session.problem_id)
    top_id, _ = view.session.hypotheses.top()
    target_layer = view.session.hypotheses.states[top_id].hypothesis.layer

    turns = 0
    while view.prompt is not None and turns < cap:
        prompt = view.prompt
        turns += 1
        option_id = "A"
        if problem is not None:
            option_id = _aligned_option(
                container,
                view.session.session_id,
                problem,
                list(prompt.options),
                target_layer,
            )
        index = "ABCDEFGH".find(option_id)
        option = prompt.options[index] if 0 <= index < len(prompt.options) else prompt.options[0]
        try:
            view = service.submit(
                view.session.session_id,
                SubmitAnswerCommand(answer=option, option_id=option_id),
            )
        except ValueError as exc:
            return alignment, problem, {"detail": f"turn {turns}: {exc}"}

    card = None
    if view.diagnosis is not None:
        card = {
            "layer": view.diagnosis.layer,
            "node_id": view.diagnosis.node_id,
            "one_line": view.diagnosis.one_line,
        }
    return alignment, problem, card


def run_gap(
    container: Any,
    client: OpenAICompatibleClient,
    case: Case,
    index: int,
) -> Gap:
    started = time.perf_counter()
    gap = Gap(case=case)
    try:
        _, problem, _ = _run_session(
            container,
            case.text,
            PLACEHOLDER_WORK,
            "",
            cap=0,
        )
    except Exception as exc:  # noqa: BLE001 - 建图失败要写进报告，不要中断整轮
        gap.detail = f"建图失败：{exc}"
        gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return gap

    nodes = _nodes(problem)
    gap.problem_id = problem.id
    gap.node_count = len(nodes)
    if len(nodes) < 2:
        gap.detail = "节点太少，无法跳过"
        gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return gap

    omit_index = 1 + (index % (len(nodes) - 1))
    omitted = nodes[omit_index]
    gap.omitted_id = omitted.id
    gap.omitted_text = omitted.text
    gap.omitted_type = omitted.type

    try:
        work, answer, kept, raw = _ask_student(client, case, nodes, omit_index)
    except Exception as exc:  # noqa: BLE001
        gap.detail = f"学生模拟失败：{exc}"
        gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return gap
    gap.work = work
    gap.answer = answer
    gap.kept = kept
    if not work:
        gap.detail = f"空过程：{raw[:120]}"
        gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return gap
    # A model that writes the skipped step anyway ("leaks") makes the truth
    # unknown, so those samples are dropped rather than counted as misses.
    gap.leaked = (omit_index + 1) in kept or _longest_common(omitted.text, work) >= LEAK_CHARS

    try:
        alignment, _, card = _run_session(container, case.text, work, answer)
    except Exception as exc:  # noqa: BLE001
        gap.detail = f"会话失败：{exc}"
        gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return gap

    covered = set(alignment.matched_node_ids)
    covered |= set(getattr(alignment, "partial_node_ids", ()))
    # Ground truth for "written" is what the simulated student says it kept;
    # a compressed step it admits to skipping is not an aligner miss.
    written = [
        node
        for position, node in enumerate(nodes, start=1)
        if node.id != omitted.id and (not kept or position in kept)
    ]
    gap.written = len(written)
    gap.matched_written = sum(1 for node in written if node.id in covered)
    gap.false_negatives = [node.text for node in written if node.id not in covered]
    gap.gap_detected = omitted.id not in covered
    missing = list(alignment.missing_node_ids)
    gap.first_missing = missing[0] if missing else ""
    gap.gap_first_hit = gap.first_missing == omitted.id

    if card is not None and "node_id" in card:
        gap.card_layer = str(card["layer"])
        gap.card_node = str(card["node_id"])
        gap.card_one_line = str(card["one_line"])
        gap.card_hit = gap.card_node == omitted.id
    elif card is not None:
        gap.detail = str(card.get("detail", ""))
    gap.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return gap


def _render(gaps: list[Gap], args: argparse.Namespace) -> str:
    ok = [gap for gap in gaps if not gap.detail]
    valid = [gap for gap in ok if not gap.leaked]
    with_card = [gap for gap in valid if gap.card_node]
    hits = [gap for gap in with_card if gap.card_hit]
    detected = [gap for gap in valid if gap.gap_detected]
    first_hits = [gap for gap in valid if gap.gap_first_hit]
    elsewhere = [gap for gap in with_card if gap.gap_detected and not gap.card_hit]
    recalls = [gap.recall for gap in valid]
    total_written = sum(gap.written for gap in valid)
    total_matched = sum(gap.matched_written for gap in valid)
    elapsed = [gap.elapsed_ms for gap in valid]

    lines = [
        "# M2.5 S5 ⑤ 缺口定位探针（构造真值）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 题集：`{args.problems}`（前 {args.limit} 题）",
        "- 策略：`aligned`（探针作答与对齐结论一致，见 `s5_session.py`）",
        f"- 规模：跑 {len(gaps)} 条，建图成功 {len(ok)} 条，"
        f"泄漏（模型没真跳过）{len(ok) - len(valid)} 条，计入 {len(valid)} 条",
        "",
        "## 口径",
        "",
        "真值不是老师填的，是**构造**的：给模型看这张图的全部步骤，让它扮演学生写过程，"
        "故意跳过第 k 步、其余步骤用自己的话改写。于是「哪一步该算没写」由构造决定，"
        "可以机算两件事：",
        "",
        "1. **存在性检查的漏判**：其余步骤都写了，对齐器有没有认出来；",
        "2. **缺口定位**：卡点节点是不是被跳过的那一步。",
        "",
        "它测的是 `TypeCueAligner` 在**自然语言改写**上的准确率，不是端到端诊断准确率"
        "（探针仍由 `aligned` 代答）；但只要节点 id 对上，就不再依赖「老师写的词」碰巧"
        "出现在节点文本里——那正是子串命中率的问题。",
        "",
        "学生过程由模型扮演生成（`purpose=student_simulation`），**不是真实学生**；"
        "它的价值在于真值已知，可以作为对齐器的回归基线。",
        "",
        "## 逐条结果",
        "",
        "| 题 | 跳过的那步（类型） | 跳过的那步 | 自报保留 | 认出 | 漏判 | "
        "缺口被认成 missing | 首个 missing 就是它 | 卡点层 | 卡点落在它 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for gap in valid:
        lines.append(
            f"| {cell(gap.problem_id)} | {cell(gap.omitted_type)} | {cell(gap.omitted_text)[:24]} "
            f"| {len(gap.kept) or '?'}/{gap.node_count - 1} | {gap.matched_written}/{gap.written} "
            f"| {len(gap.false_negatives)} | {'是' if gap.gap_detected else '否'} "
            f"| {'是' if gap.gap_first_hit else '否'} | {cell(gap.card_layer or '-')} "
            f"| {'是' if gap.card_hit else '否'} |",
        )

    if with_card:
        lines += [
            "",
            "### 卡点没落在被跳过那步的样本",
            "",
        ]
        misses = [gap for gap in with_card if not gap.card_hit]
        if not misses:
            lines.append("- 无")
        for gap in misses:
            lines.append(
                f"- `{gap.problem_id}`：跳过「{gap.omitted_text}」({gap.omitted_type})，"
                f"卡点却是「{gap.card_one_line}」({gap.card_layer})",
            )

    notorious = [gap for gap in valid if gap.false_negatives]
    if notorious:
        lines += [
            "",
            "### 写了却被判「没写」的步骤（对齐器漏判）",
            "",
        ]
        for gap in notorious[:12]:
            for text in gap.false_negatives[:3]:
                lines.append(f"- `{gap.problem_id}`：{text}")

    if not valid:
        lines += ["", "本轮没有可计入的样本。", ""]
        return "\n".join(lines) + "\n"

    lines += [
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 覆盖召回（写了且被认出 / 写了） | {total_matched}/{total_written} = "
        f"{pct(total_matched, total_written)} |",
        f"| 平均单条召回 | {sum(recalls) / len(recalls):.2f} |",
        f"| 缺口被认成 `missing` | {len(detected)}/{len(valid)} = "
        f"{pct(len(detected), len(valid))} |",
        f"| 首个 `missing` 就是被跳过那步 | {len(first_hits)}/{len(valid)} = "
        f"{pct(len(first_hits), len(valid))} |",
        f"| 出卡 | {len(with_card)}/{len(valid)} = {pct(len(with_card), len(valid))} |",
        f"| 卡点落在被跳过那步 | {len(hits)}/{len(with_card)} = "
        f"{pct(len(hits), len(with_card)) if with_card else '-'} |",
        f"| 缺口语义对、卡点却指了别处 | {len(elsewhere)}/{len(detected)} |",
        f"| 单条耗时 p50 / p95 | {percentile(elapsed, 0.5)} / {percentile(elapsed, 0.95)} ms |",
        "",
        "## 怎么读这三个数",
        "",
        "- **覆盖召回**掉下来，说明对齐器在改写文本上会漏判——那是「把写了的步骤判成"
        "没写」，会直接把卡点推到更靠后的步骤；",
        "- **缺口被认出**是必要条件：跳过的那步没被认成 `missing`，后面都不用看了；",
        "- **卡点落在被跳过那步**才是「定位对」；出卡率不足时这一列样本变少，别把缺样本当成命中。",
        "",
        "## 仍未解决",
        "",
        "- 学生过程是模型扮演的，措辞比真实学生规整；真实学生的错法（写错而不是没写）"
        "仍然测不到——`TypeCueAligner` 只做存在性检查，这是已知边界。",
        "- 一条样本只跳过一步；真实学生常同时缺两三步，缺口之间的相互遮蔽没测。",
        "- 探针作答仍是 `aligned`，所以这张表不能当端到端诊断准确率引用。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="S5 ⑤ 缺口定位探针（构造真值）")
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "unseen-v0.2.jsonl"),
        help="题集 JSONL",
    )
    parser.add_argument("--limit", type=int, default=20, help="跑前 N 题")
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s5-gap-probe.md"),
        help="报告路径",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    container = build_container()
    client = OpenAICompatibleClient(container.settings)
    cases = load_cases(Path(args.problems))[: args.limit]

    gaps: list[Gap] = []
    for index, case in enumerate(cases):
        gap = run_gap(container, client, case, index)
        gaps.append(gap)
        status = "泄漏" if gap.leaked else ("ok" if not gap.detail else gap.detail[:40])
        print(
            f"[{index + 1}/{len(cases)}] {gap.problem_id or '?'} "
            f"skip={gap.omitted_id or '-'} recall={gap.recall:.2f} "
            f"gap={'Y' if gap.gap_detected else 'N'} "
            f"card={gap.card_layer or '-'}/{gap.card_node or '-'} "
            f"hit={'Y' if gap.card_hit else 'N'} {status}",
            flush=True,
        )

    report = _render(gaps, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    valid = [gap for gap in gaps if not gap.detail and not gap.leaked]
    with_card = [gap for gap in valid if gap.card_node]
    hits = [gap for gap in with_card if gap.card_hit]
    print()
    print(f"计入 {len(valid)} 条；出卡 {len(with_card)}；卡点命中 {len(hits)}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
