"""Compose the account layer from the environment contract.

``build_auth`` is the only place that knows SQLAlchemy and Redis exist. It
returns ``None`` when ``SYNAPSE_AUTH=off``, which means no engine is created and
no database file is touched — the local single-user baseline stays byte-for-byte
the same.

The runtime carries a ``close`` hook so uvicorn shutdown (and tests) can release
the engine and any Redis connection instead of leaking a file handle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from redis import Redis
from sqlalchemy.engine import Engine

from synapse.application.auth import AuthService, SessionTokenStore
from synapse.infrastructure.auth.db import build_session_factory, create_auth_engine
from synapse.infrastructure.auth.passwords import Argon2PasswordHasher
from synapse.infrastructure.auth.settings import AuthSettings
from synapse.infrastructure.auth.stores import (
    RedisClient,
    RedisSessionTokenStore,
    SqlSessionTokenStore,
    SqlUserStore,
)


@dataclass(frozen=True, slots=True)
class AuthRuntime:
    """The configured service plus the resources it opened."""

    service: AuthService
    close: Callable[[], None]


def build_auth(
    settings: AuthSettings,
    *,
    redis_client: RedisClient | None = None,
    engine: Engine | None = None,
) -> AuthRuntime | None:
    """Build the account layer, or ``None`` when authentication is off."""

    if not settings.enabled:
        return None
    auth_engine = engine if engine is not None else create_auth_engine(settings.database_url)
    sessions = build_session_factory(auth_engine)

    client: RedisClient | None = None
    close_redis: Callable[[], None] | None = None
    if settings.redis_url:
        if redis_client is None:
            connection = Redis.from_url(settings.redis_url, decode_responses=True)
            client = cast(RedisClient, connection)
            close_redis = connection.close
        else:
            client = redis_client

    tokens: SessionTokenStore
    if client is not None:
        tokens = RedisSessionTokenStore(client, ttl_s=settings.session_ttl_s)
    else:
        # No Redis: the same SQL database that holds accounts holds sessions.
        tokens = SqlSessionTokenStore(sessions)

    service = AuthService(
        users=SqlUserStore(sessions),
        tokens=tokens,
        hasher=Argon2PasswordHasher(),
        session_ttl_s=settings.session_ttl_s,
        allow_signup=settings.allow_signup,
    )

    def close() -> None:
        auth_engine.dispose()
        if close_redis is not None:
            close_redis()

    return AuthRuntime(service=service, close=close)
