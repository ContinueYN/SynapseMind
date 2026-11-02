"""Health check DTO."""

from __future__ import annotations

from typing import Literal

from synapse.api.schemas.common import StrictModel


class HealthOut(StrictModel):
    status: Literal["ok"] = "ok"
    version: str
