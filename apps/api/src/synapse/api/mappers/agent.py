"""Agent trace mapper."""

from __future__ import annotations

from synapse.api.schemas.agent import (
    AgentCitationOut,
    AgentLimitsOut,
    AgentPlannerOut,
    AgentReflectionOut,
    AgentStepOut,
    AgentSuggestionOut,
    AgentTraceOut,
)
from synapse.application.diagnosis.agent import AgentTrace


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
