"""Verifier ports for the generic graph (Phase 1b).

The plan's four verification modes each get an adapter, not a separate system.
Phase 1b wires the two that already have real implementations behind them:

* ``FormalVerifier`` reuses the SymPy parameter-range falsifier (M2.5 S5);
* ``EmpiricalVerifier`` reuses the physics unit/numeric replay (M2.5 S6).

Both take a **claim**, never a graph: an empty graph, a graph without a claim,
or a call with no structured data must produce ``unknown`` with a concrete
reason. ``unknown`` is a result, not an error — and it is never rendered as
"checked and fine".
"""

from __future__ import annotations

from typing import Protocol

from synapse.domain.problem.generic import ClaimCheck, EmpiricalClaim
from synapse.domain.problem.models import VerificationClaim


class FormalVerifier(Protocol):
    def verify(self, claim: VerificationClaim) -> ClaimCheck: ...


class EmpiricalVerifier(Protocol):
    def verify(self, claim: EmpiricalClaim) -> ClaimCheck: ...
