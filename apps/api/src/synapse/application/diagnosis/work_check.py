"""Port for checking the equalities a student wrote (M2.5 S5 ⑥).

The application service may not import SymPy or the substitution rules in
``infrastructure/verification``; it only needs the answers to one question:
*which equals signs in this work are provably broken?* The implementation is
``infrastructure.verification.equalities.SympyEqualityChecker``.

The port returns only findings, never the raw report: counters such as
``checked`` belong to evaluation runs, not to the diagnosis card.
"""

from __future__ import annotations

from typing import Protocol

from synapse.domain.diagnosis.work import WorkFinding


class EqualityChecker(Protocol):
    def findings(self, work: str) -> tuple[WorkFinding, ...]: ...
