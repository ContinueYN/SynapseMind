"""M2.5 S5 ④: replay real student answers and review the cards.

``s5_session.py`` answers probes with the *aligned* policy, which proves the
wiring but cannot say whether a card is right: the simulated student always
agrees with whatever the aligner found. This script takes work a human actually
wrote — ``work`` is the student's own text, ``answer`` their final answer — and
reports, per answer:

* did a card come out, and which node/layer it points at;
* does that node contain the bottleneck a teacher marked
  (``expected_bottleneck``);
* did the student end up with the correct final answer
  (``final_correct``), which makes "卡点命中" and "答对了还指卡点" separable.

It writes a Markdown sheet whose last column (``人工判断``) is left blank on
purpose: the teacher fills 准确 / 说得通但不对 / 空泛, and only then is there a
diagnosis-accuracy number. Until ``source == "student"`` rows exist, everything
here is a pipeline test, and the report says so.

Input: ``eval/problems/student-answers-v0.1.jsonl``, one object per line::

    {"problem_id": "P_DERIV_002", "student_id": "s01",
     "answer": "极大值 2，极小值 -2", "work": "求导得 f'(x)=3x^2-6x ...",
     "expected_bottleneck": "讨论导数符号", "final_correct": false,
     "source": "student"}

Usage::

    cd apps/api
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_review.py
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_review.py --limit 5 --policy aligned
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from s5_session import Case, Row, cell, pct, run_case  # noqa: E402

from synapse.api.deps import build_container  # noqa: E402
from synapse.infrastructure.llm.settings import load_dotenv  # noqa: E402

ANSWERS_TEMPLATE = """\
{"problem_id": "P_DERIV_002", "student_id": "s01", "source": "synthetic", "final_correct": false,
 "answer": "极大值 2，极小值 -2",
 "work": "先求导 f'(x)=3x^2-6x，令它等于 0 得 x=0 或 x=2，然后代入算出两个极值。",
 "expected_bottleneck": "导数符号"}
