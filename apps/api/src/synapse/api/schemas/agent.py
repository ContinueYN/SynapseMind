"""Bounded agent trace DTOs (v0.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from synapse.api.schemas.common import StrictModel

AgentToolOut = Literal[
    "check_structure",
    "search_patterns",
    "search_sources",
    "compare_options",
    "ask_clarifying",
    "run_code",
    "run_tests",
]
AgentStepStatusOut = Literal["ok", "skipped", "failed"]
AgentSuggestionKindOut = Literal["structure", "source", "experiment", "clarify"]
AgentSuggestionSourceOut = Literal["rule", "knowledge", "execution", "system"]
AgentPlannerStatusOut = Literal["off", "used", "fallback"]
AgentPlanningToolOut = Literal["search_patterns", "search_sources", "compare_options"]


class AgentRunRequest(StrictModel):
    """Explicit code submission for one bounded trace.

    The API never extracts code from the problem or the attempt; the caller
    must paste it. ``tests`` is optional and requires ``code``.
    """

    code: str | None = Field(default=None, min_length=1, max_length=20000)
    tests: str | None = Field(default=None, min_length=1, max_length=20000)

    @model_validator(mode="after")
    def require_code(self) -> AgentRunRequest:
        if self.code is None:
            raise ValueError("code is required")
        if self.tests is not None and not self.tests.strip():
            raise ValueError("tests must not be blank")
        return self


class AgentCitationOut(StrictModel):
    card_id: str = Field(pattern=r"^K_[A-Z0-9_]+$")
    title: str = Field(min_length=1, max_length=60)
    source_title: str = Field(min_length=1, max_length=120)
    source_url: str = Field(pattern=r"^https://")
    license: str = Field(min_length=1, max_length=80)


class AgentStepOut(StrictModel):
    index: int = Field(ge=1, le=3)
    tool: AgentToolOut
    status: AgentStepStatusOut
    input_summary: str = Field(min_length=1, max_length=200)
    output_summary: str = Field(min_length=1, max_length=600)
    duration_ms: float = Field(ge=0, le=60000)
    citations: list[AgentCitationOut] = Field(default_factory=list, max_length=3)


class AgentSuggestionOut(StrictModel):
    kind: AgentSuggestionKindOut
    text: str = Field(min_length=1, max_length=300)
    source: AgentSuggestionSourceOut


class AgentLimitsOut(StrictModel):
    max_steps: int = Field(ge=1, le=3)
    steps_used: int = Field(ge=0, le=3)


class AgentReflectionOut(StrictModel):
    """Two lines of coverage review; neither line is a diagnosis."""

    focus: str = Field(min_length=1, max_length=300)
    next: str = Field(min_length=1, max_length=300)
    boundary: str = Field(min_length=1, max_length=200)


class AgentPlannerOut(StrictModel):
    """Which middle-step tool the optional planner picked, never an outcome."""

    status: AgentPlannerStatusOut
    reason: str = Field(min_length=1, max_length=200)
    tool: AgentPlanningToolOut | None = None

    @model_validator(mode="after")
    def tool_matches_status(self) -> AgentPlannerOut:
        if self.status == "used" and self.tool is None:
            raise ValueError("used planner requires a tool")
        if self.status != "used" and self.tool is not None:
            raise ValueError("only a used planner may carry a tool")
        return self


class AgentTraceOut(StrictModel):
    """A bounded tool trace, not a diagnosis and not a chain of thought."""

    version: Literal["0.3"]
    session_id: str = Field(min_length=1, max_length=64)
    mode: Literal["rules", "llm"]
    planner: AgentPlannerOut
    steps: list[AgentStepOut] = Field(default_factory=list, max_length=3)
    suggestions: list[AgentSuggestionOut] = Field(default_factory=list, max_length=3)
    reflection: AgentReflectionOut
    limits: AgentLimitsOut
    notice: str = Field(min_length=1, max_length=300)
