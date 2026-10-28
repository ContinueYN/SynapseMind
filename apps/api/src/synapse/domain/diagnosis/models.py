"""Diagnosis value objects and the L0-L6 taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Layer = Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6"]


@dataclass(frozen=True, slots=True)
class Hypothesis:
    id: str
    label: str
    layer: Layer
    node_id: str
    prior: float


@dataclass(frozen=True, slots=True)
class DiagnosisDecision:
    kind: Literal["probe", "diagnose", "stop"]
    confidence: float
    runner_up: float
    reason: str


@dataclass(frozen=True, slots=True)
class DiagnosisCard:
    version: Literal["0.1"]
    session_id: str
    problem_id: str
    layer: Layer
    label: str
    node_id: str
    one_line: str
    evidence: tuple[str, ...]
    excluded: tuple[str, ...]
    confidence: float
    confidence_label: Literal["high", "medium", "low"]
    next_action: dict[str, object]
    verify: dict[str, object]
    disagree: bool = False

    def confidence_level(self) -> Literal["high", "medium", "low"]:
        if self.confidence >= 0.80:
            return "high"
        if self.confidence >= 0.65:
            return "medium"
        return "low"
