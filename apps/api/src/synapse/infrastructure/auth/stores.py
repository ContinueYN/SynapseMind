"""Adapters for the two auth ports: user records and one-time session tokens.

``SqlUserStore``          accounts live in ``users`` (SQLite or PostgreSQL).
``SqlSessionTokenStore``  default token store: rows in ``auth_sessions``.
``RedisSessionTokenStore`` optional token store: keys with a native TTL, used
                           when ``SYNAPSE_REDIS_URL`` is configured.

Both SQL adapters translate ``SQLAlchemyError`` into ``AuthStoreUnavailable`` so
a missing migration (or an unreachable database) becomes a 503 with a migration
hint instead of an opaque 500. Redis failures do the same.

Only digests are stored: a leaked ``auth_sessions`` table cannot be replayed as
a cookie. Consumption is atomic because a login ticket is a one-time credential;
an ordinary session is read with the non-mutating ``lookup`` instead:

* SQL: ``consume`` uses a conditional ``UPDATE ... WHERE used_at IS NULL``; a
  losing racer sees ``rowcount == 0`` and is told the token was already used.
  ``lookup`` is a plain select and never writes.
* Redis: ``consume`` uses ``GETDEL`` and the adapter writes a ``used:<sha>``
  tombstone, so a replay is distinguishable from a token that never existed.
  ``lookup`` uses ``GET`` and leaves the live key in place.
  A family-revocation key closes every token of a chain at once.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from synapse.application.auth.service import (
    AuthStoreUnavailable,
    EmailAlreadyRegistered,
    TokenState,
    TokenStatus,
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
    """Default token store: one row per issued cookie.

    Login-ticket rows are consumed exactly once; ordinary-session rows are only
    ever read by ``lookup`` and stay reusable until revoked or expired.
    """

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def issue(
        self,
        *,
        token_hash: str,
        user_id: str,
        family_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        row = AuthSessionRow(
            id=f"AS_{uuid4().hex}",
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            created_at=created_at,
            expires_at=expires_at,
        )
        try:
            with self._sessions() as session:
                session.add(row)
                session.commit()
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc

    def consume(self, token_hash: str, *, now: datetime) -> TokenState:
        """Atomically spend one digest (the login-ticket path).

        The read is only used to describe the outcome; the authoritative step is
        the conditional update. Two concurrent requests cannot both see
        ``rowcount == 1``: the loser is told ``used`` and the use case then
        revokes the family.
        """

        try:
            with self._sessions() as session:
                row: AuthSessionRow | None = session.scalar(
                    select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
                )
                if row is None:
                    return TokenState.unknown()
                state = _state_for(row)
                if state.status != "active":
                    return state
                result = cast(
                    "CursorResult[Any]",
                    session.execute(
                        update(AuthSessionRow)
                        .where(
                            AuthSessionRow.token_hash == token_hash,
                            AuthSessionRow.used_at.is_(None),
                        )
                        .values(used_at=now)
                        .execution_options(synchronize_session=False)
                    ),
                )
                if result.rowcount != 1:
                    session.rollback()
                    return TokenState(
                        status="used",
                        user_id=row.user_id,
                        family_id=row.family_id,
                        expires_at=as_utc(row.expires_at),
                    )
                session.commit()
                return state
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc

    def lookup(self, token_hash: str, *, now: datetime) -> TokenState:
        """Read one digest without spending it (the ordinary-session path)."""

        del now  # expiry is enforced by the use case, not by this read
        try:
            with self._sessions() as session:
                row: AuthSessionRow | None = session.scalar(
                    select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
                )
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc
        return TokenState.unknown() if row is None else _state_for(row)

    def revoke_family(self, family_id: str, *, now: datetime) -> None:
        try:
            with self._sessions() as session:
                session.execute(
                    update(AuthSessionRow)
                    .where(
                        AuthSessionRow.family_id == family_id,
                        AuthSessionRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                    .execution_options(synchronize_session=False)
                )
                session.commit()
        except SQLAlchemyError as exc:
            raise AuthStoreUnavailable(_STORE_HINT) from exc


def _state_for(row: AuthSessionRow) -> TokenState:
    expires_at = as_utc(row.expires_at)
    status: TokenStatus
    # ``used`` wins over ``revoked``: replaying a consumed login ticket is the
    # theft signal even when the family was already closed (logout). Ordinary
    # rows are never consumed, so they still report their revocation here.
    if row.used_at is not None:
        status = "used"
    elif row.revoked_at is not None:
        status = "revoked"
    else:
        status = "active"
    return TokenState(
        status=status,
        user_id=row.user_id,
        family_id=row.family_id,
        expires_at=expires_at,
    )


class RedisClient(Protocol):
    """The four Redis calls this adapter needs; lets tests pass a fake."""

    def set(self, name: str, value: str, ex: int | None = None) -> object: ...

    def get(self, name: str) -> str | bytes | None: ...

    def getdel(self, name: str) -> str | bytes | None: ...

    def delete(self, *names: str) -> object: ...


class RedisSessionTokenStore:
    """Session tokens as Redis keys with a native TTL (no sweeping needed).

    Accounts stay in SQL: Redis is the fast, expiring half of the session, which
    is exactly the part that benefits from a TTL. The payload repeats the
    family and expiry so a client that lost its TTL configuration still fails
    closed. ``GETDEL`` makes consumption atomic on Redis 7; the tombstone keeps
    the difference between "already used" (theft signal) and "never issued".
    """

    KEY_PREFIX = "synapse:auth:sess:"
    USED_PREFIX = "synapse:auth:used:"
    FAMILY_PREFIX = "synapse:auth:fam:"

    def __init__(self, client: RedisClient, *, ttl_s: int) -> None:
        self._client = client
        self._ttl_s = ttl_s

    def issue(
        self,
        *,
        token_hash: str,
        user_id: str,
        family_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        payload = json.dumps(
            {
                "user_id": user_id,
                "family_id": family_id,
                "created_at": created_at.astimezone(UTC).isoformat(),
                "expires_at": expires_at.astimezone(UTC).isoformat(),
            }
        )
        try:
            self._client.set(self._key(token_hash), payload, ex=self._ttl_s)
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def consume(self, token_hash: str, *, now: datetime) -> TokenState:
        del now  # the Redis TTL and the payload expiry bound the value
        try:
            raw = self._client.getdel(self._key(token_hash))
            if raw is None:
                tombstone = self._client.get(self._used_key(token_hash))
                if tombstone is None:
                    return TokenState.unknown()
                state = _parse(tombstone)
                if state is None:
                    return TokenState.unknown()
                return _payload_state(state, "used")
            state = _parse(raw)
            if state is None:
                return TokenState.unknown()
            if self._family_revoked(state.family_id):
                return _payload_state(state, "revoked")
            # Write the tombstone before reporting active: a second request then
            # sees ``used`` instead of ``unknown``. Both outcomes are a 401, but
            # only the tombstone can raise the theft alarm.
            self._client.set(self._used_key(token_hash), _raw_text(raw), ex=self._ttl_s)
            return _payload_state(state, "active")
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def lookup(self, token_hash: str, *, now: datetime) -> TokenState:
        """Read one digest without removing it (the ordinary-session path)."""

        del now  # expiry is enforced by the use case
        try:
            raw = self._client.get(self._key(token_hash))
            if raw is None:
                tombstone = self._client.get(self._used_key(token_hash))
                if tombstone is None:
                    return TokenState.unknown()
                state = _parse(tombstone)
                if state is None:
                    return TokenState.unknown()
                return _payload_state(state, "used")
            state = _parse(raw)
            if state is None:
                return TokenState.unknown()
            if self._family_revoked(state.family_id):
                return _payload_state(state, "revoked")
            return _payload_state(state, "active")
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def revoke_family(self, family_id: str, *, now: datetime) -> None:
        del now  # the family key expires with the longest-lived token it covers
        try:
            self._client.set(self._family_key(family_id), "1", ex=self._ttl_s)
        except RedisError as exc:
            raise AuthStoreUnavailable(_REDIS_HINT) from exc

    def _family_revoked(self, family_id: str | None) -> bool:
        if family_id is None:
            return False
        return self._client.get(self._family_key(family_id)) is not None

    def _key(self, token_hash: str) -> str:
        return f"{self.KEY_PREFIX}{token_hash}"

    def _used_key(self, token_hash: str) -> str:
        return f"{self.USED_PREFIX}{token_hash}"

    def _family_key(self, family_id: str) -> str:
        return f"{self.FAMILY_PREFIX}{family_id}"


class _Payload:
    __slots__ = ("user_id", "family_id", "expires_at")

    def __init__(self, user_id: str, family_id: str, expires_at: datetime) -> None:
        self.user_id = user_id
        self.family_id = family_id
        self.expires_at = expires_at


def _payload_state(payload: _Payload, status: TokenStatus) -> TokenState:
    return TokenState(
        status=status,
        user_id=payload.user_id,
        family_id=payload.family_id,
        expires_at=payload.expires_at,
    )


def _raw_text(raw: str | bytes) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


def _parse(raw: str | bytes) -> _Payload | None:
    text = _raw_text(raw)
    try:
        payload = json.loads(text)
        user_id = payload["user_id"]
        family_id = payload["family_id"]
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except (ValueError, KeyError, TypeError):
        # A corrupt value must not authenticate anybody.
        return None
    if not isinstance(user_id, str) or not isinstance(family_id, str):
        return None
    return _Payload(user_id=user_id, family_id=family_id, expires_at=as_utc(expires_at))
