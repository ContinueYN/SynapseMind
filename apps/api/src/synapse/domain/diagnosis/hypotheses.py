"""Hypothesis scoring.

The state machine decides *which transition*; this module only updates
posteriors from observable probe answers. That separation is deliberate:
an LLM can later propose hypotheses, but it cannot move the dialogue.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from synapse.domain.diagnosis.models import (
    DiagnosisDecision,
    Hypothesis,
)
from synapse.domain.problem.models import AlignmentResult

HypothesisId = str

DEFAULT_PRIORS: dict[HypothesisId, float] = {
    "H_L2": 0.55,
    "H_L1": 0.25,
    "H_L4": 0.20,
}

HYPOTHESES: dict[HypothesisId, Hypothesis] = {
    "H_L2": Hypothesis(
        id="H_L2",
        label="条件转译 / 参数分类",
        layer="L2",
        node_id="n3",
        prior=DEFAULT_PRIORS["H_L2"],
    ),
    "H_L1": Hypothesis(
        id="H_L1",
        label="概念不清：恒成立与最值",
        layer="L1",
        node_id="n2",
        prior=DEFAULT_PRIORS["H_L1"],
    ),
    "H_L4": Hypothesis(
        id="H_L4",
        label="执行 / 计算错误",
        layer="L4",
        node_id="n5",
        prior=DEFAULT_PRIORS["H_L4"],
    ),
}

# Log-odds evidence. Keys are probe ids and option ids. Missing keys mean 0.
EVIDENCE: dict[str, dict[str, dict[HypothesisId, float]]] = {
    "p_a0_derivative": {
        "A": {"H_L2": 0.30, "H_L1": -0.55, "H_L4": -0.10},
        "B": {"H_L2": -0.25, "H_L1": 0.45, "H_L4": 0.25},
        "C": {"H_L2": 0.05, "H_L1": 0.30, "H_L4": 0.00},
    },
    "p_boundary_check": {
        "A": {"H_L2": 0.50, "H_L1": -0.15, "H_L4": -0.05},
        "B": {"H_L2": 0.45, "H_L1": -0.05, "H_L4": -0.05},
        "C": {"H_L2": 0.10, "H_L1": 0.30, "H_L4": 0.00},
    },
    "p_max_value": {
        "A": {"H_L2": 0.10, "H_L1": -0.10, "H_L4": -0.55},
        "B": {"H_L2": -0.10, "H_L1": 0.15, "H_L4": 0.55},
        "C": {"H_L2": 0.00, "H_L1": 0.25, "H_L4": 0.00},
    },
    # The seed graph's fourth probe used to have no weights, so choosing an
    # option on it added nothing and the turn was wasted. Keeping only the
    # branch that passes the for-all check (C) lowers L2; union/intersection
    # both raise it.
    "p_union": {
        "A": {"H_L2": 0.50},
        "B": {"H_L2": 0.45},
        "C": {"H_L2": -0.40},
    },
}


# Which layer a *missing step* points at, by node type (M2.5 S5 ②). A student
# whose process never reaches a CONDITION node most plausibly has a condition-
# translation problem (L2); one who never reaches a COMPUTE node has an
# execution problem (L4). These are layer priors, not per-problem rules, so a
# generated graph with unfamiliar node ids still gets a sensible start.
NODE_TYPE_LAYER: dict[str, str] = {
    "READ": "L1",
    "CONCEPT": "L1",
    "CONDITION": "L2",
    "STRATEGY": "L2",
    "TRANSFORM": "L2",
    "COMPUTE": "L4",
    "CHECK": "L2",
}

# Prior profiles by focus layer. The seed's hand-written map below is a more
# specific version of the same idea; these are used when a graph has no
# hand-written profile (generated graphs).
FOCUS_PRIORS: dict[str, dict[HypothesisId, float]] = {
    "L1": {"H_L2": 0.30, "H_L1": 0.45, "H_L4": 0.25},
    "L2": {"H_L2": 0.55, "H_L1": 0.25, "H_L4": 0.20},
    "L4": {"H_L2": 0.35, "H_L1": 0.20, "H_L4": 0.45},
}


def layer_for_node_type(node_type: str) -> str | None:
    """Layer to focus on when the first missing node has this type."""

    return NODE_TYPE_LAYER.get(node_type)


@dataclass
class HypothesisState:
    hypothesis: Hypothesis
    logit: float


# ``probe_id -> option_id -> hypothesis_id -> log-odds weight``. The M1 table is
# only the default: a subject plugin may supply its own model for its graph
# (M2.5 S5), and the state machine still does the scoring.
EvidenceWeights = Mapping[str, Mapping[str, Mapping[str, float]]]


@dataclass
class HypothesisSet:
    states: dict[HypothesisId, HypothesisState] = field(default_factory=dict)
    evidence: EvidenceWeights = field(default_factory=lambda: EVIDENCE)

    @classmethod
    def from_alignment(
        cls,
        alignment: AlignmentResult,
        *,
        evidence: EvidenceWeights | None = None,
        focus: str | None = None,
        labels: Mapping[HypothesisId, str] | None = None,
    ) -> HypothesisSet:
        """Seed the priors from where the process first diverges.

        ``focus`` is a layer ("L1"/"L2"/"L4") derived from the *type* of the
        missing node; it is what a generated graph uses, because node ids there
        carry no hand-tuned meaning. Without it the mapping falls back to the
        seed's node ids — kept as-is so the annotated catalog behaves exactly
        as it did before S5 ② (and the golden baseline stays comparable).

        ``labels`` lets a subject plugin rename the same three hypothesis ids
        in its own vocabulary (S6). Scoring, priors and the state machine are
        untouched: only the human-readable label changes, so a physics card
        never says "恒成立与最值".
        """

        priors = dict(DEFAULT_PRIORS)
        if focus in FOCUS_PRIORS:
            priors = dict(FOCUS_PRIORS[focus])
        elif alignment.first_divergence == "n3":
            priors = {"H_L2": 0.60, "H_L1": 0.25, "H_L4": 0.15}
        elif alignment.first_divergence == "n2":
            priors = {"H_L2": 0.35, "H_L1": 0.45, "H_L4": 0.20}
        elif alignment.first_divergence == "n5":
            priors = {"H_L2": 0.35, "H_L1": 0.20, "H_L4": 0.45}
        elif alignment.first_divergence in {"n1", "none"}:
            priors = {"H_L2": 0.30, "H_L1": 0.45, "H_L4": 0.25}

        total = sum(priors.values())
        states: dict[HypothesisId, HypothesisState] = {}
        for hypothesis_id, hypothesis in HYPOTHESES.items():
            if labels and hypothesis_id in labels:
                hypothesis = replace(hypothesis, label=labels[hypothesis_id])
            prior = priors[hypothesis_id] / total
            states[hypothesis_id] = HypothesisState(
                hypothesis=hypothesis,
                logit=math.log(prior),
            )
        return cls(
            states=states,
            evidence=EVIDENCE if evidence is None else evidence,
        )

    def _softmax(self) -> dict[HypothesisId, float]:
        if not self.states:
            return {}
        max_logit = max(state.logit for state in self.states.values())
        weights = {
            hyp_id: math.exp(state.logit - max_logit) for hyp_id, state in self.states.items()
        }
        total = sum(weights.values()) or 1.0
        return {hyp_id: weight / total for hyp_id, weight in weights.items()}

    def posteriors(self) -> dict[HypothesisId, float]:
        return self._softmax()

    def top(self) -> tuple[HypothesisId, float]:
        ranked = sorted(self.posteriors().items(), key=lambda item: item[1], reverse=True)
        return ranked[0]

    def runner_up(self) -> tuple[HypothesisId, float]:
        ranked = sorted(self.posteriors().items(), key=lambda item: item[1], reverse=True)
        return ranked[1] if len(ranked) > 1 else ("", 0.0)

    def observe(self, probe_id: str, option_id: str) -> None:
        weights = self.evidence.get(probe_id, {}).get(option_id, {})
        for hyp_id, weight in weights.items():
            if hyp_id in self.states:
                self.states[hyp_id].logit += weight

    def supported_by(self, probe_id: str, option_id: str) -> tuple[HypothesisId, ...]:
        """Which hypotheses this answer is positive evidence for.

        Used by the evidence chain; scoring still happens in ``observe``.
        """

        weights = self.evidence.get(probe_id, {}).get(option_id, {})
        return tuple(hyp_id for hyp_id, weight in weights.items() if weight > 0)

    def observe_unknown(self, probe_id: str) -> None:
        """A “不知道” answer is evidence of a missing lower-level concept.

        It must not be treated as a wrong option; it only mildly favours L1.
        """

        del probe_id  # kept for symmetry / future per-probe priors
        for hyp_id, weight in {"H_L2": 0.05, "H_L1": 0.25, "H_L4": 0.05}.items():
            if hyp_id in self.states:
                self.states[hyp_id].logit += weight

    def decide(self, turn: int, max_turns: int) -> DiagnosisDecision:
        top_id, confidence = self.top()
        _, second = self.runner_up()
        margin = confidence - second

        if confidence >= 0.80 and margin >= 0.25:
            return DiagnosisDecision(
                kind="diagnose",
                confidence=confidence,
                runner_up=second,
                reason=f"{top_id} posterior {confidence:.2f}, margin {margin:.2f}",
            )
        if turn >= max_turns:
            if confidence >= 0.55:
                return DiagnosisDecision(
                    kind="diagnose",
                    confidence=confidence,
                    runner_up=second,
                    reason="turn limit reached; report the best hypothesis with missing evidence",
                )
            return DiagnosisDecision(
                kind="stop",
                confidence=confidence,
                runner_up=second,
                reason="turn limit reached below 0.55; do not assert a diagnosis",
            )
        return DiagnosisDecision(
            kind="probe",
            confidence=confidence,
            runner_up=second,
            reason="posterior or margin not high enough",
        )

    def confidence_label(self) -> Literal["high", "medium", "low"]:
        _, confidence = self.top()
        if confidence >= 0.80:
            return "high"
        if confidence >= 0.65:
            return "medium"
        return "low"
