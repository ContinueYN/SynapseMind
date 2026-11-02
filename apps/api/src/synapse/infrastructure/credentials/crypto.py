"""Encryption for the per-user model keys.

``cryptography``'s Fernet gives authenticated symmetric encryption with a
minimal API: a stolen row cannot be decrypted without the master key, and a
tampered ciphertext fails authentication instead of producing garbage.

The master key comes from ``SYNAPSE_CREDENTIAL_KEY``. Operators can paste a
valid Fernet key (``Fernet.generate_key()``), or any high-entropy passphrase:
the passphrase is hashed with SHA-256 and urlsafe-base64 encoded into a Fernet
key, which is deterministic, so the same env value always decrypts what it
wrote. An empty value disables storage entirely (no plaintext fallback).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from synapse.application.credentials.service import CredentialDecryptionError

_FERNET_KEY_BYTES = 32


class FernetCipher:
    """A thin ``SecretCipher`` adapter over one Fernet key."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_secret(cls, secret: str | None) -> FernetCipher | None:
        """Build from ``SYNAPSE_CREDENTIAL_KEY``; ``None`` when it is blank."""

        value = (secret or "").strip()
        if not value:
            return None
        return cls(_derive_key(value))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise CredentialDecryptionError(
                "已保存的模型密钥无法解密；请检查 SYNAPSE_CREDENTIAL_KEY 是否与保存时一致。"
            ) from exc


def _derive_key(secret: str) -> bytes:
    """Accept a real Fernet key, otherwise derive one from the passphrase."""

    candidate = secret.encode("utf-8")
    if _is_fernet_key(candidate):
        return candidate
    digest = hashlib.sha256(candidate).digest()
    return base64.urlsafe_b64encode(digest)


def _is_fernet_key(candidate: bytes) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(candidate)
    except (ValueError, TypeError):
        return False
    if len(decoded) != _FERNET_KEY_BYTES:
        return False
    try:
        Fernet(candidate)
    except (ValueError, TypeError):
        return False
    return True
