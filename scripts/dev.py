"""One-command local development launcher.

    python scripts/dev.py

Creates the API venv if needed, installs dependencies on first run, starts
FastAPI and Next.js, and waits until both are reachable. Ctrl+C stops both.
Use ``--check`` to verify prerequisites without changing anything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
WEB = ROOT / "apps" / "web"


def api_python() -> Path:
    if os.name == "nt":
        return API / ".venv" / "Scripts" / "python.exe"
    return API / ".venv" / "bin" / "python"


def _run(cmd: list[str] | str, cwd: Path, *, shell: bool = False) -> None:
    print(f"$ {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, shell=shell, check=True)


def prepare_api(no_install: bool) -> Path:
    python = api_python()
    if not python.is_file():
        print("creating apps/api/.venv ...")
        subprocess.run([sys.executable, "-m", "venv", str(API / ".venv")], check=True)
    if no_install:
        return python
    probe = subprocess.run(
        [str(python), "-c", "import fastapi, uvicorn"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        _run([str(python), "-m", "pip", "install", "-e", ".[dev]"], API)
    return python


def prepare_web(no_install: bool) -> str:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("Node.js/npm was not found on PATH; install Node.js 22+.")
    if not no_install and not (WEB / "node_modules").is_dir():
        _run([npm, "install"], WEB, shell=os.name == "nt")
    return npm


def wait_for(url: str, *, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError(f"service did not become ready: {url}")


def _spawn_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_tree(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def check() -> int:
    python = api_python()
    npm = shutil.which("npm")
    warnings: list[str] = []
    problems: list[str] = []
    if not python.is_file():
        warnings.append("apps/api/.venv is missing; normal start will create it")
    if npm is None:
        problems.append("npm is missing from PATH")
    if not (WEB / "src" / "lib" / "api" / "generated.ts").is_file():
        problems.append(
            "generated API types are missing; run python scripts/contracts.py"
        )
    print(f"python: {python}")
    print(f"npm:    {npm}")
    print(f"api:    {(API / 'pyproject.toml').is_file()}")
    print(f"web:    {(WEB / 'package.json').is_file()}")
    for warning in warnings:
        print(f"WARN {warning}")
    if problems:
        for problem in problems:
            print(f"ERROR {problem}")
        return 1
    print("OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check prerequisites only")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="start both, wait until ready, then stop (for verification)",
    )
    parser.add_argument("--no-install", action="store_true", help="skip dependency install")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3000)
    args = parser.parse_args()

    if args.check:
        return check()

    python = prepare_api(args.no_install)
    npm = prepare_web(args.no_install)

    env = os.environ.copy()
    env["SYNAPSE_WEB_ORIGINS"] = (
        f"http://localhost:{args.web_port},http://127.0.0.1:{args.web_port}"
    )
    env["NEXT_PUBLIC_API_BASE"] = f"http://localhost:{args.api_port}"

    api_cmd = [
        str(python),
        "-m",
        "uvicorn",
        "synapse.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.api_port),
        "--reload",
    ]
    web_cmd = f'"{npm}" run dev -- --port {args.web_port}'
    print(f"API  http://localhost:{args.api_port}")
    print(f"Web  http://localhost:{args.web_port}")
    print("Ctrl+C to stop both.\n")

    api = subprocess.Popen(api_cmd, cwd=API, env=env, **_spawn_kwargs())
    web = subprocess.Popen(web_cmd, cwd=WEB, env=env, shell=True, **_spawn_kwargs())
    try:
        wait_for(f"http://127.0.0.1:{args.api_port}/api/v1/health")
        wait_for(f"http://127.0.0.1:{args.web_port}/")
        print("\nready: open http://localhost:%d\n" % args.web_port)
        if args.smoke:
            return 0
        while True:
            if api.poll() is not None:
                raise RuntimeError(f"API exited with {api.returncode}")
            if web.poll() is not None:
                raise RuntimeError(f"Web exited with {web.returncode}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping ...")
        return 0
    finally:
        for process in (web, api):
            stop_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())