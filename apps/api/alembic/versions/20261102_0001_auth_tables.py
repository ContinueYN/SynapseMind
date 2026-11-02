"""Auth tables: users and auth_sessions.

Revision ID: 0001_auth
Revises:
Create Date: 2026-11-02

This is the whole schema for a self-hosted single-owner deployment. There are no
tenant, role or classroom tables on purpose: one instance has one owner account,
plus any account the operator explicitly allows.

Dialect notes:

* ``DateTime(timezone=True)`` maps to ``TIMESTAMP WITH TIME ZONE`` on PostgreSQL
  and to its text-based DATETIME on SQLite. Reads normalize naive SQLite values
  to UTC in ``synapse.infrastructure.auth.db.as_utc``.
* ``password_hash`` is a variable-length Argon2id digest, hence ``Text``.
* ``token_hash`` is the SHA-256 hex of the cookie value; the raw token is never
  stored, so a database dump cannot be replayed as a login.
* Unique e-mail/token indexes are created explicitly (instead of inline
  ``UNIQUE`` constraints) so their names match the SQLAlchemy models and
  ``alembic check`` stays clean.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_auth"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)
    op.create_index(
        "ix_auth_sessions_token_hash",
        "auth_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_auth_sessions_expires_at",
        "auth_sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")