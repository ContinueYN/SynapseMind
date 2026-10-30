"""Structure hint: the only output a NONE-tier subject may produce (M2.5 S7).

Chapter 13 §13.3 splits subjects by what the product may *promise*. For math a
counterexample can be found, so the product may name the step a student skipped.
For Chinese/English/history there is no automatic truth, so the honest output is
smaller: "here are the steps this problem decomposes into, here is which ones
your process appears to mention, and here is where to look next".

That is why this lives in its own module rather than next to ``DiagnosisCard``:
the two shapes are not interchangeable. A ``StructureHint`` has no layer, no
hypothesis, no posterior and no confidence. Anything that could read as "we
found where you are stuck" belongs in the card, not here.

S8 adds ``partial``: a multi-clause step whose first half appears in the work
is neither fully covered nor absent. It is still coverage, not correctness —
"只写到一部分" is the strongest sentence this output may use.

The shape is published as ``specs/structure-hint.schema.json`` (v0.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StepStatus = Literal["covered", "partial", "missing"]


@dataclass(frozen=True, slots=True)
class HintStep:
    """One reference step, in graph order, with what the process showed.

    ``status`` is deliberately not "right"/"wrong": the aligner can only notice
    whether a step was *mentioned*, and S8 can additionally notice that only
    one clause of a multi-clause step was mentioned.
    """

    node_id: str
    text: str
    status: StepStatus


@dataclass(frozen=True, slots=True)
class StructureHint:
    """An observation about coverage, not a diagnosis.

    ``steps`` comes from the same alignment the card path uses, but read at face
    value: the aligner can only notice whether a step was *mentioned* (and, for
    the NONE tier's clause matcher, whether only part of it was mentioned),
    never whether it was done correctly. The wording in
    ``one_line``/``next_step`` and the fixed ``disclaimer`` exist so a client
    cannot present this as a diagnosis.
    """

    version: Literal["0.2"]
    session_id: str
    problem_id: str
    subject: str
    level: str
    one_line: str
    steps: tuple[HintStep, ...]
    focus_node_id: str | None
    next_step: str
    disclaimer: str

    @property
    def covered(self) -> tuple[HintStep, ...]:
        return tuple(step for step in self.steps if step.status == "covered")

    @property
    def partial(self) -> tuple[HintStep, ...]:
        return tuple(step for step in self.steps if step.status == "partial")

    @property
    def missing(self) -> tuple[HintStep, ...]:
        return tuple(step for step in self.steps if step.status == "missing")
