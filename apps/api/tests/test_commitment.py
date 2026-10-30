"""M2.5 S7: the tier decides how much the product may promise.

The table itself is small on purpose. What is worth testing is that the tiers
cannot be conflated: only NONE may produce a structure hint, and NONE may never
probe or produce a card.
"""

from __future__ import annotations

import pytest

from synapse.application.commitment import capabilities_for
from synapse.application.subject import VerifiabilityLevel


def test_strong_tier_probes_and_cards() -> None:
    capabilities = capabilities_for(VerifiabilityLevel.STRONG)

    assert capabilities.probes is True
    assert capabilities.diagnosis_card is True
    assert capabilities.structure_hint is False


def test_partial_tier_keeps_the_probe_and_card_promise() -> None:
    """Physics is not downgraded by S7: it still probes and still cards."""

    capabilities = capabilities_for(VerifiabilityLevel.PARTIAL)

    assert capabilities.probes is True
    assert capabilities.diagnosis_card is True
    assert capabilities.structure_hint is False


def test_none_tier_only_gets_the_structure_hint() -> None:
    capabilities = capabilities_for(VerifiabilityLevel.NONE)

    assert capabilities.probes is False
    assert capabilities.diagnosis_card is False
    assert capabilities.structure_hint is True
    # The note is shown to the student, so it must state the limit, not apologise.
    assert "不定位卡点" in capabilities.note


def test_every_tier_is_enumerated() -> None:
    for level in VerifiabilityLevel:
        assert capabilities_for(level) is not None


def test_an_unknown_tier_is_loud() -> None:
    """No silent fallback: a new tier must be added to the table, not defaulted.

    A ``StrEnum`` value is still a ``str``, so ``"strong"`` resolves; the guard
    is for values that are not a tier at all.
    """

    with pytest.raises(ValueError):
        capabilities_for(object())  # type: ignore[arg-type]
