"""Per-user model credentials (BYOK), encrypted at rest.

Each account may store **its own** OpenAI-compatible model key. The plaintext
key only exists inside this process, between a decrypt and the provider call:

* the store only ever receives a ciphertext (``SecretCipher``);
* the public view exposes at most the last four characters;
* nothing here logs, audits or echoes a key.

The service validates provider/base URL/model/key and asks a ``RemoteUrlGuard``
to vet the URL, because the server — not the browser — calls it. That guard is a
port: the real adapter resolves the host and refuses private addresses, while
tests can pass a stub.

When ``SYNAPSE_CREDENTIAL_KEY`` is missing the cipher is ``None``. Storage then
fails closed (503 with an actionable message) instead of falling back to
plaintext.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit


# The four presets the settings page offers. ``custom`` has no default host or
# model: the user must supply both, and the URL guard treats it as untrusted.
@dataclass(frozen=True, slots=True)
class ProviderPreset:
    name: str
    label: str
    base_url: str | None
    model: str | None


PROVIDER_PRESETS: Mapping[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        name="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    ),
    "openai": ProviderPreset(
        name="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-4o-mini",
    ),
    "custom": ProviderPreset(
        name="custom",
        label="自定义（OpenAI 兼容）",
        base_url=None,
        model=None,
    ),
}

# Hosts that are trusted by name. The guard skips DNS resolution for them so an
# offline self-hosted box can still save a recognized provider, and a hostile
# resolver cannot redirect a known host to a private address through our own
# allow-list logic (the TLS client still validates the certificate).
KNOWN_PROVIDER_HOSTS: frozenset[str] = frozenset(
    {
        "api.deepseek.com",
        "api.openai.com",
        "openrouter.ai",
    }
)

_MAX_BASE_URL = 300
_MAX_MODEL = 120
_MIN_KEY = 8
_MAX_KEY = 4096
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")

_ENCRYPTION_MISSING = (
    "未配置 SYNAPSE_CREDENTIAL_KEY，无法加密保存模型密钥；请先生成一个主密钥并重启 API。"
)
_STORED_BUT_LOCKED = (
    "SYNAPSE_CREDENTIAL_KEY 未配置或与保存时不一致，已保存的模型密钥无法解密；"
    "请配置同一个主密钥，或重新保存密钥。"
)


class CredentialError(RuntimeError):
    """Base class for BYOK failures the API maps to a status."""


class CredentialValidationError(CredentialError, ValueError):
    """The provider/base URL/model/key pair is not acceptable (422)."""


class CredentialStoreDisabled(CredentialError):
    """No master key: encryption is unavailable, so writes fail closed (503)."""


class CredentialStoreUnavailable(CredentialError):
    """The credential table is configured but not usable (503)."""


class CredentialDecryptionError(CredentialError):
    """A stored ciphertext cannot be opened with the configured master key."""


class CredentialMissing(CredentialError):
    """No saved credential exists (or no key was supplied) for this test."""


@dataclass(frozen=True, slots=True)
class StoredCredential:
    """The encrypted row; ``encrypted_key`` is ciphertext, never plaintext."""

    user_id: str
    provider: str
    base_url: str
    model: str
    encrypted_key: str
    key_last4: str
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class SecretCredential:
    """The decrypted view, alive only for one provider call."""

    provider: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True, slots=True)
class PublicCredential:
    """What the settings page may see; never includes the key.

    ``configured`` means "a key is stored **and** usable right now", not merely
    "a row exists". A row written with a different master key is unusable, so
    reporting it as configured would promise model calls that silently fall back
    to the server key; ``warning`` explains the situation instead.
    """

    configured: bool
    provider: str | None
    base_url: str | None
    model: str | None
    key_last4: str | None
    last_verified_at: datetime | None
    encryption_ready: bool
    warning: str | None


@dataclass(frozen=True, slots=True)
class CredentialInput:
    """A full save: all four fields come from the form."""

    provider: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True, slots=True)
class CredentialTestInput:
    """A test request; every field is optional and falls back to the saved row."""

    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


@dataclass(frozen=True, slots=True)
class CredentialTestResult:
    """Outcome of one provider probe; ``message`` never contains the key."""

    ok: bool
    latency_ms: int
    model: str
    message: str


class SecretCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class CredentialStore(Protocol):
    def get(self, user_id: str) -> StoredCredential | None: ...

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
    ) -> StoredCredential: ...

    def delete(self, user_id: str) -> None: ...

    def mark_verified(self, user_id: str, *, verified_at: datetime) -> None: ...


class RemoteUrlGuard(Protocol):
    """Reject a server-side URL that could reach the deployment's own network."""

    def check(self, url: str) -> None: ...


