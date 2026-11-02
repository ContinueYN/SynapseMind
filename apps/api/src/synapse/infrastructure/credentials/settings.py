"""Environment contract for per-user model credentials.

``SYNAPSE_CREDENTIAL_KEY`` is the master key that encrypts every user's model
key. Empty (the default) disables credential storage: the settings endpoints
then answer 503 for writes and report ``encryption_ready=false``, instead of
writing plaintext.

The value can be a real Fernet key or any high-entropy passphrase; see
``crypto.py`` for the derivation. Losing it means every saved credential must be
entered again — the ciphertext is not recoverable, which is the point.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CredentialSettings:
    """Resolved BYOK configuration; frozen so a request cannot mutate it."""

    master_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CredentialSettings:
        source = os.environ if env is None else env
        value = source.get("SYNAPSE_CREDENTIAL_KEY", "").strip()
        return cls(master_key=value or None)
