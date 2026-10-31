"""M2 exit condition, executed as a test.

Chapter 12 §12.3 defines PASS/FAIL against the real state machine; this module
replays ``eval/golden/golden-v0.1.jsonl`` turn by turn and asserts the verdict.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from synapse.api.deps import build_container
from synapse.application.replay import GoldenCase, judge, load_cases, replay_case

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden" / "golden-v0.1.jsonl"

# The golden corpus stays local: it is review material, not a public fixture.
# Public CI still exercises the replay engine through the non-golden tests.
if not GOLDEN_PATH.exists():
    pytest.skip(
        "private golden corpus is not published; run locally with eval/golden present",
        allow_module_level=True,
    )

CASES = load_cases(GOLDEN_PATH)


def test_golden_set_shape() -> None:
    assert len(CASES) == 10, "M2 scope is 10 cases; 100/200 belong to M2.5"
    ids = [case.case_id for case in CASES]
    assert len(set(ids)) == len(ids)

    quotas = Counter(case.category for case in CASES)
    assert quotas["wrong_answer"] == 3
    assert quotas["right_answer_missing_case"] == 3
    assert quotas["no_idea"] == 2
    assert quotas["negative"] == 2


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_case_meets_exit_condition(case: GoldenCase) -> None:
    result = replay_case(build_container().service, case)
    verdict = judge(case, result)
    trace = " ".join(
        f"t{row.turn}:{row.top1}={row.posterior:.2f}/{row.margin:.2f}:{row.kind}"
        for row in result.turns
    )
    assert verdict.passed, f"{case.case_id} {verdict.reason} | {trace}"
    assert result.leak_fallbacks == 0, f"{case.case_id} hit the leak gate"


def test_pass_rate_meets_the_80_percent_bar() -> None:
    """§2.4: >= 8/10 cases pass; a passed stop counts, a missed diagnose does not."""
    passed = 0
    diagnosed = 0
    for case in CASES:
        result = replay_case(build_container().service, case)
        passed += int(judge(case, result).passed)
        if result.outcome != "diagnose":
            continue
        diagnosed += 1
        last = result.turns[-1]
        assert last.kind == "diagnose"
        assert last.margin >= 0.25
        assert result.last_turn <= 5
    assert passed >= 8, "chapter 12 §2.4 recommends >= 8/10"
    assert diagnosed >= 1
