"""Machine-checkable claims shared by the solution graph and the generic graph.

The solution graph used to own these types. Phase 1b needs the same formal claim
on a generic graph, while ``models`` needs to own the generic graph reference —
importing each other would be a cycle. The claim types therefore live in their
own module and are re-exported from ``models`` so existing imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Interval:
    """One connected piece of a parameter answer range (M2.5 S5).

    Endpoints are SymPy expression strings, not floats: ``1/E`` and ``E`` are
    the answers a student is expected to write, and rounding them before the
    verifier sees them would make boundary checks meaningless. ``None`` means
    unbounded on that side.
    """

    lower: str | None
    upper: str | None
    lower_inclusive: bool = True
    upper_inclusive: bool = True


@dataclass(frozen=True, slots=True)
class VerificationClaim:
    """A graph's formalised answer, written so a machine can falsify it.

    Meaning (chapter 13 §13.3, STRONG tier)::

        for all variable in variable_domain:  expression <relation> 0
        ⇔  parameter ∈ intervals

    v1 only covers this shape — a parameter range under a universally
    quantified one-variable constraint. Answer sets that are not a parameter
    range (a value, a solution set in x, a proof) have no claim, and the
    verifier says ``unknown`` instead of pretending.
    """

    kind: str
    parameter: str
    variable: str
    variable_domain: str
    expression: str
    relation: str
    intervals: tuple[Interval, ...]
