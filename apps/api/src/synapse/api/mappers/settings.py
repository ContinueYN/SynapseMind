"""Per-user model credential (BYOK) mappers."""

from __future__ import annotations

from synapse.api.mappers.common import clip_text
from synapse.api.schemas.settings import ModelCredentialOut, ModelTestOut
from synapse.application.credentials.service import CredentialTestResult, PublicCredential


def model_credential_out(public: PublicCredential) -> ModelCredentialOut:
    """The masked view: last four characters only, never the stored key."""

    return ModelCredentialOut(
        configured=public.configured,
        provider=public.provider,
        base_url=public.base_url,
        model=public.model,
        key_last4=public.key_last4,
        last_verified_at=public.last_verified_at,
        encryption_ready=public.encryption_ready,
        warning=public.warning,
    )


def model_test_out(result: CredentialTestResult) -> ModelTestOut:
    """Map a probe result; the message is already key-free by construction."""

    return ModelTestOut(
        ok=result.ok,
        latency_ms=result.latency_ms,
        model=clip_text(result.model, 120),
        message=clip_text(result.message, 300),
    )
