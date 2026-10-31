"""Events accepted by the dialogue transition table."""

from __future__ import annotations

from enum import StrEnum


class DialogueEvent(StrEnum):
    INGESTED = "ingested"
    PARSED = "parsed"
    NEED_INPUT = "need_input"
    INPUT_CONFIRMED = "input_confirmed"
    ALIGNED = "aligned"
    SCAFFOLD_READY = "scaffold_ready"
    WORK_SUBMITTED = "work_submitted"
    PROBE_ANSWERED = "probe_answered"
    DIAGNOSIS_READY = "diagnosis_ready"
    INTERVENTION_STARTED = "intervention_started"
    VERIFY_SCHEDULED = "verify_scheduled"
    VERIFIED = "verified"
    TURN_LIMIT = "turn_limit"
    ABORT = "abort"
    CLOSE = "close"
