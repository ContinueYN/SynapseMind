#!/usr/bin/env python3
"""Build a clean, public copy of the repository.

The main checkout keeps the product/design/evaluation material that should not
be published. This script copies only the runnable code, public docs, and the
public CI workflow into a separate directory with a fresh history.

Usage:
    python scripts/release/export_public.py
    python scripts/release/export_public.py --target ../SynapseMind-public
    python scripts/release/export_public.py --target ../SynapseMind-public --force
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = ROOT.parent / "SynapseMind-public"
TEMPLATES = ROOT / "scripts" / "release" / "templates"

EXCLUDED_DIRS = {
    ".next",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".import_linter_cache",
    ".turbo",
    "coverage",
    "test-results",
    "playwright-report",
}
EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    ".env",
    ".env.local",
    ".eslintcache",
    "*.tsbuildinfo",
}
TOP_LEVEL_FILES = [
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    ".gitignore",
    ".editorconfig",
    ".gitattributes",
]


def _ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        if path.is_dir() and name in EXCLUDED_DIRS:
            ignored.add(name)
        elif name in EXCLUDED_FILES or name.endswith((".log", ".pid", ".tsbuildinfo")):
            ignored.add(name)
        elif name.startswith(".env"):
            ignored.add(name)
    return ignored


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=_ignore)


def _copy_public_scripts(target: Path) -> None:
    scripts = target / "scripts"
    scripts.mkdir()
    public_scripts = (
        "dev/run.py",
        "dev/run.ps1",
        "contracts/generate.py",
        "contracts/export_openapi.py",
        "checks/check_repo.py",
    )
    for rel in public_scripts:
        destination = scripts / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / rel, destination)
    shutil.copy2(TEMPLATES / "README.scripts.md", scripts / "README.md")


def _remove_readonly(func, path: str, _exc_info) -> None:
    """Git marks object files read-only on Windows; clear the bit and retry."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _validate_target(target: Path, force: bool) -> None:
    resolved = target.resolve()
    root = ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise SystemExit("refusing to export inside the private checkout")
    if resolved.exists() and any(resolved.iterdir()):
        if not force:
            raise SystemExit(
                f"target is not empty: {resolved}\n"
                "Pass --force to replace it after checking the path."
            )
        shutil.rmtree(resolved, onerror=_remove_readonly)


def export(target: Path, force: bool) -> None:
    _validate_target(target, force)
    target.mkdir(parents=True, exist_ok=True)

    for name in TOP_LEVEL_FILES:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, target / name)

    _copy_tree(ROOT / "apps", target / "apps")
    _copy_tree(ROOT / "infra", target / "infra")
    _copy_tree(ROOT / "specs", target / "specs")
    _copy_tree(ROOT / "docs" / "adr", target / "docs" / "adr")
    _copy_public_scripts(target)

    workflows = target / ".github" / "workflows"
    workflows.mkdir(parents=True)
    shutil.copy2(TEMPLATES / "ci.public.yml", workflows / "ci.yml")

    shutil.copy2(TEMPLATES / "README.public.md", target / "README.md")
    shutil.copy2(TEMPLATES / "CONTRIBUTING.public.md", target / "CONTRIBUTING.md")
    (target / ".public-repo").write_text(
        "This checkout contains only the files intended for the public repository.\n"
        "The private design/eval material lives outside this tree.\n",
        encoding="utf-8",
    )

    print(f"public export: {target}")
    app_files = sum(1 for path in (target / "apps").rglob("*") if path.is_file())
    print(f"  apps: {app_files} files")
    print("  next: git init, review, commit, then add the remote")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    export(args.target.resolve(), args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())