"""Domain -> HTTP mappers.

Routes and response validation only see these DTOs. The answer store is not
reachable from here.
"""

from __future__ import annotations

from synapse.api.schemas import (
    CardOut,
    DiagnosisOut,
    HistoryItemOut,
    NextActionOut,
    ProbeOut,
    ProgressOut,
    SessionOut,
    VerifyOut,
)
from synapse.application.composer import ProbePrompt
from synapse.application.service import SessionView
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.dialogue.session import DialogueSession, TurnRecord


def probe_out(prompt: ProbePrompt) -> ProbeOut:
    return ProbeOut(
        action=prompt.action,
        question=prompt.question,
        options=list(prompt.options),
        hint_level=prompt.hint_level,
        reason_code=prompt.reason_code,
        confidence=prompt.confidence,
    )


def progress_out(session: DialogueSession) -> ProgressOut:
    top_id, confidence = session.hypotheses.top()
    return ProgressOut(
        turn=session.turn,
        max_turns=session.max_turns,
        confidence=round(confidence, 2),
        top_hypothesis=top_id,
    )


def history_out(record: TurnRecord) -> HistoryItemOut:
    return HistoryItemOut(
        turn=record.turn,
        question=record.question,
        answer=record.answer,
        option_id=record.option_id,
        action=record.action,
        is_unknown=record.is_unknown,
    )


def diagnosis_out(card: DiagnosisCard) -> DiagnosisOut:
    return DiagnosisOut(
        version=card.version,
        session_id=card.session_id,
        problem_id=card.problem_id,
        card=CardOut(
            layer=card.layer,
            label=card.label,
            node_id=card.node_id,
            one_line=card.one_line,
            evidence=list(card.evidence),
            excluded=list(card.excluded),
            confidence=card.confidence,
            confidence_label=card.confidence_label,
            next_action=NextActionOut.model_validate(card.next_action),
            verify=VerifyOut.model_validate(card.verify),
            disagree=card.disagree,
        ),
    )


def session_out(view: SessionView, problem_title: str, problem_text: str) -> SessionOut:
    session = view.session
    return SessionOut(
        session_id=session.session_id,
        state=session.state.value,
        problem_id=session.problem_id,
        problem_title=problem_title,
        problem_text=problem_text,
        mode=session.mode,
        turn=session.turn,
        max_turns=session.max_turns,
        prompt=probe_out(view.prompt) if view.prompt else None,
        diagnosis=diagnosis_out(view.diagnosis) if view.diagnosis else None,
        notice=view.notice,
        progress=progress_out(session),
        history=[history_out(record) for record in session.history],
    )
