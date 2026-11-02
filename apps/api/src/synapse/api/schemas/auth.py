"""Account DTOs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from synapse.api.schemas.common import StrictModel

# Deliberately simple: the API stores only addresses this pattern accepts, and a
# full RFC 5322 parser would add a dependency without making an address reachable.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL_PATTERN.match(cleaned):
        raise ValueError("email is not a valid address")
    return cleaned


class RegisterRequest(StrictModel):
    """Account creation for a self-hosted owner.

    Only the first registration succeeds unless ``SYNAPSE_AUTH_ALLOW_SIGNUP=on``.
    The password is length-checked here and hashed with Argon2id before it
    reaches any store; it is never logged or echoed back.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def password_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class LoginRequest(StrictModel):
    """Credentials for an existing account.

    The password has no real minimum here beyond being non-empty: rejecting a
    short password at login would tell a caller something about the account.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class AuthUserOut(StrictModel):
    """The public account view; no digest, no session token."""

    id: str = Field(min_length=1, max_length=40)
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=120)
    created_at: datetime


class LogoutOut(StrictModel):
    status: Literal["ok"] = "ok"
