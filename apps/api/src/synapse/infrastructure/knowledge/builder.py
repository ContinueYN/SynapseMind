"""Composition for the optional knowledge retriever."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from synapse.application.knowledge import KnowledgeService
from synapse.infrastructure.knowledge.corpus import load_corpus
from synapse.infrastructure.knowledge.embedding import DEFAULT_MODEL, FastEmbedEmbedder
from synapse.infrastructure.knowledge.index import InMemoryKnowledgeIndex

DEFAULT_MIN_SCORE = 0.35
# FastEmbed's own default is a temporary directory. Keep the ~90 MB model
# across runs and OS temp cleanups; override with SYNAPSE_EMBED_CACHE.
DEFAULT_CACHE_DIR = str(Path.home() / ".cache" / "synapsemind" / "fastembed")


@dataclass(frozen=True, slots=True)
class KnowledgeSettings:
    model_name: str = DEFAULT_MODEL
    cache_dir: str = DEFAULT_CACHE_DIR
    corpus_path: Path | None = None
    min_score: float = DEFAULT_MIN_SCORE

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> KnowledgeSettings:
        source = os.environ if env is None else env
        raw_score = source.get("SYNAPSE_RAG_MIN_SCORE", str(DEFAULT_MIN_SCORE)).strip()
        try:
            score = float(raw_score)
        except ValueError as exc:
            raise ValueError(f"SYNAPSE_RAG_MIN_SCORE={raw_score!r}: expected a number") from exc
        if not 0.0 <= score <= 1.0:
            raise ValueError("SYNAPSE_RAG_MIN_SCORE must be between 0 and 1")
        raw_path = source.get("SYNAPSE_KNOWLEDGE_PATH", "").strip()
        return cls(
            model_name=source.get("SYNAPSE_EMBED_MODEL", "").strip() or DEFAULT_MODEL,
            cache_dir=source.get("SYNAPSE_EMBED_CACHE", "").strip() or DEFAULT_CACHE_DIR,
            corpus_path=Path(raw_path) if raw_path else None,
            min_score=score,
        )


def build_knowledge_service(
    *,
    enabled: bool,
    settings: KnowledgeSettings | None = None,
) -> KnowledgeService:
    """Return a disabled service unless ``SYNAPSE_RAG`` is explicitly on.

    Turning the switch on is intentionally loud: the model must load before the
    API starts, so a missing dependency or failed download is an operator error,
    not a silently empty search box.
    """

    if not enabled:
        return KnowledgeService(None)
    config = settings or KnowledgeSettings.from_env()
    cards = load_corpus(config.corpus_path)
    embedder = FastEmbedEmbedder(config.model_name, cache_dir=config.cache_dir)
    index = InMemoryKnowledgeIndex(cards, embedder, min_score=config.min_score)
    return KnowledgeService(index)