"""


@dataclass(frozen=True, slots=True)
class Answer:
    problem_id: str
    student_id: str
    answer: str
    work: str
    expected_bottleneck: str
    final_correct: bool | None
    source: str
    source_url: str = ""


@dataclass
class Review:
    answer: Answer
    row: Row
    node_text: str = ""
    hit: bool | None = None


def load_problems(path: Path) -> dict[str, dict[str, Any]]:
    problems: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        payload = json.loads(raw)
        problems[str(payload["id"])] = payload
    return problems


def _payloads(path: Path) -> list[dict[str, Any]]:
    """JSONL, or CSV with a header row — whichever the reviewer finds easier.

    The CSV path exists so a teacher can fill a spreadsheet instead of writing
    JSON by hand; columns are the same field names as the JSONL rows.
    """

    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows: list[dict[str, Any]] = []
        for row in csv.DictReader(io.StringIO(text)):
            rows.append({key: (value or "") for key, value in row.items() if key})
        return [row for row in rows if any(str(v).strip() for v in row.values())]
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"{path}: 每一行必须是 JSON 对象")
        payloads.append(payload)
    return payloads


def _as_bool(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "对", "正确"}


def load_answers(path: Path) -> list[Answer]:
    answers: list[Answer] = []
    for line_number, payload in enumerate(_payloads(path), start=1):
        answers.append(
            Answer(
                problem_id=str(payload["problem_id"]).strip(),
                student_id=str(payload.get("student_id") or f"line{line_number}").strip(),
                answer=str(payload.get("answer", "")),
                work=str(payload.get("work", "")),
                expected_bottleneck=str(payload.get("expected_bottleneck", "")),
                final_correct=_as_bool(payload.get("final_correct")),
                source=str(payload.get("source") or "unknown").strip(),
                source_url=str(payload.get("source_url") or "").strip(),
            )
        )
    return answers


def _normalise(text: str) -> str:
    return "".join(text.split()).lower()


def matches(expected: str, node_text: str, one_line: str) -> bool:
    """Substring match, whitespace-insensitive.

    Not semantic on purpose: a teacher writing ``导数符号`` should hit a node
    that says ``讨论导数的符号``, but nothing here should paper over a card that
    names a different step.
    """

    if not expected:
        return False
    key = _normalise(expected)
    return key in _normalise(node_text) or key in _normalise(one_line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--problems",
        default=str(ROOT / "eval" / "problems" / "unseen-v0.2.jsonl"),
        help="题目集（带 expected_answer），默认 v0.2 的 100 题",
    )
    parser.add_argument(
        "--answers",
        default=str(ROOT / "eval" / "problems" / "student-answers-v0.1.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--policy", choices=("aligned", "first"), default="aligned")
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s5-student-review.md"),
    )
    args = parser.parse_args()

    answers_path = Path(args.answers)
    if not answers_path.exists():
        answers_path.parent.mkdir(parents=True, exist_ok=True)
        answers_path.write_text(ANSWERS_TEMPLATE, encoding="utf-8")
        print(f"没有作答文件，已写模板：{answers_path}")
        print("把 source 改成 student 并填入真实作答后再跑。")
        return 2

    problems = load_problems(Path(args.problems))
    answers = load_answers(answers_path)
    unknown = sorted({entry.problem_id for entry in answers} - set(problems))
    if unknown:
        print("! 这些题目 id 不在题目集里：" + ", ".join(unknown))
        return 2
    if args.limit:
        answers = answers[: args.limit]

    load_dotenv()
    container = build_container()
    reviews: list[Review] = []
    for entry in answers:
        problem = problems[entry.problem_id]
        case = Case(
            text=str(problem["text"]),
            topic=str(problem.get("topic", "")),
            subject=str(problem.get("subject", "math")),
            work=entry.work,
            answer=entry.answer,
        )
        row = run_case(container, case, policy=args.policy)
        node_text = ""
        if row.card is not None and row.problem_id:
            resolved = container.problems.get(row.problem_id)
            if resolved is not None:
                try:
                    node_text = resolved.graph.node(row.card["node_id"]).text
                except KeyError:
                    node_text = ""
        hit: bool | None = None
        if entry.expected_bottleneck and row.card is not None:
            hit = matches(entry.expected_bottleneck, node_text, str(row.card["one_line"]))
        reviews.append(Review(answer=entry, row=row, node_text=node_text, hit=hit))
        state = "出卡" if row.card else "未出卡"
        print(
            f"{entry.problem_id}/{entry.student_id}: {state} ({row.turns} 轮, {row.elapsed_ms} ms)"
        )

    report = _render(
        reviews,
        problems=problems,
        problems_path=Path(args.problems),
        answers_path=answers_path,
        policy=args.policy,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"report: {out}")
    return 0


def _render(
    reviews: list[Review],
    *,
    problems: dict[str, dict[str, Any]],
    problems_path: Path,
    answers_path: Path,
    policy: str,
) -> str:
    sources = Counter(review.answer.source for review in reviews)
    real = sources.get("student", 0) + sources.get("public-web", 0)
    public = sources.get("public-web", 0)
    cards = [review for review in reviews if review.row.card is not None]
    marked = [review for review in reviews if review.answer.expected_bottleneck]
    hits = [review for review in marked if review.hit]
    lines = [
        "# M2.5 S5 ④ 真实学生作答复盘",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 题目集：`{problems_path.name}`（{len(problems)} 题）",
        f"- 作答：`{answers_path.name}`（{len(reviews)} 条；来源 {dict(sources)}）",
        f"- 作答策略：`{policy}`（探针按对齐结论选，学生只贡献自我陈述与最终答案）",
        f"- 出卡：{len(cards)}/{len(reviews)}；卡点落在图上："
        f"{sum(1 for review in cards if review.row.node_in_graph)}/{len(cards)}",
        f"- 标了期望卡点的：{len(marked)} 条，命中 {len(hits)} 条",
        "",
        "> `source=student` 是同一批题的真实复盘；`public-web` 是公开问答页里学生自己写的原话"
        "（题目与学生不是同一批抽样，只能小样本粗检）；`synthetic` 只验管线，不能当准确率。"
        f"本轮真实作答 {real} 条（其中公开抓取 {public} 条）。",
        "",
        "| 题 | 学生 | 最终答案 | 期望答案 | 出卡 | 卡点层 | 卡面一句 | 期望卡点 | "
        "命中 | 人工判断 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for review in reviews:
        entry = review.answer
        expected_answer = str(problems[entry.problem_id].get("expected_answer", ""))
        if review.row.card is None:
            lines.append(
                f"| {entry.problem_id} | {entry.student_id} | {cell(entry.answer)} | "
                f"{cell(expected_answer)} | 否 | — | — | "
                f"{cell(entry.expected_bottleneck) or '—'} | — | 待填 |"
            )
            continue
        card = review.row.card
        hit = "—" if not entry.expected_bottleneck else ("是" if review.hit else "否")
        lines.append(
            f"| {entry.problem_id} | {entry.student_id} | {cell(entry.answer)} | "
            f"{cell(expected_answer)} | 是 | {card['layer']} | {cell(str(card['one_line']))} | "
            f"{cell(entry.expected_bottleneck)} | {hit} | 待填 |"
        )

    flagged: list[str] = []
    for review in reviews:
        if review.answer.final_correct is None or review.row.card is None:
            continue
        if review.answer.final_correct and review.row.card["layer"] == "L2":
            flagged.append(
                f"{review.answer.problem_id}/{review.answer.student_id}（答对但指出卡点）"
            )
        elif not review.answer.final_correct and review.row.card["layer"] != "L2":
            flagged.append(
                f"{review.answer.problem_id}/{review.answer.student_id}"
                f"（答错但只给出 {review.row.card['layer']}）"
            )

    lines += [
        "",
        "## 口径",
        "",
        "- `work` 是学生自己写的原文，`answer` 是他的最终答案；探针仍由 `--policy` 代答，"
        "因为探针问的是「你怎么想」，这一层无法从一段书面过程里还原。",
        "- 「命中」只做**去空白的子串匹配**：期望卡点写「导数符号」，节点写「讨论导数的符号」"
        "算命中；写别的步骤就不算。不是语义判断，宁可漏判。",
        "- 只有 `人工判断` 列（准确 / 说得通但不对 / 空泛）填完，才能算诊断准确率；"
        "在那之前，「出卡率」和「命中率」都只是**代理指标**。",
        "- 现在的 20/20 出卡来自 `aligned` 策略（模拟学生总是顺着对齐结论答题），"
        "那不是诊断准确率。",
    ]
    if flagged:
        lines += ["", "## 值得人工复核的自动告警", ""]
        lines += [f"- {item}" for item in flagged]
    cited = [review for review in reviews if review.answer.source_url]
    if cited:
        lines += ["", "## 学生原话的出处", "", "| 题 | 学生 | 来源 |", "|---|---|---|"]
        lines += [
            f"| {review.answer.problem_id} | {review.answer.student_id} | "
            f"{review.answer.source_url} |"
            for review in cited
        ]
        lines += [
            "",
            "> 公开问答页里的学生原话，只摘了与卡点相关的几句；题目文本按原题整理。"
            "这比 `synthetic` 强（错法和卡点是学生自己说的），但仍不是同一批题、"
            "同一批学生的抽样，只能当小样本粗检。",
        ]
    lines += [
        "",
        f"出卡率 {pct(len(cards), len(reviews))}，命中率 "
        f"{pct(len(hits), len(marked)) if marked else '-'}。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
