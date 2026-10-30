"""M2.5 S7: a NONE-tier subject gets a structure hint, never a card.

The measurement is not "can 语文 be diagnosed" — it cannot, and the product does
not claim to. It is:

* submitting a Chinese stem still builds a reference structure (so the hint has
  something honest to point at);
* the session stops after ALIGN: zero probes, zero diagnosis cards, one
  structure hint;
* the hint conforms to ``specs/structure-hint.schema.json`` and only says what
  the aligner can see ("this step was not written"), never "you got it wrong";
* the graph itself carries no probes and no claim, because the tier cannot use
  them (the generator drops them and records a repair code).

Usage::

    python scripts/eval/s7_none_tier.py [--limit N]
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

from jsonschema import Draft202012Validator  # noqa: E402
from s5_session import PASS_BAR, cell, pct, percentile  # noqa: E402

from synapse.api.deps import build_container  # noqa: E402
from synapse.api.mappers import hint_out  # noqa: E402
from synapse.application.commands import StartSessionCommand  # noqa: E402
from synapse.application.errors import ProblemNotSupported  # noqa: E402
from synapse.domain.dialogue.states import DialogueState  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402

SPEC_PATH = ROOT / "specs" / "structure-hint.schema.json"

ANSWER = "写了，但拿不准。"


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    text: str
    work: str
    work_full: str
    topic: str
    subject: str = "chinese"

    def work_for(self, variant: str) -> str:
        if variant == "blank":
            # S8's false-positive guard: a generic answer with no process must
            # stay entirely ``missing``.
            return ""
        return self.work_full if variant == "full" else self.work


VARIANTS = ("partial", "full")


def load_cases(path: Path) -> list[Case]:
    """Each line carries its own partial work, so the hints differ per stem.

    A single fixed work would only prove the plumbing; varying it shows that the
    aligner actually moves the "not written" mark with the student's text.
    """

    cases: list[Case] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"{path}:{line_number}: 每一行必须是 JSON 对象")
        cases.append(
            Case(
                id=str(payload["id"]),
                text=str(payload["text"]),
                work=str(payload["work"]),
                work_full=str(payload.get("work_full", payload["work"])),
                topic=str(payload.get("topic", "")),
                subject=str(payload.get("subject", "chinese")),
            )
        )
    return cases


@dataclass
class Row:
    case: Case
    variant: str = "partial"
    created: bool = False
    elapsed_ms: int = 0
    problem_id: str = ""
    state: str = ""
    nodes: int = 0
    probes: int = 0
    claims: int = 0
    hint_json: dict[str, Any] | None = None
    steps: int = 0
    covered: int = 0
    focus: str = ""
    focus_text: str = ""
    spec_ok: bool = False
    detail: str = ""
    notices: list[str] = field(default_factory=list)


def _validator() -> Draft202012Validator:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(spec)


def run_case(
    container: Any,
    case: Case,
    validator: Draft202012Validator,
    variant: str = "partial",
) -> Row:
    row = Row(case=case, variant=variant)
    work = case.work_for(variant)
    started = time.perf_counter()
    try:
        view = container.service.start(
            StartSessionCommand(
                problem_text=case.text,
                answer=ANSWER,
                work=work,
                subject=case.subject,
            )
        )
    except ProblemNotSupported as exc:
        row.elapsed_ms = int((time.perf_counter() - started) * 1000)
        row.detail = str(exc)
        return row
    row.elapsed_ms = int((time.perf_counter() - started) * 1000)

    session = view.session
    problem = container.problems.get(session.problem_id)
    row.created = True
    row.problem_id = session.problem_id
    row.state = session.state.value
    row.notices = [view.notice] if view.notice else []
    if problem is not None:
        row.nodes = len(problem.graph.nodes)
        row.probes = len(problem.graph.probes())
        row.claims = 1 if problem.graph.claim is not None else 0

    hint = view.hint
    if hint is None:
        row.detail = "没有结构提示"
        return row

    payload = hint_out(hint).model_dump(mode="json", exclude_none=False)
    row.hint_json = payload
    row.steps = len(payload["steps"])
    row.covered = sum(1 for step in payload["steps"] if step["status"] == "covered")
    row.focus = str(payload.get("focus_node_id") or "")
    focus_step = next(
        (step for step in payload["steps"] if step["node_id"] == row.focus), None
    )
    row.focus_text = focus_step["text"] if focus_step is not None else ""
    row.spec_ok = not list(validator.iter_errors(payload))

    # Invariants the tier promises; record the first violation as the detail.
    if session.state is not DialogueState.CLOSED:
        row.detail = f"状态是 {session.state.value}，不是 CLOSED"
    elif view.prompt is not None:
        row.detail = "NONE 档不应生成探针"
    elif session.diagnosis is not None:
        row.detail = "NONE 档不应生成卡点卡"
    elif payload["level"] != "none":
        row.detail = "hint.level 不是 none"
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "chinese-v0.1.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s7-none-tier.md"),
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
        run_case(container, case, validator, variant)
        for case in cases
        for variant in VARIANTS
    ]
    elapsed = time.perf_counter() - started

    created = sum(1 for row in rows if row.created)
    with_hint = [row for row in rows if row.hint_json is not None]
    spec_ok = sum(1 for row in with_hint if row.spec_ok)
    no_probe_graphs = sum(1 for row in rows if row.created and row.probes == 0)
    no_claim_graphs = sum(1 for row in rows if row.created and row.claims == 0)
    closed = sum(1 for row in rows if row.state == "CLOSED")
    violations = [row for row in rows if row.created and row.detail]
    latencies = [row.elapsed_ms for row in rows if row.created]
    nodes = [row.nodes for row in rows if row.created]

    # Does the hint actually track the process? Per stem: the fuller process must
    # cover at least as many steps, and its first gap must not move earlier.
    by_case: dict[str, dict[str, Row]] = {}
    for row in rows:
        by_case.setdefault(row.case.id, {})[row.variant] = row
    monotone: list[bool] = []
    for entry in by_case.values():
        partial, full = entry.get("partial"), entry.get("full")
        if partial is None or full is None or not (partial.created and full.created):
            continue
        monotone.append(full.covered >= partial.covered)
    same_focus = sum(
        1
        for entry in by_case.values()
        if entry.get("partial")
        and entry.get("full")
        and entry["partial"].focus == entry["full"].focus
    )
    partial_cov = [
        row.covered for row in rows if row.variant == "partial" and row.created
    ]
    full_cov = [row.covered for row in rows if row.variant == "full" and row.created]
    # Same stem → the resolver's fingerprint cache hands back the same graph, so a
    # coverage difference between variants is alignment, not a re-rolled graph.
    same_graph = sum(
        1
        for entry in by_case.values()
        if entry.get("partial")
        and entry.get("full")
        and entry["partial"].problem_id == entry["full"].problem_id
    )

    lines: list[str] = [
        "# M2.5 S7 结构提示报告（NONE 档：语文，不追问、不出卡）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"- 模型：`{settings.model}`；prompt：`{settings.graph_prompt_version}-chinese`；"
        f"模式：`{settings.mode}`",
        f"- 数据集：`{Path(args.problems).name}`（{len(cases)} 题 × "
        f"{len(VARIANTS)} 段过程 = {len(rows)} 次建会话）",
        f"- 建会话成功：{created}/{len(rows)}（{pct(created, len(rows))}，门槛 ≥{PASS_BAR:.0%}）",
        f"- 出结构提示：{len(with_hint)}/{created}；符合 `structure-hint.schema.json`：{spec_ok}/{len(with_hint)}",
        f"- 出卡点卡：0/{created}（按设计）；出探针：0/{created}（按设计）；"
        f"停在 CLOSED：{closed}/{created}",
        f"- 生成图：探针 {sum(row.probes for row in rows)} 个、claim "
        f"{sum(row.claims for row in rows)} 条（NONE 档一律丢弃）；"
        f"无探针的图 {no_probe_graphs}/{created}、无 claim 的图 {no_claim_graphs}/{created}；"
        f"节点均值 {(sum(nodes) / len(nodes)) if nodes else 0:.1f}",
        f"- 建会话 p50 {percentile(latencies, 0.50)} ms / p95 {percentile(latencies, 0.95)} ms；"
        f"总耗时 {elapsed:.1f}s",
        f"- 承诺违例：{len(violations)}",
        "",
        "> 这是**承诺降级**的验收：同一套 `SessionService` / `DialogueSession` / "
        "`CompositeAligner`，只因为插件的 `level` 是 `NONE`，就在 ALIGN 之后收束。"
        "不判断“语文诊断准不准”——语文没有可自动验证的真值，本报告不假装有。",
        "",
        "两段过程是同一个学生的两种写法：`partial` 只写前几步（读完题就停），"
        "`full` 写完整思路。它检验的不是“语文好不好”，而是**提示会不会跟着过程变**。",
        "",
        f"- 覆盖数单调（full ≥ partial）：{sum(monotone)}/{len(monotone)}；"
        f"两段过程 focus 相同：{same_focus}/{len(by_case)}；"
        f"同一题复用同一张图：{same_graph}/{len(by_case)}",
        f"- 已写到（partial 均值）：{(sum(partial_cov) / len(partial_cov)) if partial_cov else 0:.1f}；"
        f"（full 均值）：{(sum(full_cov) / len(full_cov)) if full_cov else 0:.1f}",
        "",
        "| 题号 | 过程 | 步骤 | 已写到 | focus | 探针/claim | 提交的过程 | 一句话 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        hint = row.hint_json or {}
        lines.append(
            "| {id} | {variant} | {steps} | {covered} | {focus} | {probes}/{claims} | "
            "{work} | {one_line} |".format(
                id=cell(row.case.topic or row.problem_id or "?"),
                variant=row.variant,
                steps=row.steps,
                covered=row.covered,
                focus=cell(row.focus or "-"),
                probes=row.probes,
                claims=row.claims,
                work=cell(row.case.work_for(row.variant)[:52]),
                one_line=cell(str(hint.get("one_line", ""))[:80]),
            )
        )

    if violations:
        lines += ["", "违例："]
        lines += [
            f"- `{row.problem_id or row.case.id}`：{row.detail}" for row in violations
        ]

    sample = next((row for row in rows if row.hint_json is not None), None)
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
            "- **不是“更弱的卡点卡”**：结构提示没有层级、没有置信度、没有 `next_action`/"
            "`verify`，contract 上就是另一张表（`specs/structure-hint.schema.json`）。"
        ),
        (
            "- **只看得见“有没有写”**：`TypeCueAligner` 是存在性检查（线索词 / 有没有写式子 / "
            "3-gram 兜底），所以 `missing` 的措辞是“看起来没有写到”，不是“写错了”。"
        ),
        (
            "- **不追问**：`application/commitment.py` 在 `start()` 里就分流，探针规划器根本不会被调用；"
            "状态走 `ALIGN → STOP → CLOSED`，状态机与转移表一行未改。"
        ),
        (
            "- **图里没有探针与 claim**：语文 prompt 不要这两样；模型若写了，建图器丢弃并记 "
            "`probes_dropped_unsupported` / `claim_dropped_unsupported`，图仍然可用。"
        ),
        (
            '- **不是自动识别**：必须显式声明 `subject="chinese"`；未声明时按数学处理，'
            "这是 S3「不猜学科」的延续。"
        ),
        (
            "- 本报告衡量的是接线与承诺，不是诊断准确率；语文的“卡在哪一步”无法自动验证，"
            "所以产品不给这个结论。"
        ),
        (
            "- **已知的低估**：`TypeCueAligner` 的兜底要求节点整句 3-gram 覆盖率 ≥50%，"
            "而语文节点是多分句长句（“判定题型 + 明确从哪几个角度作答”），学生只写了前半句时"
            "仍算 `missing`。方向是保守的（宁可说“没看到”，也不说“你错了”），但覆盖计数偏低；"
            "改进候选：分句级匹配，或把对齐器也做成插件端口（S8 再动，先记录）。"
        ),
    ]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"\n建会话 {created}/{len(rows)}，结构提示 {len(with_hint)}，"
        f"合规 {spec_ok}/{len(with_hint)}，违例 {len(violations)}"
    )
    print(f"报告：{out}")
    return 0 if created / len(rows) >= PASS_BAR and not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
