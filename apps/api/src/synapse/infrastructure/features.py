"""Non-LLM feature switches.

Every switch defaults **off**, so a checkout without the variable behaves exactly
like the baseline that was measured. A typo is loud (``ValueError``): silently
treating ``SYNAPSE_EQUALITY_CHECK=onn`` as off would look like a healthy default
and hide the reason a reported finding never appeared.

The equality-chain switch is deliberately separate from ``LLMSettings``: it does
not need a model, and its default matters to the rule baseline used by golden.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    # Check the student's own equality chains and merge provable findings into
    # the diagnosis card. Off by default: it changes annotated baseline cards.
    equality_check: bool = False
    # Read-only knowledge retrieval. Off by default because turning it on loads
    # an optional ONNX embedding model; the rule diagnosis path never needs it.
    rag: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FeatureFlags:
        source = os.environ if env is None else env
        return cls(
            equality_check=_parse_flag(
                "SYNAPSE_EQUALITY_CHECK",
                source.get("SYNAPSE_EQUALITY_CHECK", "off"),
            ),
            rag=_parse_flag("SYNAPSE_RAG", source.get("SYNAPSE_RAG", "off")),
        )


def _parse_flag(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name}={raw!r}: expected on | off")
