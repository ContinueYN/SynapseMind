"""Shared text helpers for the domain -> HTTP mappers."""

from __future__ import annotations


def clip(text: str, limit: int) -> str:
    """Fit a string inside a DTO limit without dropping it."""

    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def clip_text(text: str, limit: int) -> str:
    """Strip, then keep a mapper-produced string inside its DTO limit."""

    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"
