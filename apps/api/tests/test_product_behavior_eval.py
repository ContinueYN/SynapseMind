"""CI drift guard for the product behavior / contract harness.

The full harness is a 44-case regression pass over the fixed set in
``scripts/eval/product_behavior_cases.py``. Running all of it in the default
suite would duplicate work and make the suite slower for little extra signal, so
this file runs the ``subset=True`` cases only (roughly a fifth of the set) and
also checks that the case table itself stays well-formed.

If these tests fail, the harness has drifted: either a product boundary changed
or the fixed case set was edited without updating its expectation. Do not "fix"
CI by deleting a case; update the contract and say why in the report.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_EVAL = ROOT / "scripts" / "eval"
if str(SCRIPTS_EVAL) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_EVAL))

import product_behavior as harness  # noqa: E402


def test_the_fixed_case_set_is_well_formed() -> None:
    ids = [case.id for case in harness.CASES]

    assert len(ids) == len(set(ids)), f"duplicate case id: {ids}"
    assert len(ids) >= 24, f"expected at least 24 cases, got {len(ids)}"
    for case in harness.CASES:
        assert case.intent, f"{case.id}: missing intent"
        assert case.contract, f"{case.id}: missing contract"
        assert case.checks, f"{case.id}: missing checks"
        assert case.scenario in harness.SCENARIOS, f"{case.id}: unknown scenario"
        if case.expected == "expected_fail":
            assert case.reason, f"{case.id}: expected_fail needs a reason"
    subset = [case for case in harness.CASES if case.id in harness.SUBSET_IDS]
    assert len(subset) >= 6, f"subset too small: {[case.id for case in subset]}"


def test_the_fast_subset_still_meets_its_contracts() -> None:
    cases = tuple(case for case in harness.CASES if case.id in harness.SUBSET_IDS)
    results = harness.run_cases(cases)

    failures = []
    for result in results:
        if result.ok:
            continue
        missing = "; ".join(
            f"{check.key}={result.obs.fields.get(check.key)!r}" for check in result.failed_checks
        )
        failures.append(f"{result.case.id} [{result.status}]: {missing}")

    assert not failures, "\n".join(failures)
