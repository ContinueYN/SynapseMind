"""Adapters for the two auth ports: user records and session tokens.

``SqlUserStore``      accounts live in ``users`` (SQLite or PostgreSQL).
``SqlSessionTokenStore``  default token store: rows in ``auth_sessions``.
``RedisSessionTokenStore`` optional token store: keys with a native TTL, used
                          when ``SYNAPSE_REDIS_URL`` is configured.

Both SQL adapters translate ``SQLAlchemyError`` into ``AuthStoreUnavailable`` so
a missing migration (or an unreachable database) becomes a 503 with a migration
hint instead of an opaque 500. Redis failures do the same.

Only digests are stored: a leaked ``auth_sessions`` table cannot be replayed as
a cookie, and logout sets ``revoked_at`` instead of pretending the row is gone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from synapse.application.auth import (
    AuthStoreUnavailable,
    EmailAlreadyRegistered,
    SessionToken,
    UserRecord,
)
from synapse.infrastructure.auth.db import AuthSessionRow, UserRow, as_utc

_STORE_HINT = "账号数据库不可用；请检查 SYNAPSE_DATABASE_URL，并先运行 `alembic upgrade head`。"
_REDIS_HINT = "认证会话存储（Redis）不可用；请检查 SYNAPSE_REDIS_URL 或去掉该变量回退到 SQL。"


def _to_record(row: UserRow) -> UserRecord:
    return UserRecord(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        password_hash=row.password_hash,
        created_at=as_utc(row.created_at),
    )


class SqlUserStore:
    """SQL-backed accounts. One short session per operation."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def count(self) -> int:
        try:
            with self._sessions() as session:
                total = session.scalar(select(func.count()).select_from(UserRow))
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        return int(total or 0)

    def find_by_email(self, email: str) -> UserRecord | None:
        try:
            with self._sessions() as session:
                row: UserRow | None = session.scalar(select(UserRow).where(UserRow.email == email))
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        return _to_record(row) if row is not None else None

    def get(self, user_id: str) -> UserRecord | None:
        try:
            with self._sessions() as session:
                row: UserRow | None = session.get(UserRow, user_id)
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        return _to_record(row) if row is not None else None

    def create(
        self,
        *,
        email: str,
        display_name: str | None,
        password_hash: str,
        created_at: datetime,
    ) -> UserRecord:
        row = UserRow(
            id=f"U_{uuid4().hex}",
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            created_at=created_at,
        )
        try:
            with self._sessions() as session:
                session.add(row)
                session.commit()
        except IntegrityError as exc:
            # The unique e-mail index is the last line of defence: two
            # simultaneous submits of the same address still end in one account.
            raise EmailAlreadyRegistered("该邮箱已注册。") from exc
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        return _to_record(row)


class SqlSessionTokenStore:
    """Default token store: a row per login, revocable and expiring in SQL."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None:
        row = AuthSessionRow(
            id=f"AS_{uuid4().hex}",
            user_id=user_id,
            token_hash=token_hash,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        try:
            with self._sessions() as session:
                session.add(row)
                session.commit()
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc

    def resolve(self, token_hash: str) -> SessionToken | None:
        try:
            with self._sessions() as session:
                row: AuthSessionRow | None = session.scalar(
                    select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
                )
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        if row is None or row.revoked_at is not None:
            return None
        return SessionToken(user_id=row.user_id, expires_at=as_utc(row.expires_at))

    def revoke(self, token_hash: str) -> None:
        try:
            with self._sessions() as session:
                row: AuthSessionRow | None = session.scalar(
                    select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
                )
                if row is not None:
                    row.revoked_at = datetime.now(UTC)
                    session.commit()
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc


class RedisClient(Protocol):
    """The four Redis calls this adapter needs; lets tests pass a fake."""

    def set(self, name: str, value: str, ex: int | None = None) -> object: ...

    def get(self, name: str) -> str | bytes | None: ...

    def delete(self, *names: str) -> object: ...


class RedisSessionTokenStore:
    """Session tokens as Redis keys with a native TTL (no sweeping needed).

    Accounts stay in SQL: Redis is the fast, expiring half of the session, which
    is exactly the part that benefits from a TTL. The payload repeats the
    expiry so a client that lost its TTL configuration still fails closed.
    """

    KEY_PREFIX = "synapse:auth:sess:"

    def __init__(self, client: RedisClient, *, ttl_s: int) -> None:
        self._client = client
        self._ttl_s = ttl_s

    def create(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None:
        payload = json.dumps(
            {"user_id": user_id, "expires_at": expires_at.astimezone(UTC).isoformat()}
        )
        try:
            self._client.set(self._key(token_hash), payload, ex=self._ttl_s)
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def resolve(self, token_hash: str) -> SessionToken | None:
        try:
            raw = self._client.get(self._key(token_hash))
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            payload = json.loads(text)
            user_id = payload["user_id"]
            expires_at = datetime.fromisoformat(payload["expires_at"])
        except (ValueError, KeyError, TypeError):
            # A corrupt value must not authenticate anybody.
            return None
        if not isinstance(user_id, str):
            return None
        return SessionToken(user_id=user_id, expires_at=as_utc(expires_at))

    def revoke(self, token_hash: str) -> None:
        try:
            self._client.delete(self._key(token_hash))
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def _key(self, token_hash: str) -> str:
        return f"{self.KEY_PREFIX}{token_hash}"
