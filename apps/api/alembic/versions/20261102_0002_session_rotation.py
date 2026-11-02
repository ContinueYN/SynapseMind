"""One-time session rotation: session families and the ``used_at`` marker.

Revision ID: 0002_session_rotation
Revises: 0001_auth
Create Date: 2026-11-02

The cookie became a one-time credential in this slice. Two columns carry that:

``family_id``  groups every token produced by one login's rotation chain, so a
               logout or a replay alarm can revoke the whole chain at once.
``used_at``    non-null once the digest has been consumed; a second presentation
               is treated as session theft.

Existing rows are backfilled in place: each pre-rotation token becomes its own
one-token family (``family_id = id``) and is still unconsumed (``used_at NULL``),
which keeps already-issued cookies working until their normal expiry.

SQLite needs a table rebuild to add a ``NOT NULL`` column with a backfill, so the
constraint is applied through ``batch_alter_table``. PostgreSQL takes the same
path through a plain ``ALTER TABLE ... SET NOT NULL``. ``used_at`` stays nullable
by design: ``NULL`` means "not consumed yet".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_session_rotation"
down_revision: str | None = "0001_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("family_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill before the NOT NULL constraint: an issued cookie must keep working
    # across the deploy, and each old row is its own family.
    op.execute("UPDATE auth_sessions SET family_id = id WHERE family_id IS NULL")
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.alter_column(
            "family_id",
            existing_type=sa.String(length=40),
            nullable=False,
        )
    op.create_index(
        "ix_auth_sessions_family_id",
        "auth_sessions",
        ["family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_family_id", table_name="auth_sessions")
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_column("used_at")
        batch_op.drop_column("family_id")