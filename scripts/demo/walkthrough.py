"""Run a few student journeys in-process and write a Markdown transcript.

This is the demo/regression entry point, not an accuracy benchmark:

    python scripts/demo/walkthrough.py                  # all, live if a key exists
    python scripts/demo/walkthrough.py --no-live        # annotated + blank only
    python scripts/demo/walkthrough.py --case physics --out var/demo/physics.md

It talks to ``SessionService`` directly (no HTTP, no browser, no database), so
the transcript is exactly what the shipped application layer produced. Live
cases are skipped, not faked, when no model is available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from synapse.api.deps import build_container
from synapse.application.commands import (
    StartSessionCommand,
    SubmitAnswerCommand,
    VerifyStepCommand,
)
from synapse.application.service import SessionService, SessionView
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv
from synapse.infrastructure.seed import SAMPLE_PROBLEM

WRONG_WORK = (
    "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。"
    "a>0 时最大值为 -ln a-1≤0，所以 a≥1/e。"
)
PHYSICS_TEXT = (
    "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，"
    "动摩擦因数 0.2，求物块的加速度。"
)
CHINESE_TEXT = "阅读下面的文字，完成题目：文中两次写到“灯”，请结合全文简要分析其作用。"

CASES = ("wrong", "blank", "physics", "chinese")


class Transcript:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, line: str = "") -> None:
        self.lines.append(line)

    def heading(self, text: str) -> None:
        self.add(f"## {text}")
        self.add()

    def bullets(self, items: list[str]) -> None:
        for item in items:
            self.add(f"- {item}")
        self.add()

    def turn(
        self,
        *,
        state: str,
        question: str,
        choice: str = "",
        top: str = "",
        note: str = "",
    ) -> None:
        self.add(f"| {state} | {question} | {choice} | {top} | {note} |")

    def table_header(self) -> None:
        self.add("| 状态 | 系统动作 | 选择 | 顶层假设 | 备注 |")
        self.add("|---|---|---|---|---|")


def _top(view: SessionView) -> str:
    top_id, posterior = view.session.hypotheses.top()
    return f"{top_id} {posterior:.2f}"


def _answer_loop(
    service: SessionService,
    view: SessionView,
    transcript: Transcript,
    *,
    max_turns: int = 6,
) -> SessionView:
    """Choose A for each probe so the transcript reaches a stop or a card."""
    for _ in range(max_turns):
        if view.diagnosis is not None or view.prompt is None:
            return view
        prompt = view.prompt
        choice = "A"
        text = prompt.options[0] if prompt.options else ""
        transcript.turn(
            state=view.session.state.value,
            question=prompt.question,
            choice=f"{choice}. {text}",
            top=_top(view),
            note=prompt.reason_code,
        )
        view = service.submit(
            view.session.session_id,
            SubmitAnswerCommand(answer=choice, option_id=choice),
        )
    return view


def _render_card(view: SessionView, transcript: Transcript) -> None:
    transcript.add()
    card = view.diagnosis
    if card is None:
        transcript.add(f"没有出卡；当前状态 `{view.session.state.value}`。")
        transcript.add()
        return
    transcript.add(
        f"**卡点**：{card.label}（`{card.layer}`，置信 {card.confidence:.2f}）"
    )
    transcript.add()
    transcript.add(f"> {card.one_line}")
    transcript.add()
    transcript.bullets(
        [
            f"位置：`{card.node_id}`",
            *[f"证据：{item}" for item in card.evidence],
            f"下一步：`{json.dumps(card.next_action, ensure_ascii=False)}`",
        ]
    )


def _run_wrong(service: SessionService, transcript: Transcript) -> bool:
    transcript.heading("1. 标注题：错步 → 探针 → 卡点卡（离线）")
    started = perf_counter()
    view = service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="a≥1/e",
            work=WRONG_WORK,
            self_report="correct_but_guessed",
        )
    )
    transcript.bullets(
        [
            f"题目：{SAMPLE_PROBLEM.text}",
            f"学生答案：`a≥1/e`；过程：{WRONG_WORK}",
            f"进入状态：`{view.session.state.value}`",
        ]
    )
    transcript.table_header()
    view = _answer_loop(service, view, transcript)
    _render_card(view, transcript)

    verdict = service.verify_step(
        view.session.session_id,
        VerifyStepCommand(
            text="1/x = 1/x + 1",
            node_id=view.diagnosis.node_id if view.diagnosis else "",
        ),
    )
    exited = service.exit(view.session.session_id)
    transcript.bullets(
        [
            f"单步验证：`{verdict.status}` — {verdict.detail}",
            f"显式退出：`{exited.session.state.value}`；{exited.notice}",
            f"耗时：{perf_counter() - started:.2f}s",
        ]
    )
    return view.diagnosis is not None


def _run_blank(service: SessionService, transcript: Transcript) -> bool:
    transcript.heading("2. 空白入口：先示例，再交回一行（离线）")
    started = perf_counter()
    view = service.start(
        StartSessionCommand(
            problem_text=SAMPLE_PROBLEM.text,
            answer="不会",
            self_report="no_idea",
        )
    )
    if view.scaffold is None:
        transcript.add("没有进入 `SCAFFOLD`：空白分支失效。")
        return False
    transcript.bullets(
        [
            f"进入状态：`{view.session.state.value}`",
            "示例只展示起步，不是本题答案：",
            *[f"{step.label}：{step.text}" for step in view.scaffold.steps],
            f"下一步：{view.scaffold.next_step}",
        ]
    )
    view = service.submit(
        view.session.session_id,
        SubmitAnswerCommand(answer="定义域 x>0；先找 f(x) 的最大值。"),
    )
    transcript.bullets(
        [
            f"提交一行后：`{view.session.state.value}`",
            f"下一问：{view.prompt.question if view.prompt else '无'}",
            f"耗时：{perf_counter() - started:.2f}s",
        ]
    )
    return view.prompt is not None


def _run_live(
    service: SessionService,
    transcript: Transcript,
    *,
    title: str,
    text: str,
    answer: str,
    work: str,
    expect: str,
) -> bool:
    transcript.heading(title)
    started = perf_counter()
    view = service.start(
        StartSessionCommand(
            problem_text=text,
            answer=answer,
            work=work,
            self_report=None if work else "no_idea",
        )
    )
    transcript.bullets(
        [
            f"题目：{text}",
            f"进入状态：`{view.session.state.value}`；学科：`{service.problem_subject(view.session.problem_id)}`",
        ]
    )
    if view.scaffold is not None:
        transcript.bullets([f"示例：{step.text}" for step in view.scaffold.steps])
    if view.hint is not None:
        transcript.bullets(
            [
                f"结构提示：{view.hint.one_line}",
                f"下一步：{view.hint.next_step}",
                "固定免责声明：" + view.hint.disclaimer,
            ]
        )
    if view.prompt is not None:
        started_with_prompt = True
        transcript.table_header()
        view = _answer_loop(service, view, transcript)
        _render_card(view, transcript)
    else:
        started_with_prompt = False

    ok = {
        "card": view.diagnosis is not None,
        "hint": view.hint is not None,
        # A live probe can legitimately end in STOP/CLOSED without a card; the
        # demo still proves start -> graph -> at least one real question.
        "prompt": started_with_prompt or view.diagnosis is not None,
    }[expect]
    transcript.bullets([f"耗时：{perf_counter() - started:.2f}s"])
    return ok


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=("all", *CASES),
        default="all",
        help="which journey to run (default: all)",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="never call the model, even when a key is present",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("var/demo/walkthrough.md"),
        help="Markdown output path",
    )
    args = parser.parse_args()

    load_dotenv()
    # The demo wants to show the step verifier, not the default-off switch. An
    # explicit SYNAPSE_EQUALITY_CHECK=off still wins via setdefault.
    os.environ.setdefault("SYNAPSE_EQUALITY_CHECK", "on")
    settings = LLMSettings.from_env()
    # This is an explicit demo entry point: a present key is enough to run the
    # live cases, unless the caller says --no-live. Production still defaults to
    # SYNAPSE_LLM_MODE=off.
    live_available = bool(settings.api_key) and not args.no_live
    if live_available and settings.mode == "off":
        settings = replace(settings, mode="on")
    if args.no_live:
        settings = replace(settings, mode="off")

    container = build_container(settings)
    service = container.service
    transcript = Transcript()
    transcript.add("# SynapseMind walkthrough")
    transcript.add()
    transcript.bullets(
        [
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"模型：{'on' if live_available else 'off（离线/未配置 key）'}",
            "说明：这是链路 transcript，不是诊断准确率；生成的题目没有人工复核。",
        ]
    )

    selected = CASES if args.case == "all" else (args.case,)
    results: list[bool] = []
    skipped: list[str] = []

    if "wrong" in selected:
        results.append(_run_wrong(service, transcript))
    if "blank" in selected:
        results.append(_run_blank(service, transcript))
    if "physics" in selected:
        if live_available:
            results.append(
                _run_live(
                    service,
                    transcript,
                    title="3. 物理：无声明学科 → 自动识别 → 建图 → 追问/卡点（实时）",
                    text=PHYSICS_TEXT,
                    answer="a=5 m/s^2",
                    work="先读题，标出已知量。",
                    expect="prompt",
                )
            )
        else:
            skipped.append("physics")
    if "chinese" in selected:
        if live_available:
            results.append(
                _run_live(
                    service,
                    transcript,
                    title="4. 语文：自动识别为 NONE 档 → 只给结构提示（实时）",
                    text=CHINESE_TEXT,
                    answer="不会",
                    work="",
                    expect="hint",
                )
            )
        else:
            skipped.append("chinese")

    transcript.add("## 结果")
    transcript.add()
    transcript.bullets(
        [
            f"通过：{sum(results)}/{len(results)}",
            "跳过（无可用模型）：" + (", ".join(skipped) if skipped else "无"),
        ]
    )
    _write(args.out, "\n".join(transcript.lines) + "\n")
    print(f"wrote {args.out} ({sum(results)}/{len(results)} passed, skipped={skipped})")
    return 0 if all(results) and (bool(results) or skipped) else 1


if __name__ == "__main__":
    raise SystemExit(main())
