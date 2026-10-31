from __future__ import annotations

import pytest

from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.dialogue.table import IllegalTransition, legal_events, next_state


def test_happy_path_transitions() -> None:
    state = DialogueState.INGEST
    for event, expected in (
        (DialogueEvent.INGESTED, DialogueState.PARSE),
        (DialogueEvent.PARSED, DialogueState.ALIGN),
        (DialogueEvent.ALIGNED, DialogueState.PROBE),
        (DialogueEvent.PROBE_ANSWERED, DialogueState.PROBE),
        (DialogueEvent.DIAGNOSIS_READY, DialogueState.DIAGNOSE),
        (DialogueEvent.INTERVENTION_STARTED, DialogueState.INTERVENE),
        (DialogueEvent.VERIFY_SCHEDULED, DialogueState.VERIFY),
        (DialogueEvent.VERIFIED, DialogueState.CLOSED),
    ):
        state = next_state(state, event)
        assert state is expected


def test_illegal_transition_is_explicit() -> None:
    with pytest.raises(IllegalTransition) as exc:
        next_state(DialogueState.INGEST, DialogueEvent.VERIFIED)
    assert exc.value.state is DialogueState.INGEST
    assert exc.value.event is DialogueEvent.VERIFIED


def test_closed_is_idempotent() -> None:
    assert next_state(DialogueState.CLOSED, DialogueEvent.CLOSE) is DialogueState.CLOSED
    assert DialogueEvent.CLOSE in legal_events(DialogueState.CLOSED)


def test_blank_attempt_path_enters_and_leaves_scaffold() -> None:
    assert next_state(DialogueState.PROBE, DialogueEvent.SCAFFOLD_READY) is DialogueState.SCAFFOLD
    assert next_state(DialogueState.SCAFFOLD, DialogueEvent.WORK_SUBMITTED) is DialogueState.PROBE
    assert next_state(DialogueState.SCAFFOLD, DialogueEvent.ABORT) is DialogueState.STOP
    assert next_state(DialogueState.SCAFFOLD, DialogueEvent.CLOSE) is DialogueState.CLOSED
