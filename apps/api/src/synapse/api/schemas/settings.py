"""Per-user model settings (BYOK) DTOs.

``api_key`` is write-only: it appears in a request body, never in a response,
and field-level ``repr=False`` keeps it out of accidental object dumps. No
example values are declared on purpose.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from synapse.api.schemas.common import StrictModel


class ModelCredentialIn(StrictModel):
    """A full save from the settings form; the key is required on save."""

    provider: str = Field(min_length=1, max_length=32)
    base_url: str = Field(default="", max_length=300)
    model: str = Field(default="", max_length=120)
    api_key: str = Field(min_length=8, max_length=4096, repr=False)


class ModelCredentialTestIn(StrictModel):
    """Test a candidate credential; omitted fields fall back to the saved row."""

    provider: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, min_length=8, max_length=4096, repr=False)


class ModelCredentialOut(StrictModel):
    """The masked credential view; the key itself is never part of it."""

    configured: bool
    provider: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    key_last4: str | None = Field(default=None, max_length=4)
    last_verified_at: datetime | None = None
    encryption_ready: bool
    warning: str | None = None


class ModelTestOut(StrictModel):
    """Result of one provider probe; ``message`` never contains the key."""

    ok: bool
    latency_ms: int = Field(ge=0)
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
