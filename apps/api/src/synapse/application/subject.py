"""Subject plugin port (M2.5 S2).

The dialogue kernel never learns which subject it is talking about: a plugin
supplies the *content* (how to identify a problem, which graph, which probes,
which evidence weights, whether a step can be verified) and the state machine
still decides the next state.

Three constraints from chapter 13 §13.4:

1. ``verify()`` may return ``unknown`` — that is the honest exit for subjects
   without objective truth, not a defect;
2. the state machine does not import this module;
3. generated graphs must pass ``specs/solution-graph.schema.json`` before use
   (S4 adds validation; S2 wraps the hand-written seed graph).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from synapse.domain.problem.models import Probe, Problem, SolutionGraph, SolutionNode


class VerifiabilityLevel(StrEnum):
    """How much the product may promise for a subject (chapter 13 §13.3)."""

    STRONG = "strong"  # math: symbolic/numeric checks, counter-examples
    PARTIAL = "partial"  # physics/chemistry: units, structure, numeric replay
    NONE = "none"  # languages/humanities: structure hints only


@dataclass(frozen=True, slots=True)
class ProblemRef:
    problem_id: str
    subject: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class EvidenceModel:
    """``probe_id -> option_id -> hypothesis_id -> log-odds weight``.

    Same shape as the M1 constant, so switching a plugin in cannot change how
    ``HypothesisSet.observe`` reads evidence.
    """

    weights: Mapping[str, Mapping[str, Mapping[str, float]]]

    def for_probe(self, probe_id: str) -> Mapping[str, Mapping[str, float]]:
        return self.weights.get(probe_id, {})

    @property
    def probe_ids(self) -> tuple[str, ...]:
        return tuple(self.weights)


@dataclass(frozen=True, slots=True)
class StudentStep:
    node_id: str
    text: str
    turn: int = 0


VerdictStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True, slots=True)
class Verdict:
    status: VerdictStatus
    detail: str = ""


class SubjectPlugin(Protocol):
    subject: str
    level: VerifiabilityLevel

    def identify(self, text: str) -> ProblemRef | None:
        """Recognise a problem this plugin can serve; ``None`` means "not mine"."""
        ...

    def build_graph(self, problem: Problem) -> SolutionGraph: ...

    def probes_for(self, node: SolutionNode) -> tuple[Probe, ...]: ...

    def evidence_model(self, graph: SolutionGraph) -> EvidenceModel: ...

    def verify(self, step: StudentStep) -> Verdict: ...


@dataclass(frozen=True, slots=True)
class SubjectRegistry:
    """Lookup by subject, and identification across plugins."""

    plugins: tuple[SubjectPlugin, ...]

    def for_subject(self, subject: str) -> SubjectPlugin | None:
        for plugin in self.plugins:
            if plugin.subject == subject:
                return plugin
        return None

    def identify(self, text: str) -> tuple[SubjectPlugin, ProblemRef] | None:
        for plugin in self.plugins:
            ref = plugin.identify(text)
            if ref is not None:
                return plugin, ref
        return None


class ProblemIdentifier(Protocol):
    """Map submitted text to an annotated problem id, or ``None``.

    Kept separate from the plugin: a plugin can only serve problems *it* owns,
    while identification is one decision over the whole catalog (S4 swaps the
    text matcher for a generated one here).
    """

    def identify(self, text: str) -> str | None: ...
