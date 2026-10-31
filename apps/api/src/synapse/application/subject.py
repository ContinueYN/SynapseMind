"""Subject plugin port (M2.5 S2).

The dialogue kernel never learns which subject it is talking about: a plugin
supplies the *content* (how to identify a problem, which graph, which alignment
strategy, which probes, which evidence weights, whether a step can be verified)
and the state machine still decides the next state.

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

from synapse.domain.diagnosis.work import WorkFinding
from synapse.domain.problem.alignment import StepAligner
from synapse.domain.problem.models import (
    Probe,
    Problem,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)


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
    """One step of a student's work, optionally with structured evidence.

    ``data`` is a subject-owned payload. The dialogue kernel never reads it:
    ``ScoreEngine``/state transitions only look at ``node_id``/``text``; a
    plugin may use it in ``verify()``. Keys are deliberately not typed here so
    a new subject does not have to change the shared port. A plugin must
    document the keys it understands, and any ``unknown`` it returns must say
    what was missing.

    Physics (``PhysicsPlugin``) reserves:

    ``equation``
        One scalar equation with exactly one ``=``, e.g.
        ``"F*cos(theta) - mu*N = m*a"``. Only ``+ - * / **``,
        parentheses, numbers, declared symbols and the whitelisted functions
        ``sin/cos/tan/asin/acos/atan/sqrt/exp/log/ln/abs`` plus ``pi`` are
        accepted. No ``eval``/``exec``; implicit multiplication is rejected.
    ``expression``
        Alternative to ``equation`` when the student wrote a quantity without
        ``=``. Requires ``unit``.
    ``unit``
        Declared result unit. Required with ``expression``; optional with
        ``equation``, where it is checked against the right-hand side.
    ``units``
        ``symbol -> unit expression`` for every symbol in the equation/
        expression. The empty string means dimensionless (e.g. ``mu``).
        Examples: ``"N"``, ``"m/s^2"``, ``"kg*m/s^2"``, ``"deg"``.
    ``values``
        ``symbol -> number`` in the symbol's declared unit. Values are
        converted to SI before evaluation. Numeric replay runs only when every
        free symbol has a value.
    ``expected``
        Optional ``{"value": number, "unit": unit-expression}`` for the
        student's declared result. It is compared with the equation's
        right-hand side (or with ``expression`` when there is no equation).
    ``tolerance``
        Optional number, or ``{"relative": float, "absolute": float}``. The
        defaults are ``relative=1e-6`` and ``absolute=1e-9``.

    Math reads ``text`` as an equality chain (when ``SYNAPSE_EQUALITY_CHECK``
    is on) and ignores ``data``; graph claims are still verified by the
    separate claim verifier. ``pass`` means "the checks that ran found no
    inconsistency", never "this step is proved correct".
    """

    node_id: str
    text: str
    turn: int = 0
    data: Mapping[str, object] | None = None


VerdictStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True, slots=True)
class Verdict:
    status: VerdictStatus
    detail: str = ""
    #: Structured evidence for a ``fail``; empty for ``pass``/``unknown``.
    #: Kept alongside ``detail`` so a client can lay out formula and
    #: counterexample without parsing prose (contract v0.3).
    findings: tuple[WorkFinding, ...] = ()


class SubjectPlugin(Protocol):
    subject: str
    level: VerifiabilityLevel

    def identify(self, text: str) -> ProblemRef | None:
        """Recognise a problem this plugin can serve; ``None`` means "not mine"."""
        ...

    def build_graph(self, problem: Problem | ProblemDraft) -> SolutionGraph:
        """Return an annotated graph, or generate one for a draft (S4)."""
        ...

    def aligner_for(self, problem: Problem) -> StepAligner:
        """Which matching strategy this subject uses for this problem (S8).

        The plugin owns the choice so a subject can opt into a different
        matcher without a second dispatch in the factory or the composition
        root. ``MathPlugin`` still switches between the labelled rule aligner
        and the generic graph aligner; ``ChinesePlugin`` opts into the
        clause-level variant; physics keeps the generic two-state one so its
        S6 numbers stay comparable.
        """
        ...

    def probes_for(self, node: SolutionNode) -> tuple[Probe, ...]: ...

    def evidence_model(self, graph: SolutionGraph) -> EvidenceModel: ...

    def verify(self, step: StudentStep) -> Verdict:
        """Verify one step; read-only, never a state transition (S5 ⑥)."""
        ...


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
