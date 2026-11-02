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
from pathlib import Path
from typing import Literal

LLMMode = Literal["off", "shadow", "on"]

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT_S = 4.0


def load_dotenv(path: Path | None = None) -> None:
    """Read ``KEY=VALUE`` lines into ``os.environ``; existing keys win.

    Deliberately explicit: importing the package never reads a file, and the
    tests never call this, so a developer's local ``.env`` cannot change test
    behaviour. Entry points (``scripts/dev/run.py`` via uvicorn, the eval
    script) opt in.
    """
    target = path if path is not None else _default_env_file()
    if target is None:
        return
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _default_env_file() -> Path | None:
    """``<repo root>/.env`` when running from a checkout."""
    here = Path(__file__).resolve()
    if len(here.parents) < 7:
        return None
    return here.parents[6] / ".env"


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
    # Graph building is a longer generation than a probe rewrite: its prompt and
    # its per-call budget are versioned and configured separately.
    graph_prompt_version: str = "graph-v9"
    graph_timeout_s: float = 60.0
    # Phase 1b: the generic structure graph has its own prompt and budget. It
    # is a different contract from the solution graph, so revising one must not
    # silently relabel the other in the audit trail.
    generic_graph_prompt_version: str = "generic-graph-v1"
    generic_graph_timeout_s: float = 60.0
    # Phase 4 (second slice): an optional planner may pick the middle tool of
    # the read-only agent trace. It is a separate switch because it changes what
    # the trace shows, and it is only built when the model path is live and RAG
    # is available. Default off keeps the rule trace byte-stable.
    agent_planner: bool = False
    agent_planner_prompt_version: str = "agent-plan-v1"
    agent_planner_timeout_s: float = 2.0
    # Bring-your-own-key: when on, a logged-in user's saved model credential is
    # used for that user's requests instead of the server-wide key. It never
    # enables the model on its own — ``mode`` still has to ask for it — and a
    # public/unauthenticated request still uses only the server key.
    byok: bool = False
    # The whole build is one request inside the 8s first-question budget
    # (chapter 12 §12.8). A counterexample retry is optional — the graph is
    # usable without its claim — so it only runs when it still fits here.
    graph_retry_budget_s: float = 7.5
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
            graph_prompt_version=source.get("SYNAPSE_GRAPH_PROMPT_VERSION", "graph-v9").strip(),
            graph_timeout_s=float(source.get("SYNAPSE_GRAPH_TIMEOUT_S", 60.0)),
            graph_retry_budget_s=float(source.get("SYNAPSE_GRAPH_RETRY_BUDGET_S", 7.5)),
            generic_graph_prompt_version=source.get(
                "SYNAPSE_GENERIC_GRAPH_PROMPT_VERSION", "generic-graph-v1"
            ).strip(),
            generic_graph_timeout_s=float(source.get("SYNAPSE_GENERIC_GRAPH_TIMEOUT_S", 60.0)),
            agent_planner=_parse_switch(
                "SYNAPSE_AGENT_PLANNER",
                source.get("SYNAPSE_AGENT_PLANNER", "off"),
            ),
            agent_planner_prompt_version=source.get(
                "SYNAPSE_AGENT_PLANNER_PROMPT_VERSION", "agent-plan-v1"
            ).strip(),
            agent_planner_timeout_s=_parse_planner_timeout(
                source.get("SYNAPSE_AGENT_PLANNER_TIMEOUT_S", "2.0")
            ),
            byok=_parse_switch("SYNAPSE_BYOK", source.get("SYNAPSE_BYOK", "off")),
            canary_percent=canary,
            audit_path=source.get("SYNAPSE_LLM_AUDIT_PATH", "var/audit/llm.jsonl").strip(),
        )

    @property
    def llm_enabled(self) -> bool:
        """A model path is live when the mode asks for it and *some* key exists.

        Without BYOK that means the server-wide key; with BYOK on, a user may
        supply their own key, so the process does not need one to build the
        adapters. A request from a user without a credential still falls back to
        the server key, and fails closed when neither exists.
        """

        return self.mode != "off" and (bool(self.api_key) or self.byok)

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


def _parse_switch(name: str, raw: str) -> bool:
    """Local ``on/off`` parser; the LLM layer owns its own switches."""

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name}={raw!r}: expected on | off")


def _parse_planner_timeout(raw: str) -> float:
    """Keep the planner a short side call, not a second graph build."""

    value = float(raw)
    if not 0.2 <= value <= 8.0:
        raise ValueError(f"SYNAPSE_AGENT_PLANNER_TIMEOUT_S={raw!r}: expected 0.2-8.0")
    return value
