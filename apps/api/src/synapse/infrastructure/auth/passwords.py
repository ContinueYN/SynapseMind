"""Argon2id password hashing.

Argon2id is the default of ``argon2-cffi`` and the recommended password KDF. The
digest string carries its own parameters, so a future cost bump stays readable;
``verify`` only reports whether the supplied password matches, never the stored
digest's internals.

A digest is never truncated, logged, or compared with ``==``: every check goes
through the library's constant-time verification.
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2PasswordHasher:
    """Adapter behind ``synapse.application.auth.PasswordHasher``."""

    def __init__(self, hasher: _Argon2 | None = None) -> None:
        # Tests may pass a cheaper hasher; production keeps the library default
        # (m=64 MiB, t=3, p=4), which is deliberate, not an accident.
        self._hasher = hasher or _Argon2()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            # A mismatch and a corrupt/foreign digest are both "not this
            # password". Distinguishing them would turn a data bug into an
            # account-enumeration oracle.
            return False
