"""LLM settings and the four-level rollout switch (chapter 12 §12.7).

``off`` is the default so CI never needs a key and the rule baseline stays the
measured path. A typo in the mode is loud: silently disabling the model would
be indistinguishable from a healthy ``off``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

LLMMode = Literal["off", "shadow", "on"]

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT_S = 4.0


@dataclass(frozen=True, slots=True)
class LLMSettings:
    mode: LLMMode = "off"
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    shadow_timeout_s: float = 2.0
    max_attempts: int = 2  # one retry on schema failure, never on timeout
    prompt_version: str = "probe-v1"
    canary_percent: int = 0
    audit_path: str = "var/audit/llm.jsonl"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMSettings:
        source = os.environ if env is None else env
        mode, canary = _parse_mode(source.get("SYNAPSE_LLM_MODE", "off"))
        provider = source.get("SYNAPSE_LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
        default_key = "DEEPSEEK_API_KEY" if provider == DEFAULT_PROVIDER else ""
        api_key = source.get("SYNAPSE_LLM_API_KEY") or source.get(default_key) or None
        return cls(
            mode=mode,
            provider=provider,
            model=source.get("SYNAPSE_LLM_MODEL", DEFAULT_MODEL).strip(),
            base_url=source.get("SYNAPSE_LLM_BASE_URL", DEFAULT_BASE_URL).strip(),
            api_key=api_key,
            timeout_s=float(source.get("SYNAPSE_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
            shadow_timeout_s=float(source.get("SYNAPSE_LLM_SHADOW_TIMEOUT_S", 2.0)),
            max_attempts=int(source.get("SYNAPSE_LLM_MAX_ATTEMPTS", 2)),
            prompt_version=source.get("SYNAPSE_LLM_PROMPT_VERSION", "probe-v1").strip(),
            canary_percent=canary,
            audit_path=source.get("SYNAPSE_LLM_AUDIT_PATH", "var/audit/llm.jsonl").strip(),
        )

    @property
    def llm_enabled(self) -> bool:
        """A model is only used when the mode asks for it *and* a key exists."""
        return self.mode != "off" and bool(self.api_key)

    def use_for(self, session_id: str) -> bool:
        """Canary routing: ``hash(session_id) % 100 < canary_percent``.

        Uses SHA-256 rather than ``hash()`` so the split is stable across
        processes and deployments.
        """
        if not self.llm_enabled:
            return False
        if self.mode != "on":
            return False
        if self.canary_percent <= 0:
            return True
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 100 < self.canary_percent


def _parse_mode(raw: str) -> tuple[LLMMode, int]:
    value = raw.strip().lower()
    if value == "off":
        return "off", 0
    if value == "shadow":
        return "shadow", 0
    if value == "on":
        return "on", 0
    if value.startswith("on:") and value[3:].isdigit():
        percent = int(value[3:])
        if 0 <= percent <= 100:
            return "on", percent
    raise ValueError(f"SYNAPSE_LLM_MODE={raw!r}: expected off | shadow | on | on:<0-100>")
