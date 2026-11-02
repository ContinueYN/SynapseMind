"""Per-user encrypted model credentials: storage, masking, validation, probe.

Two layers are covered:

* the application service (presets, validation, masking, "saved key is used for
  the test" semantics) with an in-memory fake store, no HTTP;
* the real app (gate + login-ticket exchange + Alembic + SQLite): the exact JSON
  contract in the task, 422/503 paths, and that two accounts never see each
  other's key.

The key itself must never come back from any endpoint, so those assertions are
explicit rather than implied by the masked DTO.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import cast

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from alembic import command
from synapse.api.deps import Container, build_container
from synapse.api.main import create_app
from synapse.application.credentials import (
    KNOWN_PROVIDER_HOSTS,
    PROVIDER_PRESETS,
    CredentialDecryptionError,
    CredentialInput,
    CredentialMissing,
    CredentialService,
    CredentialStoreDisabled,
    CredentialTestInput,
    CredentialTestResult,
    CredentialValidationError,
    ModelTester,
    RemoteUrlGuard,
    SecretCipher,
    SecretCredential,
    StoredCredential,
    normalize_base_url,
    normalize_provider,
    validate_api_key,
    validate_model,
)
from synapse.infrastructure.auth.db import build_session_factory, create_auth_engine
from synapse.infrastructure.credentials.crypto import FernetCipher
from synapse.infrastructure.credentials.db import UserModelCredentialRow
from synapse.infrastructure.credentials.guard import SsrfGuard
from synapse.infrastructure.credentials.probe import HttpxModelTester
from synapse.infrastructure.credentials.store import SqlCredentialStore

APPS_API = Path(__file__).resolve().parents[1]
ALEMBIC_INI = APPS_API / "alembic.ini"
PASSWORD = "correct horse battery"
KEY_A = "sk-alice-0123456789ab"
KEY_B = "sk-bob-9876543210zy"
MASTER_KEY = "test-master-key-for-byok"


def _upgrade(url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


# --------------------------------------------------------------------------
# Pure application service: fake store/cipher, no database
# --------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, StoredCredential] = {}

    def get(self, user_id: str) -> StoredCredential | None:
        return self.rows.get(user_id)

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
        existing = self.rows.get(user_id)
        row = StoredCredential(
            user_id=user_id,
            provider=provider,
            base_url=base_url,
            model=model,
            encrypted_key=encrypted_key,
            key_last4=key_last4,
            created_at=existing.created_at if existing is not None else updated_at,
            updated_at=updated_at,
            last_verified_at=None,
        )
        self.rows[user_id] = row
        return row

    def delete(self, user_id: str) -> None:
        self.rows.pop(user_id, None)

    def mark_verified(self, user_id: str, *, verified_at: datetime) -> None:
        row = self.rows.get(user_id)
        if row is None:
            return
        self.rows[user_id] = StoredCredential(
            user_id=row.user_id,
            provider=row.provider,
            base_url=row.base_url,
            model=row.model,
            encrypted_key=row.encrypted_key,
            key_last4=row.key_last4,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_verified_at=verified_at,
        )


class _RecordingTester:
    def __init__(self, *, ok: bool = True, message: str = "连接成功。") -> None:
        self.ok = ok
        self.message = message
        self.seen: list[SecretCredential] = []

    def probe(self, credential: SecretCredential) -> CredentialTestResult:
        self.seen.append(credential)
        return CredentialTestResult(
            ok=self.ok,
            latency_ms=7,
            model=credential.model,
            message=self.message,
        )


def _service(
    *,
    with_cipher: bool = True,
    tester: _RecordingTester | None = None,
    guard: RemoteUrlGuard | None = None,
) -> tuple[CredentialService, _MemoryStore, _RecordingTester]:
    store = _MemoryStore()
    resolved_tester = tester or _RecordingTester()
    cipher: SecretCipher | None = FernetCipher.from_secret(MASTER_KEY) if with_cipher else None
    service = CredentialService(
        store=store,
        cipher=cipher,
        guard=guard if guard is not None else SsrfGuard(),
        tester=resolved_tester,
    )
    return service, store, resolved_tester


def test_presets_cover_the_four_documented_providers() -> None:
    assert set(PROVIDER_PRESETS) == {"deepseek", "openai", "openrouter", "custom"}
    assert PROVIDER_PRESETS["deepseek"].base_url == "https://api.deepseek.com/v1"
    assert PROVIDER_PRESETS["deepseek"].model == "deepseek-chat"
    assert PROVIDER_PRESETS["openai"].model == "gpt-4o-mini"
    assert PROVIDER_PRESETS["openrouter"].model == "openai/gpt-4o-mini"
    assert PROVIDER_PRESETS["custom"].base_url is None
    assert PROVIDER_PRESETS["custom"].model is None
    assert {
        "api.deepseek.com",
        "api.openai.com",
        "openrouter.ai",
    } == KNOWN_PROVIDER_HOSTS


def test_normalize_helpers_fill_presets_and_reject_bad_values() -> None:
    assert normalize_provider("  DeepSeek ") == "deepseek"
    with pytest.raises(CredentialValidationError):
        normalize_provider("some-other-provider")

    assert (
        normalize_base_url("https://API.DeepSeek.com/v1/", provider="deepseek")
        == "https://api.deepseek.com/v1"
    )
    # Empty means "use the preset"; custom has none, so it must be supplied.
    assert normalize_base_url("", provider="deepseek") == "https://api.deepseek.com/v1"
    with pytest.raises(CredentialValidationError):
        normalize_base_url("", provider="custom")
    with pytest.raises(CredentialValidationError):
        normalize_base_url("http://api.deepseek.com/v1", provider="deepseek")
    with pytest.raises(CredentialValidationError):
        normalize_base_url("https://user:pass@api.deepseek.com/v1", provider="deepseek")
    with pytest.raises(CredentialValidationError):
        normalize_base_url("https://api.deepseek.com/v1?x=1", provider="deepseek")

    assert validate_model(" deepseek-chat ", provider="deepseek") == "deepseek-chat"
    assert validate_model("", provider="deepseek") == "deepseek-chat"
    with pytest.raises(CredentialValidationError):
        validate_model("bad model!", provider="deepseek")

    assert validate_api_key("  sk-abcdefgh  ") == "sk-abcdefgh"
    with pytest.raises(CredentialValidationError):
        validate_api_key("short")
    with pytest.raises(CredentialValidationError):
        validate_api_key("sk-with space-123456")


def test_save_masks_the_key_and_resolve_returns_it() -> None:
    service, store, _ = _service()

    public = service.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )

    assert public.configured is True
    assert public.provider == "deepseek"
    assert public.base_url == "https://api.deepseek.com/v1"
    assert public.model == "deepseek-chat"
    assert public.key_last4 == KEY_A[-4:]
    assert public.encryption_ready is True
    assert public.warning is None

    stored = store.rows["U_A"]
    assert stored.encrypted_key != KEY_A
    assert KEY_A not in stored.encrypted_key
    assert stored.key_last4 == KEY_A[-4:]

    resolved = service.resolve("U_A")
    assert resolved is not None
    assert resolved.api_key == KEY_A
    assert service.resolve("U_B") is None


def test_no_master_key_disables_writes_and_reports_the_reason() -> None:
    service, _, tester = _service(with_cipher=False)

    public = service.get_public("U_A")
    assert public.configured is False
    assert public.encryption_ready is False
    assert public.warning is not None and "SYNAPSE_CREDENTIAL_KEY" in public.warning

    with pytest.raises(CredentialStoreDisabled):
        service.save(
            "U_A",
            CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
        )
    with pytest.raises(CredentialStoreDisabled):
        service.test("U_A", CredentialTestInput())
    assert tester.seen == []
    # Deleting is allowed and idempotent even without a master key.
    service.delete("U_A")


def test_wrong_master_key_cannot_decrypt_a_saved_row() -> None:
    store = _MemoryStore()
    writer = CredentialService(
        store=store,
        cipher=FernetCipher.from_secret("first-secret"),
        guard=SsrfGuard(),
        tester=_RecordingTester(),
    )
    writer.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )

    reader = CredentialService(
        store=store,
        cipher=FernetCipher.from_secret("second-secret"),
        guard=SsrfGuard(),
        tester=_RecordingTester(),
    )
    with pytest.raises(CredentialDecryptionError):
        reader.resolve("U_A")
    # The masked view still loads, with the actionable warning.
    public = reader.get_public("U_A")
    assert public.configured is False
    assert public.key_last4 == KEY_A[-4:]
    assert public.warning is not None and "不一致" in public.warning


def test_test_endpoint_semantics_at_the_service_level() -> None:
    tester = _RecordingTester()
    service, _, _ = _service(tester=tester)

    with pytest.raises(CredentialMissing):
        service.test("U_A", CredentialTestInput())

    service.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    result = service.test("U_A", CredentialTestInput())
    assert result.ok is True
    assert tester.seen[-1].api_key == KEY_A
    assert service.get_public("U_A").last_verified_at is not None

    # A candidate key is used for the probe but is not saved.
    candidate = "sk-candidate-0000000000"
    service.test("U_A", CredentialTestInput(api_key=candidate))
    assert tester.seen[-1].api_key == candidate
    assert service.resolve("U_A").api_key == KEY_A  # type: ignore[union-attr]

    # Switching provider without a new key is refused, not silently reused.
    with pytest.raises(CredentialMissing):
        service.test("U_A", CredentialTestInput(provider="openai"))


# --------------------------------------------------------------------------
# The real app: contract, statuses, isolation, rotation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByokHarness:
    app: FastAPI
    container: Container
    database: Path

    @property
    def credentials(self) -> CredentialService:
        assert self.container.credentials is not None
        return self.container.credentials


@pytest.fixture()
def make_byok_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., ByokHarness]]:
    containers: list[Container] = []
    counter = count()

    def make(
        *,
        master_key: str | None = MASTER_KEY,
        auth: bool = True,
        tester: ModelTester | None = None,
        guard: RemoteUrlGuard | None = None,
        database: Path | None = None,
    ) -> ByokHarness:
        target = database or tmp_path / f"byok-{next(counter)}.sqlite3"
        url = f"sqlite+pysqlite:///{target.as_posix()}"
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
        monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "3600")
        monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on")
        monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "off")
        monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
        if auth:
            monkeypatch.setenv("SYNAPSE_AUTH", "on")
            _upgrade(url)
        else:
            monkeypatch.delenv("SYNAPSE_AUTH", raising=False)
        if master_key is None:
            monkeypatch.delenv("SYNAPSE_CREDENTIAL_KEY", raising=False)
        else:
            monkeypatch.setenv("SYNAPSE_CREDENTIAL_KEY", master_key)
        container = build_container(
            credential_guard=guard,
            credential_tester=tester,
        )
        containers.append(container)
        return ByokHarness(app=create_app(container), container=container, database=target)

    try:
        yield make
    finally:
        for container in containers:
            if container.auth_dispose is not None:
                container.auth_dispose()


def _user(app: FastAPI, email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return client


def _put(client: TestClient, **body: object) -> httpx.Response:
    return client.put("/api/v1/settings/model", json=body)


def test_settings_contract_before_any_key(make_byok_app: Callable[..., ByokHarness]) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")

    response = alice.get("/api/v1/settings/model")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "configured": False,
        "provider": None,
        "base_url": None,
        "model": None,
        "key_last4": None,
        "last_verified_at": None,
        "encryption_ready": True,
        "warning": None,
    }


def test_put_stores_encrypted_and_never_returns_the_key(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")

    saved = _put(alice, provider="deepseek", base_url="", model="", api_key=KEY_A)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["configured"] is True
    assert body["key_last4"] == KEY_A[-4:]
    assert body["provider"] == "deepseek"
    assert body["base_url"] == "https://api.deepseek.com/v1"
    assert body["model"] == "deepseek-chat"
    assert KEY_A not in saved.text

    fetched = alice.get("/api/v1/settings/model")
    assert fetched.status_code == 200
    assert KEY_A not in fetched.text
    assert fetched.json()["key_last4"] == KEY_A[-4:]

    # At rest: ciphertext, plus the plaintext only in the service's resolved view.
    engine = create_auth_engine(f"sqlite+pysqlite:///{harness.database.as_posix()}")
    try:
        with build_session_factory(engine)() as session:
            row = session.scalars(select(UserModelCredentialRow)).one()
            assert row.encrypted_key != KEY_A
            assert KEY_A not in row.encrypted_key
            assert row.key_last4 == KEY_A[-4:]
    finally:
        engine.dispose()
    resolved = harness.credentials.resolve(cast(str, cast(dict[str, object], _me(alice))["id"]))
    assert resolved is not None and resolved.api_key == KEY_A


def _me(client: TestClient) -> dict[str, object]:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def test_put_rejects_unsafe_urls_and_bad_input(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")

    for base_url in (
        "http://api.deepseek.com/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://10.0.0.8/v1",
        "https://172.16.5.4/v1",
        "https://192.168.1.2/v1",
        "https://169.254.169.254/latest",
        "https://[::1]/v1",
    ):
        response = _put(
            alice,
            provider="custom",
            base_url=base_url,
            model="m",
            api_key=KEY_A,
        )
        assert response.status_code == 422, (base_url, response.text)
        assert KEY_A not in response.text

    assert _put(alice, provider="nope", api_key=KEY_A).status_code == 422
    assert _put(alice, provider="deepseek", model="bad model!", api_key=KEY_A).status_code == 422
    assert _put(alice, provider="deepseek", api_key="short").status_code == 422
    assert _put(alice, provider="custom", model="m", api_key=KEY_A).status_code == 422

    # Nothing was written by the rejected attempts.
    assert alice.get("/api/v1/settings/model").json()["configured"] is False


def test_two_users_cannot_see_or_overwrite_each_others_key(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")
    bob = _user(harness.app, "bob@example.com")

    assert _put(alice, provider="deepseek", api_key=KEY_A).status_code == 200
    alice_id = cast(str, _me(alice)["id"])
    bob_id = cast(str, _me(bob)["id"])

    bob_view = bob.get("/api/v1/settings/model").json()
    assert bob_view["configured"] is False
    assert bob_view["key_last4"] is None

    assert _put(bob, provider="openai", api_key=KEY_B).status_code == 200
    assert bob.get("/api/v1/settings/model").json()["key_last4"] == KEY_B[-4:]
    assert alice.get("/api/v1/settings/model").json()["key_last4"] == KEY_A[-4:]

    assert harness.credentials.resolve(alice_id).api_key == KEY_A  # type: ignore[union-attr]
    assert harness.credentials.resolve(bob_id).api_key == KEY_B  # type: ignore[union-attr]


def test_delete_removes_the_row_and_is_idempotent(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")
    alice_id = cast(str, _me(alice)["id"])

    assert _put(alice, provider="deepseek", api_key=KEY_A).status_code == 200
    first = alice.delete("/api/v1/settings/model")
    assert first.status_code == 204
    assert first.content == b""
    assert alice.get("/api/v1/settings/model").json()["configured"] is False
    assert harness.credentials.resolve(alice_id) is None
    assert alice.delete("/api/v1/settings/model").status_code == 204


def test_login_ticket_is_exchanged_on_the_settings_routes(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")
    before = alice.cookies.get("synapse_session")

    response = _put(alice, provider="deepseek", api_key=KEY_A)
    assert response.status_code == 200
    after = alice.cookies.get("synapse_session")
    assert before and after and after != before
    assert "set-cookie" in response.headers

    # The exchanged ordinary session is reused, not rotated again.
    reused = alice.get("/api/v1/settings/model")
    assert reused.status_code == 200
    assert "set-cookie" not in reused.headers
    assert alice.cookies.get("synapse_session") == after


def test_missing_master_key_is_503_and_never_writes(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app(master_key=None)
    alice = _user(harness.app, "alice@example.com")

    view = alice.get("/api/v1/settings/model")
    assert view.status_code == 200
    assert view.json()["encryption_ready"] is False
    assert view.json()["configured"] is False
    assert "SYNAPSE_CREDENTIAL_KEY" in cast(str, view.json()["warning"])

    saved = _put(alice, provider="deepseek", api_key=KEY_A)
    assert saved.status_code == 503
    assert "SYNAPSE_CREDENTIAL_KEY" in saved.json()["detail"]
    assert KEY_A not in saved.text

    tested = alice.post("/api/v1/settings/model/test", json={})
    assert tested.status_code == 503

    # Deletion still works, so an operator who lost the key can clean up.
    assert alice.delete("/api/v1/settings/model").status_code == 204


def test_settings_are_forbidden_when_auth_is_off(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app(auth=False)
    anonymous = TestClient(harness.app)

    response = anonymous.get("/api/v1/settings/model")
    assert response.status_code == 403
    assert "SYNAPSE_AUTH" in response.json()["detail"]
    assert anonymous.post("/api/v1/settings/model/test", json={}).status_code == 403


def test_settings_require_a_login(make_byok_app: Callable[..., ByokHarness]) -> None:
    harness = make_byok_app()
    anonymous = TestClient(harness.app)
    response = anonymous.get("/api/v1/settings/model")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Cookie"


def test_test_endpoint_marks_a_saved_key_verified(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    tester = _RecordingTester(message="连接成功，模型 deepseek-chat 已响应。")
    harness = make_byok_app(tester=tester)
    alice = _user(harness.app, "alice@example.com")
    assert _put(alice, provider="deepseek", api_key=KEY_A).status_code == 200

    response = alice.post("/api/v1/settings/model/test", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"ok", "latency_ms", "model", "message"}
    assert body["ok"] is True
    assert body["latency_ms"] == 7
    assert body["model"] == "deepseek-chat"
    assert KEY_A not in response.text
    assert tester.seen[-1].api_key == KEY_A

    assert alice.get("/api/v1/settings/model").json()["last_verified_at"] is not None


def test_test_endpoint_reports_a_provider_failure_as_200(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    tester = _RecordingTester(ok=False, message="服务商拒绝了这组凭据（HTTP 401/403）。")
    harness = make_byok_app(tester=tester)
    alice = _user(harness.app, "alice@example.com")

    response = alice.post(
        "/api/v1/settings/model/test",
        json={"provider": "deepseek", "api_key": KEY_A},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False
    assert response.json()["message"].startswith("服务商拒绝")
    assert KEY_A not in response.text
    # A failed probe never marks the saved row as verified.
    assert alice.get("/api/v1/settings/model").json()["last_verified_at"] is None


def test_test_endpoint_without_any_key_is_422(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")
    response = alice.post("/api/v1/settings/model/test", json={})
    assert response.status_code == 422
    assert "api_key" in response.json()["detail"]


def test_saved_key_survives_a_restart(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    first = make_byok_app()
    alice = _user(first.app, "alice@example.com")
    assert _put(alice, provider="deepseek", api_key=KEY_A).status_code == 200
    alice_id = cast(str, _me(alice)["id"])

    # A second app over the same database: the row is still decryptable with the
    # same master key, so a restart does not silently discard the user's key.
    second = make_byok_app(database=first.database)
    assert second.container.credentials is not None
    resolved = second.container.credentials.resolve(alice_id)
    assert resolved is not None
    assert resolved.api_key == KEY_A
    assert resolved.provider == "deepseek"


def test_stored_row_is_only_ciphertext(
    make_byok_app: Callable[..., ByokHarness],
) -> None:
    harness = make_byok_app()
    alice = _user(harness.app, "alice@example.com")
    assert _put(alice, provider="deepseek", api_key=KEY_A).status_code == 200

    engine = create_auth_engine(f"sqlite+pysqlite:///{harness.database.as_posix()}")
    try:
        store = SqlCredentialStore(build_session_factory(engine))
        row = store.get(cast(str, _me(alice)["id"]))
    finally:
        engine.dispose()
    assert row is not None
    assert row.key_last4 == KEY_A[-4:]
    assert KEY_A not in row.encrypted_key


# --------------------------------------------------------------------------
# The real HTTP probe: sanitized messages, no key echoed
# --------------------------------------------------------------------------


def test_probe_reports_success_without_echoing_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"content": "pong"}}],
            },
        )

    tester = HttpxModelTester(transport_factory=lambda: httpx.MockTransport(handler))
    result = tester.probe(
        SecretCredential(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key=KEY_A,
        )
    )

    assert result.ok is True
    assert result.model == "deepseek-chat"
    assert result.latency_ms >= 0
    assert KEY_A not in result.message
    assert seen[0].headers["authorization"] == f"Bearer {KEY_A}"
    body = seen[0].read().decode("utf-8")
    assert '"max_tokens":1' in body.replace(" ", "")


def test_probe_401_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A hostile/verbose provider echoing the key must not reach the browser.
        return httpx.Response(
            401,
            json={"error": {"message": f"invalid api key {KEY_A}"}},
        )

    tester = HttpxModelTester(transport_factory=lambda: httpx.MockTransport(handler))
    result = tester.probe(
        SecretCredential(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key=KEY_A,
        )
    )

    assert result.ok is False
    assert KEY_A not in result.message
    assert "401" in result.message


def test_probe_transport_error_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {KEY_A}", request=request)

    tester = HttpxModelTester(transport_factory=lambda: httpx.MockTransport(handler))
    result = tester.probe(
        SecretCredential(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key=KEY_A,
        )
    )

    assert result.ok is False
    assert KEY_A not in result.message


def test_guard_allows_the_known_hosts_and_blocks_private_literals() -> None:
    guard = SsrfGuard()
    for url in (
        "https://api.deepseek.com/v1",
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
    ):
        guard.check(url)

    for url in (
        "http://api.deepseek.com/v1",
        "https://localhost:8080/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://10.1.2.3/v1",
        "https://192.168.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/v1",
        "https://printer.local/v1",
    ):
        with pytest.raises(CredentialValidationError):
            guard.check(url)


def test_guard_rejects_a_hostname_that_resolves_private() -> None:
    def resolver(host: str, port: int, **kwargs: object) -> list[object]:
        del host, port, kwargs
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.7", 443)),
        ]

    guard = SsrfGuard(allowed_hosts=frozenset(), resolver=resolver)
    with pytest.raises(CredentialValidationError):
        guard.check("https://public-looking.example/v1")


def test_guard_rejects_an_unresolvable_hostname() -> None:
    def resolver(host: str, port: int, **kwargs: object) -> list[object]:
        del host, port, kwargs
        raise OSError("no dns here")

    guard = SsrfGuard(allowed_hosts=frozenset(), resolver=resolver)
    with pytest.raises(CredentialValidationError):
        guard.check("https://nowhere.example/v1")
