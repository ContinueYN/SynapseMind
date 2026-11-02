"""Domain -> HTTP mappers.

Routes and response validation only see these DTOs. The answer store is not
reachable from here.
"""

from __future__ import annotations

from synapse.api.schemas import (
    AgentCitationOut,
    AgentLimitsOut,
    AgentPlannerOut,
    AgentReflectionOut,
    AgentStepOut,
    AgentSuggestionOut,
    AgentTraceOut,
    AttributionDimensionOut,
    AttributionOut,
    AuthUserOut,
    CardOut,
    CoachOut,
    CoachPointOut,
    DiagnosisOut,
    DomainIntakeOut,
    DomainOut,
    ExecutionFindingOut,
    ExecutionOut,
    GenericReviewOut,
    HintOut,
    HintStepOut,
    HistoryItemOut,
    IntakeNodeOut,
    IntakeProbeOut,
    IntakeVerificationOut,
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
from synapse.application.agent import AgentTrace
from synapse.application.auth import AuthUser
from synapse.application.coach import CoachOut as CoachResult
from synapse.application.composer import ProbePrompt
from synapse.application.domains import DomainDescriptor
from synapse.application.execution import ExecutionResult
from synapse.application.intake import DomainIntake
from synapse.application.knowledge import KnowledgeSearch
from synapse.application.review import ReviewItem
from synapse.application.scaffold import Scaffold
from synapse.application.service import SessionView
from synapse.application.subject import Verdict
from synapse.domain.diagnosis.hint import StructureHint
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.knowledge.models import KnowledgeHit
from synapse.domain.problem.generic_review import GenericReview


def _knowledge_excerpt(body: str, limit: int = 300) -> str:
    if len(body) <= limit:
        return body
    return body[: limit - 1] + "…"


def _clip_text(text: str, limit: int) -> str:
    """Keep a mapper-produced string inside its DTO limit without dropping it."""

    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _knowledge_hit(hit: KnowledgeHit) -> KnowledgeHitOut:
    card = hit.card
    return KnowledgeHitOut(
        card_id=card.id,
        kind=card.kind,
        subject=card.subject,
        verifications=list(card.verifications),
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
        version="0.2",
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
            attribution=(
                AttributionOut(
                    dimensions=[
                        AttributionDimensionOut(
                            key=dimension.key,
                            label=dimension.label,
                            weight=dimension.weight,
                        )
                        for dimension in card.attribution.dimensions
                    ],
                    all_dimensions=[
                        AttributionDimensionOut(
                            key=dimension.key,
                            label=dimension.label,
                            weight=dimension.weight,
                        )
                        for dimension in card.attribution.all_dimensions
                    ],
                    note=card.attribution.note,
                )
                if card.attribution is not None
                else None
            ),
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


def domain_out(descriptor: DomainDescriptor) -> DomainOut:
    return DomainOut(
        name=_clip(descriptor.name, 40),
        label=_clip(descriptor.label, 40),
        verification=descriptor.verification.value,
        generic=descriptor.generic,
        confidence=round(descriptor.confidence, 3),
    )


def generic_review_out(review: GenericReview) -> GenericReviewOut:
    """Validate the published generic-review shape through the DTO.

    The domain object builds ``to_dict()`` with the contract's own keys, so the
    DTO is checked against the schema instead of being hand-mapped field by
    field. If the two ever drift, response validation fails here.
    """

    return GenericReviewOut.model_validate(review.to_dict())


def intake_out(intake: DomainIntake) -> DomainIntakeOut:
    """Map the generic entry; it carries no answer and no diagnosis."""

    return DomainIntakeOut(
        version=intake.version,
        domain=domain_out(
            intake.profile.describe(intake.confidence),
        ),
        one_line=_clip(intake.one_line, 200),
        checklist=[_clip(item, 80) for item in intake.checklist[:6]],
        observed=[_clip(item, 20) for item in intake.observed[:12]],
        gaps=[_clip(item, 120) for item in intake.gaps[:3]],
        origin=intake.origin,
        graph=[
            IntakeNodeOut(
                kind=node.kind.value,
                label=_clip(node.label, 20),
                text=_clip(node.text, 120),
                source=node.source,
            )
            for node in intake.graph[:12]
        ],
        verifications=[
            IntakeVerificationOut(
                kind=check.kind,
                status=check.status,
                detail=_clip(check.detail, 400),
            )
            for check in intake.verifications[:2]
        ],
        clarifier=_clip(intake.clarifier, 200) if intake.clarifier else None,
        probe=(
            IntakeProbeOut(
                kind=intake.probe.kind.value,
                question=_clip(intake.probe.question, 200),
                answered=intake.probe.answered,
                limit=intake.probe.limit,
            )
            if intake.probe is not None
            else None
        ),
        next_step=_clip(intake.next_step, 300),
        disclaimer=_clip(intake.disclaimer, 300),
        review=generic_review_out(intake.review) if intake.review is not None else None,
    )


def session_out(
    view: SessionView,
    problem_title: str,
    problem_text: str,
    subject: str,
    domain: DomainDescriptor,
) -> SessionOut:
    session = view.session
    return SessionOut(
        session_id=session.session_id,
        state=session.state.value,
        problem_id=session.problem_id,
        problem_title=problem_title,
        problem_text=problem_text,
        subject=subject,
        domain=domain_out(domain),
        mode=session.mode,
        turn=session.turn,
        max_turns=session.max_turns,
        prompt=probe_out(view.prompt) if view.prompt else None,
        diagnosis=diagnosis_out(view.diagnosis) if view.diagnosis else None,
        hint=hint_out(view.hint) if view.hint else None,
        scaffold=scaffold_out(view.scaffold) if view.scaffold else None,
        intake=intake_out(view.intake) if view.intake else None,
        notice=(
            view.reveal.notice if view.reveal is not None and view.reveal.notice else view.notice
        ),
        answer=view.reveal.answer if view.reveal else None,
        solution=view.reveal.solution if view.reveal else None,
        progress=progress_out(session),
        history=[history_out(record) for record in session.history],
    )


def execution_out(result: ExecutionResult) -> ExecutionOut:
    return ExecutionOut(
        version="0.1",
        status=result.status,
        detail=result.detail,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        truncated=result.truncated,
        findings=[
            ExecutionFindingOut(code=finding.code, message=finding.message)
            for finding in result.findings
        ],
    )


def agent_trace_out(trace: AgentTrace) -> AgentTraceOut:
    return AgentTraceOut(
        version=trace.version,
        session_id=trace.session_id,
        mode=trace.mode,
        planner=AgentPlannerOut(
            status=trace.planner.status,
            reason=trace.planner.reason,
            tool=trace.planner.tool,
        ),
        steps=[
            AgentStepOut(
                index=step.index,
                tool=step.tool,
                status=step.status,
                input_summary=step.input_summary,
                output_summary=step.output_summary,
                duration_ms=step.duration_ms,
                citations=[
                    AgentCitationOut(
                        card_id=citation.card_id,
                        title=citation.title,
                        source_title=citation.source_title,
                        source_url=citation.source_url,
                        license=citation.license,
                    )
                    for citation in step.citations
                ],
            )
            for step in trace.steps
        ],
        suggestions=[
            AgentSuggestionOut(
                kind=suggestion.kind,
                text=suggestion.text,
                source=suggestion.source,
            )
            for suggestion in trace.suggestions
        ],
        reflection=AgentReflectionOut(
            focus=trace.reflection.focus,
            next=trace.reflection.next,
            boundary=trace.reflection.boundary,
        ),
        limits=AgentLimitsOut(
            max_steps=trace.limits.max_steps,
            steps_used=trace.limits.steps_used,
        ),
        notice=trace.notice,
    )


def coach_out(result: CoachResult) -> CoachOut:
    """Map the application DTO to the wire shape.

    Text is clipped to the schema's limits here rather than letting response
    validation fail: the coach must always answer, even when a rule line is
    slightly too long. ``not_claimed`` stays a list, never a single sentence.
    """

    return CoachOut(
        version="0.1",
        mode=result.mode,
        focus=result.focus,
        headline=_clip_text(result.headline, 160),
        points=[
            CoachPointOut(
                kind=point.kind,
                text=_clip_text(point.text, 200),
                basis=_clip_text(point.basis, 64),
            )
            for point in result.points
        ],
        next_question=_clip_text(result.next_question, 200),
        not_claimed=[_clip_text(item, 200) for item in result.not_claimed],
        disclaimer=_clip_text(result.disclaimer, 320),
    )


def auth_user_out(user: AuthUser) -> AuthUserOut:
    """Only the public account fields; digest and token are not reachable here."""

    return AuthUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
    )
