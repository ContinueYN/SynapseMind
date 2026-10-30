"""M2.5 S6 follow-up: fixed positive/negative checks for the physics verifier.

No model key and no network: this is a fast smoke test for the PARTIAL step
verifier. It checks the three verdicts and the two failure modes that matter:

* dimension mismatch  -> fail
* numeric contradiction -> fail
* missing/invalid data -> unknown

Usage::

    cd apps/api
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s6_verifier.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from synapse.application.subject import StudentStep  # noqa: E402
from synapse.infrastructure.subjects.physics import PhysicsPlugin  # noqa: E402

FORCE = {
    "equation": "F*cos(theta) - mu*N = m*a",
    "units": {
        "F": "N",
        "theta": "deg",
        "mu": "",
        "N": "N",
        "m": "kg",
        "a": "m/s^2",
    },
    "values": {"F": 10, "theta": 60, "mu": 0.2, "N": 10, "m": 2, "a": 1.5},
}

CASES: list[tuple[str, dict[str, object] | None, str]] = [
    ("量纲 + 数值回代通过", FORCE, "pass"),
    (
        "量纲错误：F = q/E",
        {"equation": "F = q/E", "units": {"F": "N", "q": "C", "E": "N/C"}},
        "fail",
    ),
    (
        "数值不成立：a 代错",
        {**FORCE, "values": {**FORCE["values"], "a": 2.0}},
        "fail",
    ),
    (
        "结果单位/数值一致",
        {
            "expression": "v",
            "unit": "m/s",
            "units": {"v": "m/s"},
            "values": {"v": 5},
            "expected": {"value": 18, "unit": "km/h"},
        },
        "pass",
    ),
    (
        "结果值与声明不符",
        {
            "expression": "v",
            "unit": "m/s",
            "units": {"v": "m/s"},
            "values": {"v": 5},
            "expected": {"value": 20, "unit": "km/h"},
        },
        "fail",
    ),
    ("纯文本没有结构化数据", None, "unknown"),
    (
        "缺单位",
        {"equation": "F = m*a", "units": {"m": "kg", "a": "m/s^2"}},
        "unknown",
    ),
    (
        "恶意语法不会被求值",
        {"equation": "__import__('os').system('echo pwned') = 0"},
        "unknown",
    ),
]


def main() -> int:
    plugin = PhysicsPlugin()
    failures = 0
    print("物理 PARTIAL 验证器自检")
    print("-" * 72)
    for name, data, expected in CASES:
        verdict = plugin.verify(StudentStep(node_id="n1", text="", data=data))
        ok = verdict.status == expected
        failures += 0 if ok else 1
        mark = "OK" if ok else "FAIL"
        print(f"[{mark}] {name}: {verdict.status} (期望 {expected})")
        print(f"       {verdict.detail}")
    print("-" * 72)
    print(f"{len(CASES) - failures}/{len(CASES)} 通过")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())