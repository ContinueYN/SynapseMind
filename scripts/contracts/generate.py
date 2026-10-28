"""Generate the TypeScript API contract from FastAPI.

Run from the repository root with the API venv available:

    python scripts/contracts/generate.py

It writes the local OpenAPI artifact, then asks ``openapi-typescript`` to
regenerate ``apps/web/src/lib/api/generated.ts``. The generated file is checked
in so a fresh clone can typecheck/build without running Python.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
EXPORT_SCRIPT = ROOT / "scripts" / "contracts" / "export_openapi.py"


def api_python() -> Path:
    if os.name == "nt":
        candidate = ROOT / "apps" / "api" / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ROOT / "apps" / "api" / ".venv" / "bin" / "python"
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def main() -> int:
    python = api_python()
    print(f"using {python}")
    subprocess.run([str(python), str(EXPORT_SCRIPT)], check=True, cwd=ROOT)

    npm = shutil.which("npm")
    if npm is None:
        print("npm was not found on PATH", file=sys.stderr)
        return 1
    subprocess.run(
        [npm, "run", "generate:api"],
        check=True,
        cwd=WEB,
        shell=os.name == "nt",
    )
    print("contracts updated: apps/web/src/lib/api/generated.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())