"""Dialogue states and actions."""

from __future__ import annotations

from enum import StrEnum


class DialogueState(StrEnum):
    INGEST = "INGEST"
    PARSE = "PARSE"
    NEED_INPUT = "NEED_INPUT"
    ALIGN = "ALIGN"
    PROBE = "PROBE"
    # A blank attempt gets a 1–2 step example before any probe. It is a real
    # dialogue state, not a hint: the student can submit work from here and the
    # session returns to PROBE.
    SCAFFOLD = "SCAFFOLD"
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
