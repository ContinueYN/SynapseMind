"""What each verifiability level is allowed to promise (M2.5 S7).

Chapter 13 §13.3 splits subjects into three tiers by whether a machine can
check the student's work:

* **STRONG** (math) — symbolic/numeric checks and counterexamples exist, so the
  product may name the step that was skipped and attach a falsifiable claim;
* **PARTIAL** (physics/chemistry) — units and numeric replay can catch some
  mistakes, so the product may probe and card, but only on structured steps;
* **NONE** (Chinese/English/history) — there is no automatic truth, so the
  product may only show the reference structure and which steps the process
  appears to mention. No probes, no diagnosis card.

This module is the single switch for that promise. It is deliberately a plain
table with no behaviour: ``SessionService`` reads it before asking the planner
for a probe, and skips straight to the structure hint when ``probes`` is false.
Keeping it out of the plugins means a new subject cannot quietly upgrade its own
promise — the tier is declared once, in the plugin, and interpreted here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from synapse.application.subject import VerifiabilityLevel


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What the dialogue may do for a subject at this tier."""

    probes: bool
    diagnosis_card: bool
    structure_hint: bool
    # Shown to the student when the tier limits the conversation; it is also
    # the reason recorded in reports, so it must read like a promise, not a bug.
    note: str


CAPABILITIES: Mapping[VerifiabilityLevel, Capabilities] = {
    VerifiabilityLevel.STRONG: Capabilities(
        probes=True,
        diagnosis_card=True,
        structure_hint=False,
        note="该学科可用符号/数值手段证伪，卡点卡可附具体证据。",
    ),
    VerifiabilityLevel.PARTIAL: Capabilities(
        probes=True,
        diagnosis_card=True,
        structure_hint=False,
        note="该学科只能在校验过的结构化步骤上给出结论，未验证的部分必须标注。",
    ),
    VerifiabilityLevel.NONE: Capabilities(
        probes=False,
        diagnosis_card=False,
        structure_hint=True,
        note=("该学科没有可自动验证的真值：只给结构提示，不追问、不定位卡点、不生成卡点卡。"),
    ),
}


def capabilities_for(level: VerifiabilityLevel) -> Capabilities:
    """Look up the tier; an unknown tier is a coding error, not a fallback."""

    try:
        return CAPABILITIES[level]
    except KeyError as exc:  # pragma: no cover - every tier is enumerated
        raise ValueError(f"unhandled verifiability level: {level!r}") from exc
