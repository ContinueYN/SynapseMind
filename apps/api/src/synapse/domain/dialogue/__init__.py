"""Dialogue domain package."""

from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.dialogue.states import DialogueAction, DialogueState
from synapse.domain.dialogue.table import IllegalTransition, next_state

__all__ = [
    "DialogueAction",
    "DialogueEvent",
    "DialogueSession",
    "DialogueState",
    "IllegalTransition",
    "TurnRecord",
    "next_state",
]
