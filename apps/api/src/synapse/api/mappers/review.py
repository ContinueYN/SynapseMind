"""Generic review and review-queue mappers."""

from __future__ import annotations

from synapse.api.mappers.common import clip
from synapse.api.schemas.review import GenericReviewOut, ReviewItemOut, ReviewItemsOut
from synapse.application.review.service import ReviewItem
from synapse.domain.problem.generic_review import GenericReview


def review_item_out(item: ReviewItem) -> ReviewItemOut:
    """Map one queue row; the queue has no student text to leak."""

    return ReviewItemOut(
        session_id=item.session_id,
        problem_id=item.problem_id,
        layer=item.layer,
        label=clip(item.label, 40),
        node_id=item.node_id,
        one_line=clip(item.one_line, 200),
        confidence=item.confidence,
        created_at=item.created_at,
    )


def review_items_out(items: list[ReviewItem]) -> ReviewItemsOut:
    return ReviewItemsOut(
        version="0.1",
        items=[review_item_out(item) for item in items],
    )


def generic_review_out(review: GenericReview) -> GenericReviewOut:
    """Validate the published generic-review shape through the DTO.

    The domain object builds ``to_dict()`` with the contract's own keys, so the
    DTO is checked against the schema instead of being hand-mapped field by
    field. If the two ever drift, response validation fails here.
    """

    return GenericReviewOut.model_validate(review.to_dict())
