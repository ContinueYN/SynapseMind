"""The ``user_model_credentials`` table.

One row per user (``user_id`` is unique and cascades from ``users``), so saving a
new key replaces the old one instead of accumulating secrets. Only the ciphertext
and a four-character mask are stored; the plaintext key never reaches this layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from synapse.infrastructure.auth.db import Base


class UserModelCredentialRow(Base):
    """A user's own OpenAI-compatible key, encrypted at rest."""

    __tablename__ = "user_model_credentials"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # Fernet token; never the API key itself.
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_last4: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
