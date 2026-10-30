"""A machine-checkable finding about the student's own work.

The equality-chain checker (``infrastructure/verification/equalities.py``) can
say "this equals sign does not hold" without a reference answer: it compares the
two sides as functions, or their limits when the chain contains ``lim``. The
finding is a domain value because it outlives the request that computed it — it
is stored on the session and merged into the diagnosis card several turns later.

``summary`` is the student-facing one-liner, e.g.
``"x→0 时左边极限 0.5、右边 2"``. It is built where the numeric evidence is
available (the infrastructure adapter) so the card layer never has to re-parse
prose or recompute SymPy values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FindingKind = Literal["identity", "limit"]


@dataclass(frozen=True, slots=True)
class WorkFinding:
    """One broken equals sign in the student's own process."""

    kind: FindingKind
    left: str
    right: str
    detail: str
    counterexample: str = ""
    summary: str = ""
