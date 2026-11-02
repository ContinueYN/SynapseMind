"""HTTP routes, composed under ``/api/v1``.

Keep each handler thin: validate, call a use case, map the result. The feature
modules only define routers; this module owns the single prefix and the order
in which they are registered.
"""

from __future__ import annotations

from fastapi import APIRouter

from synapse.api.routes import executions, health, knowledge, review, sessions

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(executions.router)
router.include_router(review.router)
router.include_router(knowledge.router)
# Registered last so every session route above is part of this gated router.
router.include_router(sessions.router)
