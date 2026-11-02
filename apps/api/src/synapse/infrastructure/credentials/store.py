"""SQL adapter for the per-user credential rows.

One short session per operation, like the auth stores. A database error becomes
``CredentialStoreUnavailable`` (503) instead of an opaque 500; a missing
migration is the common cause.

``upsert`` looks the row up first and updates it, which keeps ``created_at``
stable across saves. The unique index on ``user_id`` is still the final guard
against two concurrent first saves.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from synapse.application.credentials import (
    CredentialStoreUnavailable,
    StoredCredential,
)
from synapse.infrastructure.auth.db import as_utc
from synapse.infrastructure.credentials.db import UserModelCredentialRow

_STORE_HINT = "模型凭据存储不可用；请检查 SYNAPSE_DATABASE_URL，并先运行 `alembic upgrade head`。"


def _to_record(row: UserModelCredentialRow) -> StoredCredential:
    return StoredCredential(
        user_id=row.user_id,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        encrypted_key=row.encrypted_key,
        key_last4=row.key_last4,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        last_verified_at=(None if row.last_verified_at is None else as_utc(row.last_verified_at)),
    )


class SqlCredentialStore:
    """Encrypted credential rows in SQLite or PostgreSQL."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, user_id: str) -> StoredCredential | None:
        try:
            with self._sessions() as session:
                row: UserModelCredentialRow | None = session.scalar(
                    select(UserModelCredentialRow).where(UserModelCredentialRow.user_id == user_id)
                )
        except SQLAlchemyError as exc:
            raise CredentialStoreUnavailable(_STORE_HINT) from exc
        return None if row is None else _to_record(row)

    def upsert(
        self,
        user_id: str,
        *,
        provider: str,
        base_url: str,
        model: str,
        encrypted_key: str,
        key_last4: str,
        updated_at: datetime,
    ) -> StoredCredential:
        try:
            with self._sessions() as session:
                row: UserModelCredentialRow | None = session.scalar(
                    select(UserModelCredentialRow).where(UserModelCredentialRow.user_id == user_id)
                )
                if row is None:
                    row = UserModelCredentialRow(
                        id=f"MC_{uuid4().hex}",
                        user_id=user_id,
                        provider=provider,
                        base_url=base_url,
                        model=model,
                        encrypted_key=encrypted_key,
                        key_last4=key_last4,
                        created_at=updated_at,
                        updated_at=updated_at,
                    )
                    session.add(row)
                else:
                    row.provider = provider
                    row.base_url = base_url
                    row.model = model
                    row.encrypted_key = encrypted_key
                    row.key_last4 = key_last4
                    row.updated_at = updated_at
                    # A new key has not been verified yet, even if the previous
                    # one was; claiming otherwise would be a fabricated check.
                    row.last_verified_at = None
                session.commit()
                return _to_record(row)
        except IntegrityError as exc:
            raise CredentialStoreUnavailable("保存模型凭据时发生冲突，请重试。") from exc
        except SQLAlchemyError as exc:
            raise CredentialStoreUnavailable(_STORE_HINT) from exc

    def delete(self, user_id: str) -> None:
        try:
            with self._sessions() as session:
                row: UserModelCredentialRow | None = session.scalar(
                    select(UserModelCredentialRow).where(UserModelCredentialRow.user_id == user_id)
                )
                if row is not None:
                    session.delete(row)
                    session.commit()
        except SQLAlchemyError as exc:
            raise CredentialStoreUnavailable(_STORE_HINT) from exc

    def mark_verified(self, user_id: str, *, verified_at: datetime) -> None:
        try:
            with self._sessions() as session:
                row: UserModelCredentialRow | None = session.scalar(
                    select(UserModelCredentialRow).where(UserModelCredentialRow.user_id == user_id)
                )
                if row is not None:
                    row.last_verified_at = verified_at
                    session.commit()
        except SQLAlchemyError as exc:
            raise CredentialStoreUnavailable(_STORE_HINT) from exc
