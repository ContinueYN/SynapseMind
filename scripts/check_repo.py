#!/usr/bin/env python3
"""Repository consistency checks for the SynapseMind design repo.

No third-party dependencies. Run from anywhere:
    python scripts/check_repo.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".gitignore",
    "docs/README.md",
    "docs/adr/README.md",
    "docs/adr/0001-language-and-code-architecture.md",
    "docs/design/README.md",
    "docs/design/chapters/00-一页纸.md",
    "docs/design/chapters/08-skill映射.md",
    "docs/design/release/SynapseMind-单题诊断引导-设计方案.md",
    "docs/design/release/SynapseMind-单题诊断引导-设计方案.docx",
    "docs/design/release/SynapseMind-单题诊断引导-设计方案.pdf",
    "docs/design/assets/01-dialogue-loop.png",
    "docs/design/assets/02-diagnosis-engine.png",
    "docs/design/assets/03-architecture.png",
    "specs/dialogue-state.md",
    "specs/problem-input.schema.json",
    "specs/solution-graph.schema.json",
    "specs/diagnosis.schema.json",
    "tools/generate_docx.py",
    "tools/merge_markdown.py",
    "tools/diagrams.py",
]

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SKILL_ROW_RE = re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|", re.MULTILINE)

SKIP_DIRS = {
    ".git",
    ".tmp",
    "node_modules",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "docs/archive",
}


def walk_markdown() -> list[Path]:
    roots = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "adr",
        ROOT / "docs" / "design",
        ROOT / "docs" / "reference",
        ROOT / "specs",
        ROOT / "apps",
        ROOT / "services",
        ROOT / "packages",
        ROOT / "eval",
        ROOT / "infra",
        ROOT / "scripts",
        ROOT / "tools",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            rel = path.relative_to(ROOT).as_posix()
            if any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
                continue
            files.append(path)
    return sorted(set(files))


def check_required(errors: list[str]) -> None:
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")


def check_json(errors: list[str]) -> None:
    for path in sorted((ROOT / "specs").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report the concrete parse error
            errors.append(f"invalid JSON: {path.relative_to(ROOT)}: {exc}")


def check_links(errors: list[str], warnings: list[str]) -> int:
    checked = 0
    for path in walk_markdown():
        text = path.read_text(encoding="utf-8")
        for raw in LINK_RE.findall(text):
            link = raw.strip().strip("<>")
            if not link:
                continue
            if link.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            target_part = link.split("#", 1)[0].strip()
            if not target_part:
                continue
            checked += 1
            target = (
                (ROOT / target_part.lstrip("/"))
                if target_part.startswith("/")
                else (path.parent / target_part)
            ).resolve()
            if not target.exists():
                errors.append(
                    f"broken link: {path.relative_to(ROOT)} -> {raw}"
                )
    return checked


def check_skill_mapping(errors: list[str]) -> int:
    path = ROOT / "docs" / "design" / "chapters" / "08-skill映射.md"
    if not path.is_file():
        return 0
    rows = SKILL_ROW_RE.findall(path.read_text(encoding="utf-8"))
    expected = [str(i) for i in range(1, 12)]
    if rows != expected:
        errors.append(f"skill mapping rows are {rows}, expected {expected}")
    return len(rows)


def check_images(errors: list[str]) -> None:
    for rel in REQUIRED:
        if rel.endswith(".png"):
            data = (ROOT / rel).read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                errors.append(f"not a PNG: {rel}")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    check_required(errors)
    check_json(errors)
    links = check_links(errors, warnings)
    skill_rows = check_skill_mapping(errors)
    check_images(errors)

    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("OK")
    print(f"  markdown files: {len(walk_markdown())}")
    print(f"  relative links: {links}")
    print(f"  skill rows: {skill_rows}")
    print(f"  specs: {len(list((ROOT / 'specs').glob('*.json')))} json")
    for item in warnings:
        print(f"  warn: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())