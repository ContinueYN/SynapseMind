"""Generic-graph generation port (Phase 1b).

Phase 1a could only read structure out of the student's own words. A generated
graph adds the other half: the same eleven node kinds, organised from the
problem itself, so an open domain gets a content graph instead of a blank page.

The port lives here as pure data + a Protocol, exactly like ``application/graph``:
the domain and the service never import a model client, and the implementation
is ``infrastructure.llm.generic_graph``. A failed build is explicit and the
caller degrades to the Phase 0 intake; it never fabricates a graph from rules,
because a rule table cannot understand an arbitrary problem.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.application.diagnosis.domains import IntakeFramework, VerificationMode
from synapse.domain.problem.generic import ClaimCheck, GenericGraph

GenericGraphFailureReason = Literal[
    "disabled",  # no key / mode off
    "invalid_draft",  # id does not match the problem-id contract
    "timeout",
    "transport",
    "bad_json",
    "schema_invalid",
    "degenerate",  # too few nodes, no goal, or fewer than two options
]


@dataclass(frozen=True, slots=True)
class GenericGraphDraft:
    """Everything the model may use to organise a generic problem.

    ``answer``/``work`` are the student's own text. The formalisation is allowed
    to read the answer the student already wrote; it is never allowed to solve
    the problem for them. ``structured`` is a future hook for structured
    empirical input (equation + units) — absent means the empirical verifier
    must return ``unknown`` rather than guess units from prose.
    """

    id: str
    text: str
    label: str
    verification: VerificationMode
    framework: IntakeFramework
    answer: str = ""
    work: str = ""
    structured: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class GenericGraphBuildResult:
    graph: GenericGraph
    checks: tuple[ClaimCheck, ...] = ()
    attempts: int = 1
    repairs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    cached: bool = False


class GenericGraphBuildFailed(RuntimeError):
    """The model could not organise this problem; the caller keeps the floor."""

    def __init__(
        self,
        reason: GenericGraphFailureReason,
        *,
        detail: str = "",
        attempts: int = 0,
    ) -> None:
        message = f"{reason}: {detail}" if detail else reason
        super().__init__(message)
        self.reason = reason
        self.detail = detail
        self.attempts = attempts


class GenericGraphGenerator(Protocol):
    def generate(self, draft: GenericGraphDraft) -> GenericGraphBuildResult: ...