class ModelTester(Protocol):
    """One OpenAI-compatible round trip against a candidate credential."""

    def probe(self, credential: SecretCredential) -> CredentialTestResult: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_provider(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned not in PROVIDER_PRESETS:
        allowed = "、".join(sorted(PROVIDER_PRESETS))
        raise CredentialValidationError(f"未知的模型服务商 {value!r}；可选：{allowed}。")
    return cleaned


def normalize_base_url(value: str, *, provider: str) -> str:
    """Require HTTPS, reject embedded credentials and normalize the path."""

    preset = PROVIDER_PRESETS[provider]
    raw = value.strip()
    if not raw:
        if preset.base_url is None:
            raise CredentialValidationError("自定义服务商需要填写 base_url（必须使用 https://）。")
        return preset.base_url
    if len(raw) > _MAX_BASE_URL:
        raise CredentialValidationError(f"base_url 不能超过 {_MAX_BASE_URL} 个字符。")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise CredentialValidationError("base_url 必须使用 https://（不接收 http 或其它协议）。")
    if not parts.hostname:
        raise CredentialValidationError("base_url 缺少主机名。")
    if parts.username is not None or parts.password is not None:
        # Credentials in the URL would be stored, logged and sent as-is.
        raise CredentialValidationError("base_url 不能包含用户名或密码。")
    if parts.query or parts.fragment:
        raise CredentialValidationError("base_url 不能包含查询串或片段。")
    path = parts.path.rstrip("/")
    netloc = parts.netloc.lower()
    return f"https://{netloc}{path}"


def validate_model(value: str, *, provider: str) -> str:
    preset = PROVIDER_PRESETS[provider]
    raw = value.strip()
    if not raw:
        if preset.model is None:
            raise CredentialValidationError("自定义服务商需要填写 model 名称。")
        return preset.model
    if not _MODEL_PATTERN.fullmatch(raw):
        raise CredentialValidationError(
            "model 只能包含字母、数字和 . _ : / -，且不超过 120 个字符。"
        )
    return raw


def validate_api_key(value: str) -> str:
    cleaned = value.strip()
    if not _MIN_KEY <= len(cleaned) <= _MAX_KEY:
        raise CredentialValidationError(f"api_key 长度需要在 {_MIN_KEY}–{_MAX_KEY} 个字符之间。")
    if any(char.isspace() or ord(char) < 32 for char in cleaned):
        raise CredentialValidationError("api_key 不能包含空白或控制字符。")
    return cleaned


class CredentialService:
    """Save/resolve/test one user's model credential."""

    def __init__(
        self,
        *,
        store: CredentialStore,
        cipher: SecretCipher | None,
        guard: RemoteUrlGuard,
        tester: ModelTester,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._guard = guard
        self._tester = tester
        self._clock = clock

    @property
    def encryption_ready(self) -> bool:
        return self._cipher is not None

    def get_public(self, user_id: str) -> PublicCredential:
        stored = self._store.get(user_id)
        ready = self.encryption_ready
        if stored is None:
            return PublicCredential(
                configured=False,
                provider=None,
                base_url=None,
                model=None,
                key_last4=None,
                last_verified_at=None,
                encryption_ready=ready,
                warning=None if ready else _ENCRYPTION_MISSING,
            )
        # A row is not the same as a usable key: the master key may have changed
        # since it was written. Probe decryption once so the page can say so.
        usable = False
        if ready:
            try:
                self._require_cipher().decrypt(stored.encrypted_key)
                usable = True
            except CredentialError:
                usable = False
        return PublicCredential(
            configured=usable,
            provider=stored.provider,
            base_url=stored.base_url,
            model=stored.model,
            key_last4=stored.key_last4,
            last_verified_at=stored.last_verified_at,
            encryption_ready=ready,
            warning=None if usable else _STORED_BUT_LOCKED,
        )

    def save(self, user_id: str, payload: CredentialInput) -> PublicCredential:
        cipher = self._require_cipher()
        secret = self._validate(payload)
        now = self._clock()
        stored = self._store.upsert(
            user_id,
            provider=secret.provider,
            base_url=secret.base_url,
            model=secret.model,
            encrypted_key=cipher.encrypt(secret.api_key),
            key_last4=secret.api_key[-4:],
            updated_at=now,
        )
        return self._public(stored)

    def delete(self, user_id: str) -> None:
        self._store.delete(user_id)

    def resolve(self, user_id: str) -> SecretCredential | None:
        """Return the decrypted credential for one user, or ``None``.

        Raises :class:`CredentialDecryptionError` when a row exists but cannot be
        opened; the model runtime treats that as "no credential" and falls back
        to the server key instead of failing the request.
        """

        stored = self._store.get(user_id)
        if stored is None:
            return None
        cipher = self._require_cipher()
        try:
            plaintext = cipher.decrypt(stored.encrypted_key)
        except Exception as exc:  # the concrete error may echo the ciphertext
            raise CredentialDecryptionError(_STORED_BUT_LOCKED) from exc
        return SecretCredential(
            provider=stored.provider,
            base_url=stored.base_url,
            model=stored.model,
            api_key=plaintext,
        )

    def test(self, user_id: str, payload: CredentialTestInput) -> CredentialTestResult:
        """Probe a candidate credential; a saved one is marked verified on success."""

        self._require_cipher()
        secret = self._effective(user_id, payload)
        result = self._tester.probe(secret)
        if result.ok and payload.api_key is None:
            self._store.mark_verified(user_id, verified_at=self._clock())
        return result

    def _effective(self, user_id: str, payload: CredentialTestInput) -> SecretCredential:
        stored = self._store.get(user_id)
        saved: SecretCredential | None = None
        if stored is not None:
            cipher = self._require_cipher()
            try:
                plaintext = cipher.decrypt(stored.encrypted_key)
            except Exception as exc:  # see ``resolve``
                raise CredentialDecryptionError(_STORED_BUT_LOCKED) from exc
            saved = SecretCredential(
                provider=stored.provider,
                base_url=stored.base_url,
                model=stored.model,
                api_key=plaintext,
            )

        provider_raw = payload.provider
        if provider_raw is None or not provider_raw.strip():
            if saved is None:
                raise CredentialMissing("还没有保存的模型凭据，请填写 provider 和 api_key。")
            provider_raw = saved.provider
        provider = normalize_provider(provider_raw)

        same_provider_saved = saved is not None and saved.provider == provider
        base_url = payload.base_url
        if base_url is None:
            base_url = saved.base_url if saved is not None and same_provider_saved else ""
        model = payload.model
        if model is None:
            model = saved.model if saved is not None and same_provider_saved else ""

        api_key = payload.api_key
        if api_key is None:
            if saved is None:
                raise CredentialMissing("还没有保存的模型密钥，请填写 api_key。")
            if not same_provider_saved:
                raise CredentialMissing("切换模型服务商时需要重新填写 api_key。")
            api_key = saved.api_key

        return self._validate(
            CredentialInput(
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
            )
        )

    def _validate(self, payload: CredentialInput) -> SecretCredential:
        provider = normalize_provider(payload.provider)
        base_url = normalize_base_url(payload.base_url, provider=provider)
        model = validate_model(payload.model, provider=provider)
        api_key = validate_api_key(payload.api_key)
        # The server is the one that will call this URL; vet it before saving.
        self._guard.check(base_url)
        return SecretCredential(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
        )

    def _require_cipher(self) -> SecretCipher:
        if self._cipher is None:
            raise CredentialStoreDisabled(_ENCRYPTION_MISSING)
        return self._cipher

    @staticmethod
    def _public(stored: StoredCredential) -> PublicCredential:
        return PublicCredential(
            configured=True,
            provider=stored.provider,
            base_url=stored.base_url,
            model=stored.model,
            key_last4=stored.key_last4,
            last_verified_at=stored.last_verified_at,
            encryption_ready=True,
            warning=None,
        )
