"""Render the local card-disagreement queue as a review sheet.

The API appends one row when a student disagrees with a card. The row contains
the card's conclusion and location, not the student's work. The last column is
left blank for a teacher to mark 准确 / 说得通但不对 / 空泛.

Usage::

    python scripts/eval/review_queue.py
    python scripts/eval/review_queue.py --db var/review.sqlite3 --out eval/reports/review.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from synapse.application.review import ReviewItem  # noqa: E402
from synapse.infrastructure.review import SqliteReviewQueue  # noqa: E402


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render(items: list[ReviewItem]) -> str:
    lines = [
        "# 卡点卡异议复核",
        "",
        "> 来源：学生点击「我不同意」；不含学生原文。最后一列留给教师填写。",
        "",
        f"共 {len(items)} 条。",
        "",
        "| 时间 | 会话 | 题目 | 层级 | 节点 | 置信 | 卡面结论 | 人工判断 |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {_cell(item.created_at)} | `{_cell(item.session_id)}` | "
            f"`{_cell(item.problem_id)}` | {_cell(item.layer)} | "
            f"`{_cell(item.node_id)}` | {item.confidence:.2f} | "
            f"{_cell(item.one_line)} |  |"
        )
    if not items:
        lines.append("| — | — | — | — | — | — | 暂无异议记录 |  |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "var" / "review.sqlite3")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    text = render(SqliteReviewQueue(args.db).items())
    if args.out is None:
        print(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
