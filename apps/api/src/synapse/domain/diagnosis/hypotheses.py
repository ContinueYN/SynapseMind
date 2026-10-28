"""Hypothesis scoring.

The state machine decides *which transition*; this module only updates
posteriors from observable probe answers. That separation is deliberate:
an LLM can later propose hypotheses, but it cannot move the dialogue.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
}


@dataclass
class HypothesisState:
    hypothesis: Hypothesis
    logit: float


@dataclass
class HypothesisSet:
    states: dict[HypothesisId, HypothesisState] = field(default_factory=dict)

    @classmethod
    def from_alignment(cls, alignment: AlignmentResult) -> HypothesisSet:
        priors = dict(DEFAULT_PRIORS)
        if alignment.first_divergence == "n3":
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
            prior = priors[hypothesis_id] / total
            states[hypothesis_id] = HypothesisState(
                hypothesis=hypothesis,
                logit=math.log(prior),
            )
        return cls(states=states)

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
        weights = EVIDENCE.get(probe_id, {}).get(option_id, {})
        for hyp_id, weight in weights.items():
            if hyp_id in self.states:
                self.states[hyp_id].logit += weight

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
