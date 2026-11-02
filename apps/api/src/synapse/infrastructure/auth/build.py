"""Compose the account layer from the environment contract.

``build_auth`` is the only place that knows SQLAlchemy and Redis exist. It
returns ``None`` when ``SYNAPSE_AUTH=off``, which means no engine is created and
no database file is touched — the local single-user baseline stays byte-for-byte
the same.

The same runtime also owns the per-user model-credential service, because both
tables live in the same database and share one engine. BYOK is composed even
without a master key: the service then reports ``encryption_ready=false`` and
refuses writes, which is a clearer failure than an endpoint that does not exist.

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
from synapse.application.credentials import (
    CredentialService,
    ModelTester,
    RemoteUrlGuard,
)
from synapse.infrastructure.auth.db import build_session_factory, create_auth_engine
from synapse.infrastructure.auth.passwords import Argon2PasswordHasher
from synapse.infrastructure.auth.settings import AuthSettings
from synapse.infrastructure.auth.stores import (
    RedisClient,
    RedisSessionTokenStore,
    SqlSessionTokenStore,
    SqlUserStore,
)
from synapse.infrastructure.credentials.crypto import FernetCipher
from synapse.infrastructure.credentials.guard import SsrfGuard
from synapse.infrastructure.credentials.probe import HttpxModelTester
from synapse.infrastructure.credentials.settings import CredentialSettings
from synapse.infrastructure.credentials.store import SqlCredentialStore


@dataclass(frozen=True, slots=True)
class AuthRuntime:
    """The configured service(s) plus the resources they opened."""

    service: AuthService
    close: Callable[[], None]
    # None only when a caller builds an ``AuthRuntime`` without a database (the
    # gate-only tests do that); the settings router then answers 503.
    credentials: CredentialService | None = None


def build_auth(
    settings: AuthSettings,
    *,
    redis_client: RedisClient | None = None,
    engine: Engine | None = None,
    credential_settings: CredentialSettings | None = None,
    credential_guard: RemoteUrlGuard | None = None,
    credential_tester: ModelTester | None = None,
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

    credential_cfg = (
        credential_settings if credential_settings is not None else CredentialSettings.from_env()
    )
    credentials = CredentialService(
        store=SqlCredentialStore(sessions),
        cipher=FernetCipher.from_secret(credential_cfg.master_key),
        guard=credential_guard if credential_guard is not None else SsrfGuard(),
        tester=credential_tester if credential_tester is not None else HttpxModelTester(),
    )

    def close() -> None:
        auth_engine.dispose()
        if close_redis is not None:
            close_redis()

    return AuthRuntime(service=service, close=close, credentials=credentials)
