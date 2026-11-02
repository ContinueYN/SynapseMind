"""Shared protocol base types.

These are protocol shapes, not domain objects. Keeping them here prevents
FastAPI/Pydantic from leaking into the domain layer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
