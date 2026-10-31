"""The single source of truth for legal dialogue transitions.

LLM output never selects a state directly. The application emits an event and
this table either accepts it or raises. Keeping the table pure makes it cheap
to exhaustively test.
"""

from __future__ import annotations

from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.states import DialogueState

Transition = tuple[DialogueState, DialogueEvent]


class IllegalTransition(ValueError):
    def __init__(self, state: DialogueState, event: DialogueEvent) -> None:
        super().__init__(f"illegal transition: {state} + {event}")
        self.state = state
        self.event = event


TRANSITIONS: dict[Transition, DialogueState] = {
    (DialogueState.INGEST, DialogueEvent.INGESTED): DialogueState.PARSE,
    (DialogueState.PARSE, DialogueEvent.PARSED): DialogueState.ALIGN,
    (DialogueState.PARSE, DialogueEvent.NEED_INPUT): DialogueState.NEED_INPUT,
    (DialogueState.NEED_INPUT, DialogueEvent.INPUT_CONFIRMED): DialogueState.PARSE,
    (DialogueState.NEED_INPUT, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.ALIGN, DialogueEvent.ALIGNED): DialogueState.PROBE,
    # The factory lands on PROBE after ALIGN. A blank attempt is diverted from
    # there into SCAFFOLD; submitting work returns to PROBE.
    (DialogueState.PROBE, DialogueEvent.SCAFFOLD_READY): DialogueState.SCAFFOLD,
    (DialogueState.SCAFFOLD, DialogueEvent.WORK_SUBMITTED): DialogueState.PROBE,
    (DialogueState.SCAFFOLD, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.SCAFFOLD, DialogueEvent.CLOSE): DialogueState.CLOSED,
    (DialogueState.ALIGN, DialogueEvent.DIAGNOSIS_READY): DialogueState.DIAGNOSE,
    (DialogueState.ALIGN, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.PROBE, DialogueEvent.PROBE_ANSWERED): DialogueState.PROBE,
    (DialogueState.PROBE, DialogueEvent.DIAGNOSIS_READY): DialogueState.DIAGNOSE,
    (DialogueState.PROBE, DialogueEvent.TURN_LIMIT): DialogueState.STOP,
    (DialogueState.PROBE, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.PROBE, DialogueEvent.CLOSE): DialogueState.CLOSED,
    (DialogueState.DIAGNOSE, DialogueEvent.INTERVENTION_STARTED): DialogueState.INTERVENE,
    (DialogueState.DIAGNOSE, DialogueEvent.CLOSE): DialogueState.CLOSED,
    (DialogueState.INTERVENE, DialogueEvent.VERIFY_SCHEDULED): DialogueState.VERIFY,
    (DialogueState.INTERVENE, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.VERIFY, DialogueEvent.VERIFIED): DialogueState.CLOSED,
    (DialogueState.VERIFY, DialogueEvent.ABORT): DialogueState.STOP,
    (DialogueState.STOP, DialogueEvent.CLOSE): DialogueState.CLOSED,
    (DialogueState.CLOSED, DialogueEvent.CLOSE): DialogueState.CLOSED,
}


def next_state(state: DialogueState, event: DialogueEvent) -> DialogueState:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise IllegalTransition(state, event) from exc


def legal_events(state: DialogueState) -> frozenset[DialogueEvent]:
    return frozenset(event for (current, event) in TRANSITIONS if current is state)
