"""Problem, solution graph and student-attempt models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Probe:
    """A single discriminating question attached to a solution-graph node."""

    id: str
    question: str
    options: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    hint_level: int = 0
    # ``option letter -> hypothesis id -> log-odds`` (M2.5 S5). A generated
    # graph carries its own evidence; the hand-written seed graph keeps using
    # the table in ``EVIDENCE``. Empty means "this probe carries no evidence",
    # never "fall back to another problem's weights".
    evidence: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    # Kept in the graph, never serialised into a learning-mode response.
    correct_option: str | None = None


@dataclass(frozen=True, slots=True)
class SolutionNode:
    id: str
    type: str
    text: str
    demand: Mapping[str, float] = field(default_factory=dict)
    common_errors: tuple[str, ...] = ()
    probes: tuple[Probe, ...] = ()


@dataclass(frozen=True, slots=True)
class Interval:
    """One connected piece of a parameter answer range (M2.5 S5).

    Endpoints are SymPy expression strings, not floats: ``1/E`` and ``E`` are
    the answers a student is expected to write, and rounding them before the
    verifier sees them would make boundary checks meaningless. ``None`` means
    unbounded on that side.
    """

    lower: str | None
    upper: str | None
    lower_inclusive: bool = True
    upper_inclusive: bool = True


@dataclass(frozen=True, slots=True)
class VerificationClaim:
    """A graph's formalised answer, written so a machine can falsify it.

    Meaning (chapter 13 §13.3, STRONG tier)::

        for all variable in variable_domain:  expression <relation> 0
        ⇔  parameter ∈ intervals

    v1 only covers this shape — a parameter range under a universally
    quantified one-variable constraint. Answer sets that are not a parameter
    range (a value, a solution set in x, a proof) have no claim, and the
    verifier says ``unknown`` instead of pretending.
    """

    kind: str
    parameter: str
    variable: str
    variable_domain: str
    expression: str
    relation: str
    intervals: tuple[Interval, ...]


@dataclass(frozen=True, slots=True)
class SolutionGraph:
    problem_id: str
    version: str
    stem: str
    nodes: tuple[SolutionNode, ...]
    edges: tuple[tuple[str, str], ...]
    claim: VerificationClaim | None = None

    def node(self, node_id: str) -> SolutionNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def probes(self) -> tuple[Probe, ...]:
        return tuple(probe for node in self.nodes for probe in node.probes)

    def probe(self, probe_id: str) -> Probe:
        for probe in self.probes():
            if probe.id == probe_id:
                return probe
        raise KeyError(probe_id)


@dataclass(frozen=True, slots=True)
class Problem:
    id: str
    title: str
    text: str
    graph: SolutionGraph
    subject: str = "math"
    grade: str = "high_school"
    # ``False`` for a graph the model generated for a submitted stem (M2.5 S5
    # ②): it has no reviewed reference solution, no hand-tuned aligner and no
    # curated card text, so everything downstream must stay hedged.
    annotated: bool = True


@dataclass(frozen=True, slots=True)
class ProblemDraft:
    """A submitted problem that has no annotated graph yet (M2.5 S4).

    Kept separate from ``Problem`` on purpose: a ``Problem`` always owns a
    graph, while a draft is exactly the input the model is asked to decompose.
    Until S5 wires generated graphs into the request path, drafts only flow
    through the graph generator and the S4 evaluation harness.
    """

    id: str
    text: str
    subject: str = "math"
    grade: str = "high_school"


@dataclass(frozen=True, slots=True)
class StudentAttempt:
    answer: str
    work: str = ""
    stuck_at: str = ""
    confidence: int | None = None
    self_report: str | None = None

    @property
    def knows_nothing(self) -> bool:
        return self.self_report == "no_idea" or self.answer.strip() in {
            "",
            "不会",
            "不知道",
            "完全不会",
        }


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Where the student's process first diverges from the reference graph."""

    first_divergence: str
    matched_node_ids: tuple[str, ...]
    missing_node_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    excluded: tuple[str, ...] = ()
