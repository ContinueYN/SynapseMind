"""Load and validate the checked-in knowledge corpus."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from synapse.domain.knowledge.models import KnowledgeCard, KnowledgeSource

DEFAULT_CORPUS = "corpus.jsonl"
_MAX_TITLE = 60
_MAX_BODY = 600
_MAX_TAG = 24
_MAX_TAGS = 8
_CARD_ID = re.compile(r"^K_[A-Z0-9_]+$")


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
    extra = set(raw) - {"id", "subject", "title", "body", "tags", "source"}
    if extra:
        raise ValueError(f"{where}: unexpected fields {sorted(extra)}")
    subject = _text(raw.get("subject"), f"{where}.subject", limit=20)
    if subject not in {"math", "physics", "chinese"}:
        raise ValueError(f"{where}.subject: unsupported subject {subject!r}")
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
        subject=subject,
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
