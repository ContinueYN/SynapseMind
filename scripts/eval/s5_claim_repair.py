"""Controlled claim-repair probe (M2.5 S5 ④, ADR-0004 §5.4/§8).

``s5_verify.py`` only exercises the repair when the model happens to write a
wrong answer range, and that is stochastic: ``P_DERIV_003`` has come back both
refuted (``(-∞, e]``) and correct (``[0, e]``). This probe forces the known
refutations so the batch does not have to get lucky.

Each case pins the formal part of the claim (``f(x)=e^x-a x ≥ 0``, ``a∈R``,
``x∈R``) and only gets the answer interval wrong — in a different way:

- ``negative_branch``: ``(-∞, e]`` — the historical failure, keeps ``a<0``;
- ``too_narrow``: ``[1, e]`` — drops the whole ``0 ≤ a < 1`` band;
- ``open_zero``: ``(0, e]`` — right bounds, wrong inclusivity at 0;
- ``open_e``: ``[0, e)`` — right bounds, wrong inclusivity at ``e``;
- ``extra_negative``: ``(-1, e]`` — a narrower false negative band.

For every case the probe asks the *interval-only* repair call for a corrected
range, with the timeout the production path would have left (the 8s budget minus
the build), and reports latency, the new range and whether the verifier accepts
it. That is the S5 ④ closure check: the negative-parameter branch — and the
boundary conventions around it — get removed without putting any concrete
function into the prompt (the expression comes from the claim itself).

    cd apps/api
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_claim_repair.py
    .\\.venv\\Scripts\\python.exe ..\\..\\scripts\\eval\\s5_claim_repair.py --case open_zero

Exit code 0 when every call parsed and every case had at least one repaired
range pass the verifier; 1 otherwise. This is a probe, not a gate.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

from synapse.application.verification import describe_claim  # noqa: E402
from synapse.domain.problem.models import (  # noqa: E402
    Interval,
    ProblemDraft,
    VerificationClaim,
)
from synapse.infrastructure.llm.client import OpenAICompatibleClient  # noqa: E402
from synapse.infrastructure.llm.graph import (  # noqa: E402
    build_claim_repair_request,
    read_claim_repair,
)
from synapse.infrastructure.llm.settings import LLMSettings, load_dotenv  # noqa: E402
from synapse.infrastructure.seed import SAMPLE_PROBLEM  # noqa: E402
from synapse.infrastructure.verification.sympy_verifier import SymPyVerifier  # noqa: E402

DRAFT = ProblemDraft(
    id="P_DERIV_003",
    text="已知函数 f(x)=e^x-a x，a∈R。若 f(x)≥0 对任意 x∈R 恒成立，求 a 的取值范围。",
)

CASE_TEXT = {
    "negative_branch": "历史错法：保留 a<0 的分支",
    "too_narrow": "漏掉 0≤a<1 的整段",
    "open_zero": "边界取错：0 被排除",
    "open_e": "边界取错：e 被排除",
    "extra_negative": "负参数段收窄但没有删掉",
}


def _claim(lower: str | None, upper: str | None, *, lower_inclusive: bool, upper_inclusive: bool):
    return VerificationClaim(
        kind="parameter_range",
        parameter="a",
        variable="x",
        variable_domain="(-inf,+inf)",
        expression="exp(x) - a*x",
        relation=">=",
        intervals=(
            Interval(
                lower=lower,
                upper=upper,
                lower_inclusive=lower_inclusive,
                upper_inclusive=upper_inclusive,
            ),
        ),
    )


CASES: dict[str, VerificationClaim] = {
    "negative_branch": _claim(None, "E", lower_inclusive=False, upper_inclusive=True),
    "too_narrow": _claim("1", "E", lower_inclusive=True, upper_inclusive=True),
    "open_zero": _claim("0", "E", lower_inclusive=False, upper_inclusive=True),
    "open_e": _claim("0", "E", lower_inclusive=True, upper_inclusive=False),
    "extra_negative": _claim("-1", "E", lower_inclusive=False, upper_inclusive=True),
}


def _run_case(
    name: str,
    claim: VerificationClaim,
    *,
    verifier: SymPyVerifier,
    client: OpenAICompatibleClient,
    repeats: int,
    timeout: float,
) -> dict[str, Any]:
    graph = replace(SAMPLE_PROBLEM.graph, claim=claim)
    refutation = verifier.verify(graph)
    print(f"\n== {name}：{describe_claim(claim)} -> {refutation.status}")
    if refutation.status != "fail":
        print(f"! 这个错答案没有被推翻：{refutation.status}/{refutation.reason}")
        return {
            "name": name,
            "claim": describe_claim(claim),
            "refutation": refutation,
            "rows": [],
            "ok": False,
        }

    print(f"反例：{refutation.detail}")
    rows: list[dict[str, Any]] = []
    for index in range(1, repeats + 1):
        request = build_claim_repair_request(DRAFT, claim, refutation)
        started = time.perf_counter()
        try:
            response = client.complete(request, timeout_s=timeout)
        except Exception as exc:  # noqa: BLE001 - the report needs the failure
            rows.append(
                {
                    "index": index,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "answer": f"{type(exc).__name__}: {exc}",
                    "verdict": "call_failed",
                    "ok": False,
                }
            )
            print(f"#{index} 调用失败：{exc}")
            continue
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            repaired = read_claim_repair(response.text, graph, refutation)
        except Exception as exc:  # noqa: BLE001 - malformed reply is a row, not a crash
            rows.append(
                {
                    "index": index,
                    "latency_ms": latency_ms,
                    "answer": f"未解析：{exc}",
                    "verdict": "malformed",
                    "ok": False,
                }
            )
            print(f"#{index} {latency_ms}ms 未解析：{exc}")
            continue
        if repaired is None:
            rows.append(
                {
                    "index": index,
                    "latency_ms": latency_ms,
                    "answer": "声明不存在满足条件的区间",
                    "verdict": "declined",
                    "ok": False,
                }
            )
            print(f"#{index} {latency_ms}ms 拒绝给出区间")
            continue
        verdict = verifier.verify(replace(graph, claim=repaired))
        ok = verdict.status == "pass"
        rows.append(
            {
                "index": index,
                "latency_ms": latency_ms,
                "answer": describe_claim(repaired),
                "verdict": f"{verdict.status}/{verdict.reason}",
                "ok": ok,
            }
        )
        print(f"#{index} {latency_ms}ms {describe_claim(repaired)} -> {verdict.status}")

    parsed = [row for row in rows if row["verdict"] not in {"call_failed", "malformed"}]
    return {
        "name": name,
        "claim": describe_claim(claim),
        "refutation": refutation,
        "rows": rows,
        "ok": len(parsed) == len(rows) and any(row["ok"] for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--case",
        action="append",
        choices=sorted(CASES),
        help="repeatable; defaults to every case",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="seconds left in the first-question budget when the repair runs",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "reports" / "m2.5-s5-claim-repair.md"),
    )
    args = parser.parse_args()

    load_dotenv()
    settings = LLMSettings.from_env()
    if not settings.api_key:
        print("! 需要 DEEPSEEK_API_KEY（仓库根 .env 或环境变量）")
        return 2

    names = args.case or sorted(CASES)
    verifier = SymPyVerifier()
    client = OpenAICompatibleClient(settings)
    results: list[dict[str, Any]] = []
    try:
        for name in names:
            results.append(
                _run_case(
                    name,
                    CASES[name],
                    verifier=verifier,
                    client=client,
                    repeats=args.repeats,
                    timeout=args.timeout,
                )
            )
    finally:
        client.close()

    report = _render(results, settings=settings, timeout=args.timeout, repeats=args.repeats)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"report: {out}")

    return 0 if all(case["ok"] for case in results) else 1


def _render(
    results: list[dict[str, Any]],
    *,
    settings: LLMSettings,
    timeout: float,
    repeats: int,
) -> str:
    latencies = [
        row["latency_ms"] for case in results for row in case["rows"] if row["latency_ms"] > 0
    ]
    healed = [sum(1 for row in case["rows"] if row["ok"]) for case in results]
    total = sum(len(case["rows"]) for case in results)
    lines = [
        "# M2.5 S5 claim 只重写区间的受控探针",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 模型：`{settings.model}`；预算内超时：{timeout:.1f}s；每例 {repeats} 次",
        f"- 结果：{sum(healed)}/{total} 次修复通过验证；"
        f"延迟 p50 {_pct(latencies, 0.5)} ms / max {max(latencies, default=0)} ms",
        "",
    ]
    for case in results:
        refutation = case["refutation"]
        lines += [
            f"## `{case['name']}`：{CASE_TEXT.get(case['name'], '')}",
            "",
            f"- 预设错答案：`{case['claim']}`",
            f"- 反例：{refutation.detail if refutation.status == 'fail' else refutation.reason}",
            "",
            "| 轮次 | 耗时(ms) | 修复后的答案 | 验证 |",
            "|---|---|---|---|",
        ]
        for row in case["rows"]:
            lines.append(
                f"| {row['index']} | {row['latency_ms']} | {_cell(str(row['answer']))} | "
                f"{row['verdict']} |"
            )
        if not case["rows"]:
            lines.append("| — | — | 预设错答案未被推翻，跳过 | — |")
        lines.append("")

    lines += [
        "## 口径",
        "",
        "- 探针只调用一次 `graph_claim_repair`，不重新建图；生产路径里它的超时"
        "等于「7.5s 预算减去已用时间」，所以这里的 3s 是慢首问（≈4.5s 建图）之后的典型余量。",
        "- 修复请求把表达式、关系、参数与定义域钉死，模型只能改区间；"
        "`verification_malformed` 是例外（表达式本身读不懂，允许重写整个 claim）。",
        "- 五例都是同一个 `f(x)=e^x-a x ≥ 0` 的形状，错的地方不同（负参数段、整段、"
        "两端的开闭）。它们不是批量准确率；批量口径仍看 `s5_verify.py`。",
        "- 修复不是单调的：模型可能把「偏窄」过修成「偏宽」（本批出现过一次 `[1,E]` → "
        "`(-∞,E]`），重新验证仍 `fail`。生产路径此时丢弃 claim、保留图"
        "（`claim_repair_refuted`），不会留下被推翻的答案。",
    ]
    return "\n".join(lines) + "\n"


def _pct(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, int(fraction * len(ordered)) - 1)]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
