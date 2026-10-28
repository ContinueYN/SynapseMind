#!/usr/bin/env python3
"""Merge docs/design/chapters/*.md into the release Markdown.

The chapters are the single source of truth. `generate_docx.py` reads the
merged Markdown, so run this before generating DOCX/PDF.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = ROOT / "docs" / "design" / "chapters"
DST = ROOT / "docs" / "design" / "release" / "SynapseMind-单题诊断引导-设计方案.md"


def main() -> int:
    files = sorted(CHAPTERS.glob("*.md"))
    if not files:
        raise SystemExit(f"no chapters under {CHAPTERS}")

    parts = [path.read_text(encoding="utf-8").strip() for path in files]
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text("\n\n".join(parts) + "\n", encoding="utf-8")

    print(f"merged {len(files)} chapters -> {DST}")
    for path in files:
        print(f"  + {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())