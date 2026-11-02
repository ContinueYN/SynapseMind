"""Per-user encrypted model credentials (BYOK).

Revision ID: 0003_model_credentials
Revises: 0002_session_rotation
Create Date: 2026-11-02

``user_model_credentials`` holds one row per account:

* ``encrypted_key`` is a Fernet ciphertext; the plaintext key is never stored,
  logged or returned. ``key_last4`` exists only for the masked settings display.
* ``user_id`` is unique and cascades from ``users`` — deleting an account
  removes its secret with it.
* ``last_verified_at`` records the last successful "test connection" for the
  *stored* key; saving a new key resets it.

The table is created in the same database as the account tables (SQLite locally,
PostgreSQL in compose). A missing migration surfaces as a 503 with an
``alembic upgrade head`` hint instead of a 500.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_model_credentials"
down_revision: str | None = "0002_session_rotation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_model_credentials",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_model_credentials_user_id",
        "user_model_credentials",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_model_credentials_user_id",
        table_name="user_model_credentials",
    )
    op.drop_table("user_model_credentials")