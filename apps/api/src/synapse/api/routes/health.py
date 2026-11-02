"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter

from synapse.api.schemas.health import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(version="0.1.0")
