"""Load and validate the checked-in knowledge corpus."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import cast

from synapse.domain.knowledge.models import (
    KnowledgeCard,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeVerification,
)

DEFAULT_CORPUS = "corpus.jsonl"
_MAX_TITLE = 60
_MAX_BODY = 600
_MAX_TAG = 24
_MAX_TAGS = 8
_MAX_SUBJECT = 40
_CARD_ID = re.compile(r"^K_[A-Z0-9_]+$")
_KINDS: frozenset[str] = frozenset({"concept", "pattern", "method", "error", "source"})
_VERIFICATIONS: frozenset[str] = frozenset({"formal", "executable", "empirical", "argumentative"})
# Older rows predate the metadata. Default them conservatively: a math card is
# a formal explanation, a physics card is empirical, and anything else is an
# argumentative framework. New cards can and should state both fields.
_DEFAULT_VERIFICATIONS: dict[str, tuple[KnowledgeVerification, ...]] = {
    "math": ("formal",),
    "physics": ("empirical",),
    "chinese": ("argumentative",),
}
_FALLBACK_VERIFICATIONS: tuple[KnowledgeVerification, ...] = ("argumentative",)


def _text(value: object, where: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where}: expected a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{where}: must not be empty")
    if len(cleaned) > limit:
        raise ValueError(f"{where}: longer than {limit} characters")
    return cleaned


def _source(value: object, where: str) -> KnowledgeSource:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected an object")
    extra = set(value) - {"title", "url", "license"}
    if extra:
        raise ValueError(f"{where}: unexpected fields {sorted(extra)}")
    url = _text(value.get("url"), f"{where}.url", limit=500)
    if not url.startswith("https://"):
        raise ValueError(f"{where}.url: must be an https URL")
    return KnowledgeSource(
        title=_text(value.get("title"), f"{where}.title", limit=120),
        url=url,
        license=_text(value.get("license"), f"{where}.license", limit=80),
    )


def _card(raw: object, where: str) -> KnowledgeCard:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected an object")
    extra = set(raw) - {
        "id",
        "kind",
        "subject",
        "verifications",
        "title",
        "body",
        "tags",
        "source",
    }
    if extra:
        raise ValueError(f"{where}: unexpected fields {sorted(extra)}")
    # The domain is an open label, not a whitelist: a card may be about a
    # programming pattern or a decision framework just as well as a math topic.
    subject = _text(raw.get("subject"), f"{where}.subject", limit=_MAX_SUBJECT)
    kind_raw = raw.get("kind", "concept")
    if not isinstance(kind_raw, str) or kind_raw not in _KINDS:
        raise ValueError(f"{where}.kind: expected one of {sorted(_KINDS)}, got {kind_raw!r}")
    kind = cast(KnowledgeKind, kind_raw)
    verifications_raw = raw.get("verifications")
    if verifications_raw is None:
        verifications = _DEFAULT_VERIFICATIONS.get(subject, _FALLBACK_VERIFICATIONS)
    else:
        if not isinstance(verifications_raw, list) or not verifications_raw:
            raise ValueError(f"{where}.verifications: expected a non-empty array")
        if len(verifications_raw) > 4:
            raise ValueError(f"{where}.verifications: at most 4 entries")
        for index, item in enumerate(verifications_raw):
            if not isinstance(item, str) or item not in _VERIFICATIONS:
                raise ValueError(
                    f"{where}.verifications[{index}]: expected one of "
                    f"{sorted(_VERIFICATIONS)}, got {item!r}"
                )
        if len(set(verifications_raw)) != len(verifications_raw):
            raise ValueError(f"{where}.verifications: duplicate entries")
        verifications = cast(tuple[KnowledgeVerification, ...], tuple(verifications_raw))
    tags_raw = raw.get("tags")
    if not isinstance(tags_raw, list) or not tags_raw:
        raise ValueError(f"{where}.tags: expected a non-empty array")
    if len(tags_raw) > _MAX_TAGS:
        raise ValueError(f"{where}.tags: at most {_MAX_TAGS} tags")
    tags = tuple(
        _text(item, f"{where}.tags[{index}]", limit=_MAX_TAG) for index, item in enumerate(tags_raw)
    )
    card_id = _text(raw.get("id"), f"{where}.id", limit=80)
    if not _CARD_ID.fullmatch(card_id):
        raise ValueError(f"{where}.id: expected K_ followed by A-Z, 0-9 or _")
    return KnowledgeCard(
        id=card_id,
        kind=kind,
        subject=subject,
        verifications=verifications,
        title=_text(raw.get("title"), f"{where}.title", limit=_MAX_TITLE),
        body=_text(raw.get("body"), f"{where}.body", limit=_MAX_BODY),
        tags=tags,
        source=_source(raw.get("source"), f"{where}.source"),
    )


def parse_corpus(text: str, *, origin: str = "corpus") -> tuple[KnowledgeCard, ...]:
    cards: list[KnowledgeCard] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{origin}:{line_number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{where}: invalid JSON: {exc.msg}") from exc
        card = _card(raw, where)
        if card.id in seen:
            raise ValueError(f"{where}: duplicate card id {card.id!r}")
        seen.add(card.id)
        cards.append(card)
    if not cards:
        raise ValueError(f"{origin}: no knowledge cards")
    return tuple(cards)


def load_corpus(path: Path | None = None) -> tuple[KnowledgeCard, ...]:
    if path is None:
        text = (
            resources.files("synapse.infrastructure.knowledge")
            .joinpath(DEFAULT_CORPUS)
            .read_text(encoding="utf-8")
        )
        origin = DEFAULT_CORPUS
    else:
        text = path.read_text(encoding="utf-8")
        origin = str(path)
    return parse_corpus(text, origin=origin)
