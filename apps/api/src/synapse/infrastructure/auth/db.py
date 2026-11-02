"""SQLAlchemy 2.x tables and engine setup for the auth layer.

Two tables only, because this is a single-owner deployment:

``users``          one row per account (first registration wins by policy)
``auth_sessions``  opaque session-token digests with expiry and revocation

Tables are **not** created at import time or on first request. Schema belongs to
Alembic (``alembic upgrade head``), which keeps production PostgreSQL honest and
lets tests use ``Base.metadata.create_all`` on a throwaway SQLite file.

URL handling accepts both worlds the compose contract promises:

* ``sqlite+pysqlite:///var/auth.sqlite3`` (default, local)
* ``postgresql+psycopg://synapse:synapse@postgres:5432/synapse`` (compose)

A bare ``postgres://`` / ``postgresql://`` URL is rewritten to the psycopg
driver, so an operator does not have to know the SQLAlchemy dialect spelling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    """Declarative base shared by the models and the Alembic migration."""


class UserRow(Base):
    """One owner account (plus any account the operator explicitly allows)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Argon2id digest; never the password, never reversible.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthSessionRow(Base):
    """Server-side half of the cookie, stored as a SHA-256 token digest."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def normalize_database_url(url: str) -> str:
    """Accept the compose spellings without letting SQLAlchemy guess."""

    cleaned = url.strip()
    if not cleaned:
        raise ValueError("SYNAPSE_DATABASE_URL is empty")
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned[len("postgresql://") :]
    return cleaned


def create_auth_engine(url: str) -> Engine:
    """Build an engine for SQLite or PostgreSQL.

    SQLite needs ``check_same_thread=False`` because FastAPI runs sync routes in
    a thread pool; a file path's parent directory is created so a mistyped
    directory fails as a clear permission error rather than "unable to open
    database file".
    """

    normalized = normalize_database_url(url)
    parsed = make_url(normalized)
    if parsed.get_backend_name() == "sqlite":
        database = parsed.database or ""
        if database and database != ":memory:":
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        return create_engine(normalized, connect_args={"check_same_thread": False})
    return create_engine(normalized, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def as_utc(value: datetime) -> datetime:
    """Normalize a timestamp read back from the database.

    SQLite has no timezone type: ``DateTime(timezone=True)`` round-trips as a
    naive datetime. Comparing that to an aware ``datetime.now(UTC)`` raises, so
    every read goes through this helper. PostgreSQL already returns aware values.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
