"""Domain -> HTTP mappers.

Routes and response validation only see these DTOs. The answer store is not
reachable from here.
"""

from __future__ import annotations

from synapse.api.schemas import (
    CardOut,
    DiagnosisOut,
    HintOut,
    HintStepOut,
    HistoryItemOut,
    KnowledgeHitOut,
    KnowledgeSearchOut,
    KnowledgeSourceOut,
    NextActionOut,
    ProbeOut,
    ProgressOut,
    ReviewItemOut,
    ReviewItemsOut,
    ScaffoldOut,
    ScaffoldStepOut,
    SessionOut,
    StepFindingOut,
    StepVerdictOut,
    VerifyOut,
)
from synapse.application.composer import ProbePrompt
from synapse.application.knowledge import KnowledgeSearch
from synapse.application.review import ReviewItem
from synapse.application.scaffold import Scaffold
from synapse.application.service import SessionView
from synapse.application.subject import Verdict
from synapse.domain.diagnosis.hint import StructureHint
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.knowledge.models import KnowledgeHit


def _knowledge_excerpt(body: str, limit: int = 300) -> str:
    if len(body) <= limit:
        return body
    return body[: limit - 1] + "…"


def _knowledge_hit(hit: KnowledgeHit) -> KnowledgeHitOut:
    card = hit.card
    return KnowledgeHitOut(
        card_id=card.id,
        title=card.title,
        excerpt=_knowledge_excerpt(card.body),
        source=KnowledgeSourceOut(
            title=card.source.title,
            url=card.source.url,
            license=card.source.license,
        ),
        score=round(max(0.0, min(1.0, hit.score)), 4),
    )


def knowledge_search_out(result: KnowledgeSearch) -> KnowledgeSearchOut:
    return KnowledgeSearchOut(
        version="0.1",
        enabled=result.enabled,
        query=result.query,
        hits=[_knowledge_hit(hit) for hit in result.hits],
    )


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


def hint_out(hint: StructureHint) -> HintOut:
    """Map the NONE-tier hint; it never carries card fields."""

    return HintOut(
        version=hint.version,
        session_id=hint.session_id,
        problem_id=hint.problem_id,
        subject=hint.subject,
        level="none",
        one_line=hint.one_line,
        steps=[
            HintStepOut(node_id=step.node_id, text=step.text, status=step.status)
            for step in hint.steps
        ],
        focus_node_id=hint.focus_node_id,
        next_step=hint.next_step,
        disclaimer=hint.disclaimer,
    )


def scaffold_out(scaffold: Scaffold) -> ScaffoldOut:
    return ScaffoldOut(
        steps=[
            ScaffoldStepOut(label=step.label, text=step.text, node_id=step.node_id)
            for step in scaffold.steps
        ],
        focus_node_id=scaffold.focus_node_id,
        next_step=scaffold.next_step,
        disclaimer=scaffold.disclaimer,
    )


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def step_verdict_out(verdict: Verdict) -> StepVerdictOut:
    """Map one verification result; ``findings`` is empty unless it failed.

    The formulas come from the student's own text, so they are clipped to the
    DTO limit here rather than letting a pathological chain fail response
    validation.
    """

    return StepVerdictOut(
        version="0.3",
        status=verdict.status,
        detail=_clip(verdict.detail, 1000),
        findings=[
            StepFindingOut(
                kind=finding.kind,
                left=_clip(finding.left, 500),
                right=_clip(finding.right, 500),
                summary=_clip(
                    finding.summary or finding.counterexample or finding.detail or "这处等号不成立",
                    300,
                ),
                counterexample=_clip(finding.counterexample, 300),
            )
            for finding in verdict.findings[:3]
        ],
    )


def review_item_out(item: ReviewItem) -> ReviewItemOut:
    """Map one queue row; the queue has no student text to leak."""

    return ReviewItemOut(
        session_id=item.session_id,
        problem_id=item.problem_id,
        layer=item.layer,
        label=_clip(item.label, 40),
        node_id=item.node_id,
        one_line=_clip(item.one_line, 200),
        confidence=item.confidence,
        created_at=item.created_at,
    )


def review_items_out(items: list[ReviewItem]) -> ReviewItemsOut:
    return ReviewItemsOut(
        version="0.1",
        items=[review_item_out(item) for item in items],
    )


def session_out(
    view: SessionView,
    problem_title: str,
    problem_text: str,
    subject: str,
) -> SessionOut:
    session = view.session
    return SessionOut(
        session_id=session.session_id,
        state=session.state.value,
        problem_id=session.problem_id,
        problem_title=problem_title,
        problem_text=problem_text,
        subject=subject,
        mode=session.mode,
        turn=session.turn,
        max_turns=session.max_turns,
        prompt=probe_out(view.prompt) if view.prompt else None,
        diagnosis=diagnosis_out(view.diagnosis) if view.diagnosis else None,
        hint=hint_out(view.hint) if view.hint else None,
        scaffold=scaffold_out(view.scaffold) if view.scaffold else None,
        notice=view.notice,
        progress=progress_out(session),
        history=[history_out(record) for record in session.history],
    )
