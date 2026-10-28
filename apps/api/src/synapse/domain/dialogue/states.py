"""Dialogue states and actions."""

from __future__ import annotations

from enum import StrEnum


class DialogueState(StrEnum):
    INGEST = "INGEST"
    PARSE = "PARSE"
    NEED_INPUT = "NEED_INPUT"
    ALIGN = "ALIGN"
    PROBE = "PROBE"
    DIAGNOSE = "DIAGNOSE"
    INTERVENE = "INTERVENE"
    VERIFY = "VERIFY"
    STOP = "STOP"
    CLOSED = "CLOSED"


class DialogueAction(StrEnum):
    ASK = "ask"
    HINT = "hint"
    CONFIRM = "confirm"
    DIAGNOSE = "diagnose"
    INTERVENE = "intervene"
    STOP = "stop"
    OFFER_ANSWER_EXIT = "offer_answer_exit"
