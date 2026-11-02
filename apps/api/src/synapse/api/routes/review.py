"""Internal review queue route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from synapse.api.auth import require_authenticated
from synapse.api.deps import get_review_service
from synapse.api.mappers.review import review_items_out
from synapse.api.schemas.review import ReviewItemsOut
from synapse.application.review.service import ReviewService

router = APIRouter()


@router.get(
    "/review/items",
    response_model=ReviewItemsOut,
    dependencies=[Depends(require_authenticated)],
)
def list_review_items(
    review: ReviewService = Depends(get_review_service),
) -> ReviewItemsOut:
    """Read-only listing of disagreed cards for the internal review page.

    There is no write endpoint and no per-owner filtering: the queue is a local
    SQLite file. With ``SYNAPSE_AUTH=on`` the middleware requires a session, so
    an anonymous caller gets 401; any logged-in account can read the global
    queue (this is the internal operator view, not a per-user resource). With
    auth off the listing is the local baseline and answers 200. The page
    exports the reviewer's judgment as a CSV instead of storing it, and the
    response never contains the student's own work.
    """

    return review_items_out(review.items())
