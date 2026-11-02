"""Process coach DTOs (v0.1).

The coach is process feedback, not a solution. These DTOs deliberately have no
``answer``/``solution``/``score``/``rank`` field: the response model itself is
part of the boundary, not only the service behind it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from synapse.api.schemas.common import StrictModel

CoachFocusOut = Literal["where_wrong", "how_to_start"]
CoachModeOut = Literal["rules", "llm"]
CoachPointKindOut = Literal[
    "missing_evidence",
    "missing_reasoning",
    "missing_constraint",
    "no_attempt",
    "next_step",
    "process_note",
]


class CoachRequest(StrictModel):
    """The only two things a student can ask the coach for."""

    focus: CoachFocusOut


class CoachPointOut(StrictModel):
    """One process observation; ``basis`` names where it came from."""

    kind: CoachPointKindOut
    text: str = Field(min_length=1, max_length=200)
    basis: str = Field(min_length=1, max_length=64)


class CoachOut(StrictModel):
    """Process feedback with its uncertainty made explicit.

    ``not_claimed`` must be non-empty: the coach has no correctness check, no
    answer store and no score, and the client renders that list rather than
    letting the result read like a verdict.
    """

    version: Literal["0.1"]
    mode: CoachModeOut
    focus: CoachFocusOut
    headline: str = Field(min_length=1, max_length=160)
    points: list[CoachPointOut] = Field(min_length=1, max_length=4)
    next_question: str = Field(min_length=1, max_length=200)
    not_claimed: list[str] = Field(min_length=1, max_length=6)
    disclaimer: str = Field(min_length=1, max_length=320)
