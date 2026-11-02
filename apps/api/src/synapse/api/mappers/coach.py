"""Process coach mapper."""

from __future__ import annotations

from synapse.api.mappers.common import clip_text
from synapse.api.schemas.coach import CoachOut, CoachPointOut
from synapse.application.diagnosis.coach import CoachOut as CoachResult


def coach_out(result: CoachResult) -> CoachOut:
    """Map the application DTO to the wire shape.

    Text is clipped to the schema's limits here rather than letting response
    validation fail: the coach must always answer, even when a rule line is
    slightly too long. ``not_claimed`` stays a list, never a single sentence.
    """

    return CoachOut(
        version="0.1",
        mode=result.mode,
        focus=result.focus,
        headline=clip_text(result.headline, 160),
        points=[
            CoachPointOut(
                kind=point.kind,
                text=clip_text(point.text, 200),
                basis=clip_text(point.basis, 64),
            )
            for point in result.points
        ],
        next_question=clip_text(result.next_question, 200),
        not_claimed=[clip_text(item, 200) for item in result.not_claimed],
        disclaimer=clip_text(result.disclaimer, 320),
    )
