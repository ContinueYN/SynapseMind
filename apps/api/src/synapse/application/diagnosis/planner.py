"""Probe planning strategies.

Pattern: Strategy. The planner chooses *what to ask*; the composer turns it
into a prompt; the state machine decides whether asking is legal.
"""

from __future__ import annotations

from typing import Protocol

from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Probe, SolutionGraph


class ProbePlanner(Protocol):
    def next(self, session: DialogueSession, graph: SolutionGraph) -> Probe | None: ...


class HypothesisTargetedPlanner:
    """Prefer probes that discriminate the current top hypotheses.

    Falls back to the first unasked probe so a sparse graph still produces a
    conversation. No probe is ever repeated.
    """

    def next(self, session: DialogueSession, graph: SolutionGraph) -> Probe | None:
        candidates = [probe for probe in graph.probes() if probe.id not in session.asked_probe_ids]
        if not candidates:
            return None

        top_ids = {
            hyp_id for hyp_id, _ in (session.hypotheses.top(), session.hypotheses.runner_up())
        }
        scored: list[tuple[int, int, Probe]] = []
        for index, probe in enumerate(candidates):
            overlap = len(top_ids.intersection(probe.targets))
            scored.append((overlap, -index, probe))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2]
