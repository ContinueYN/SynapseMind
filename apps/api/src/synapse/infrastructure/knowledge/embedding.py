"""Embedding adapters.

``FastEmbedEmbedder`` is the optional production path; ``HashingEmbedder`` is a
deterministic, offline fallback used by tests. Neither one sees student prose:
the API only sends a concept label to retrieval.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from typing import Protocol

from synapse.application.knowledge import KnowledgeUnavailable

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
_ASCII_WORD = re.compile(r"[a-zA-Z0-9_]+")
_HAN = re.compile(r"[\u4e00-\u9fff]")


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...

    def embed_query(self, text: str) -> tuple[float, ...]: ...


def normalize(vector: Iterable[float]) -> tuple[float, ...]:
    values = tuple(float(item) for item in vector)
    norm = sum(item * item for item in values) ** 0.5
    if norm == 0.0:
        return values
    return tuple(item / norm for item in values)


def _tokens(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    words = _ASCII_WORD.findall(lowered)
    han = _HAN.findall(lowered)
    bigrams = [han[index] + han[index + 1] for index in range(len(han) - 1)]
    return tuple(words + han + bigrams)


class HashingEmbedder:
    """Bag-of-tokens hashing; deterministic and dependency-free.

    It is not a semantic model. It exists so retrieval, ranking and API plumbing
    can be tested without downloading a model. Production uses FastEmbed.
    """

    def __init__(self, dimension: int = 256) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.model_name = f"hashing-{dimension}"
        self.dimension = dimension

    def _vector(self, text: str) -> tuple[float, ...]:
        counts: dict[int, float] = {}
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest, "big") % self.dimension
            counts[slot] = counts.get(slot, 0.0) + 1.0
        vector = [0.0] * self.dimension
        for slot, count in counts.items():
            vector[slot] = count
        return normalize(vector)

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._vector(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)


class FastEmbedEmbedder:
    """ONNX-based Chinese embeddings; imports the optional dependency lazily."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        cache_dir: str | None = None,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised by a missing extra
            raise KnowledgeUnavailable(
                "RAG 已开启，但没有安装 fastembed；先运行 "
                '`python -m pip install "fastembed>=0.9,<1"`。'
            ) from exc
        try:
            self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
            self.dimension = int(TextEmbedding.get_embedding_size(model_name))
        except Exception as exc:
            raise KnowledgeUnavailable(
                f"无法加载嵌入模型 {model_name!r}：{exc}。"
                "首次运行需要下载模型；若访问 huggingface.co 失败，可设置 "
                "HF_ENDPOINT=https://hf-mirror.com 后重试。"
            ) from exc
        self.model_name = model_name

    def embed_passages(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        try:
            return tuple(normalize(vector) for vector in self._model.passage_embed(list(texts)))
        except Exception as exc:
            raise KnowledgeUnavailable(f"嵌入计算失败：{exc}") from exc

    def embed_query(self, text: str) -> tuple[float, ...]:
        try:
            vector = next(iter(self._model.query_embed([text])))
        except Exception as exc:
            raise KnowledgeUnavailable(f"查询嵌入失败：{exc}") from exc
        return normalize(vector)
