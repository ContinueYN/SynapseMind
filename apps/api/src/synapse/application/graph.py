"""Solution-graph generation port (M2.5 S4).

Chapter 13 §13.5 puts ``build_graph()`` between identification and alignment.
The port lives here (pure data + Protocol) so the state machine and the
application service never import a model client; the LLM implementation lives
in ``infrastructure.llm.graph``.

A failed build is always explicit. There is no rule-based fallback for an
arbitrary problem — inventing a graph would be worse than saying "this version
cannot decompose the problem".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from synapse.application.verification import VerificationResult
from synapse.domain.problem.models import ProblemDraft, SolutionGraph

GraphFailureReason = Literal[
    "disabled",  # no key / mode off
    "invalid_draft",  # draft id does not match the contract
    "timeout",
    "transport",
    "bad_json",  # the model did not return a parsable object
    "schema_invalid",  # parsed, but violates the graph contract
    "degenerate",  # too few nodes / no dependency to speak of
]


@dataclass(frozen=True, slots=True)
class GraphBuildResult:
    graph: SolutionGraph
    fingerprint: str
    attempts: int
    repairs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    cached: bool = False
    # ``pass`` (no counterexample found), ``unknown`` (nothing to check / could
    # not decide) or ``fail``. A ``fail`` never fails the build: the interval is
    # repaired by a claim-only call (the graph is not regenerated), and a claim
    # that is still refuted is dropped (``claim_dropped_refuted``) so
    # ``graph.claim`` stays ``None`` and nothing downstream can read a refuted
    # range as checked. The counterexample itself is kept here.
    verification: VerificationResult | None = None


class GraphBuildFailed(RuntimeError):
    """The graph could not be built; callers must surface it, not paper over it."""

    def __init__(
        self,
        reason: GraphFailureReason,
        *,
        detail: str = "",
        attempts: int = 0,
    ) -> None:
        message = f"{reason}: {detail}" if detail else reason
        super().__init__(message)
        self.reason = reason
        self.detail = detail
        self.attempts = attempts


class GraphGenerator(Protocol):
    def generate(self, draft: ProblemDraft) -> GraphBuildResult: ...
