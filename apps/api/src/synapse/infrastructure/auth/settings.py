"""Environment contract for the account layer.

Every switch is read once when the app is composed, not at request time, so a
running server cannot change its security posture halfway. The defaults keep a
plain checkout behaving exactly like the baseline:

``SYNAPSE_AUTH=off``       no login prompt, no database engine, no gate
``SYNAPSE_DATABASE_URL``   SQLite file next to the other local state
``SYNAPSE_REDIS_URL``      unset -> auth session tokens live in SQL
``SYNAPSE_AUTH_ALLOW_SIGNUP=off``  only the first account may register
``SYNAPSE_COOKIE_SECURE=off``      plain-HTTP localhost default
``SYNAPSE_AUTH_SESSION_TTL_S``     cookie max-age and server-side TTL

A typo in a flag is loud (``ValueError``) for the same reason it is in
``features.py``: silently treating ``SYNAPSE_AUTH=onn`` as off would hide why
every diagnostic request is still unauthenticated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from synapse.infrastructure.features import parse_flag

# The cookie name is fixed by the API contract, not configurable: the web client
# and the operator docs both refer to ``synapse_session``.
COOKIE_NAME = "synapse_session"

# Relative to the process working directory, like SYNAPSE_REVIEW_DB and
# SYNAPSE_SESSION_DB. Compose overrides it with a postgresql+psycopg URL.
DEFAULT_DATABASE_URL = "sqlite+pysqlite:///var/auth.sqlite3"

# Seven days: long enough for a personal deployment, short enough that an old
# cookie stops working without a background sweeper.
DEFAULT_SESSION_TTL_S = 7 * 24 * 60 * 60

_MAX_SESSION_TTL_S = 365 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Resolved auth configuration; frozen so a request cannot mutate it."""

    enabled: bool = False
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str | None = None
    allow_signup: bool = False
    cookie_secure: bool = False
    session_ttl_s: int = DEFAULT_SESSION_TTL_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AuthSettings:
        source = os.environ if env is None else env
        return cls(
            enabled=parse_flag("SYNAPSE_AUTH", source.get("SYNAPSE_AUTH", "off")),
            database_url=(source.get("SYNAPSE_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL),
            redis_url=source.get("SYNAPSE_REDIS_URL", "").strip() or None,
            allow_signup=parse_flag(
                "SYNAPSE_AUTH_ALLOW_SIGNUP",
                source.get("SYNAPSE_AUTH_ALLOW_SIGNUP", "off"),
            ),
            cookie_secure=parse_flag(
                "SYNAPSE_COOKIE_SECURE",
                source.get("SYNAPSE_COOKIE_SECURE", "off"),
            ),
            session_ttl_s=_parse_ttl(source.get("SYNAPSE_AUTH_SESSION_TTL_S", "")),
        )


def _parse_ttl(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_SESSION_TTL_S
    try:
        ttl = int(value)
    except ValueError as exc:
        raise ValueError(f"SYNAPSE_AUTH_SESSION_TTL_S={raw!r}: expected integer seconds") from exc
    if not 1 <= ttl <= _MAX_SESSION_TTL_S:
        raise ValueError(
            f"SYNAPSE_AUTH_SESSION_TTL_S={raw!r}: expected 1..{_MAX_SESSION_TTL_S} seconds"
        )
    return ttl
