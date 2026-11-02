"""Open domain registry, resolver and the promise each mode allows.

The important properties here are negative ones: an unknown label never raises,
a low-confidence detection keeps the generic profile, and the tier comes from
the verification mode rather than from a plugin's existence.
"""

from __future__ import annotations

import pytest

from synapse.application.diagnosis.domain_detection import DetectedDomain
from synapse.application.diagnosis.domains import (
    DEFAULT_PROFILES,
    GENERIC_PROFILE,
    DomainProfile,
    DomainRegistry,
    DomainResolver,
    IntakeFramework,
    VerificationMode,
    normalize_label,
    verifiability_level,
)
from synapse.application.diagnosis.intake import build_domain_intake
from synapse.application.shared.subject import VerifiabilityLevel
from synapse.domain.problem.models import Problem, SolutionGraph

MATH = "已知函数 f(x)=x^2-a x+1，对任意 x∈R 有 f(x)>0，求 a 的取值范围。"
CODE = "我的 Python 脚本报错了：IndexError: list index out of range。"


class _Detector:
    def __init__(self, result: DetectedDomain) -> None:
        self.result = result
        self.calls = 0

    def detect(self, text: str) -> DetectedDomain:
        del text
        self.calls += 1
        return self.result


def _reference_free(subject: str, confidence: float, method: str) -> Problem:
    return Problem(
        id="P_GEN_REFERENCE_FREE",
        title="测试入口",
        text="我最近很烦，不知道该怎么办。",
        graph=SolutionGraph(
            problem_id="P_GEN_REFERENCE_FREE",
            version="g0",
            stem="我最近很烦，不知道该怎么办。",
            nodes=(),
            edges=(),
        ),
        subject=subject,
        annotated=False,
        domain_confidence=confidence,
        domain_method=method,
    )


def test_the_default_registry_keeps_the_three_classic_domains() -> None:
    registry = DomainRegistry()

    assert registry.find("math") is not None
    assert registry.profile_for("数学").name == "math"
    assert registry.profile_for("physics").name == "physics"
    assert registry.profile_for("chinese").name == "chinese"


def test_aliases_are_case_and_space_insensitive() -> None:
    registry = DomainRegistry()

    assert registry.profile_for(" Life Decision ").name == "decision"
    assert registry.profile_for("ALGORITHM").name == "programming"
    assert registry.profile_for("写作").name == "writing"


def test_an_unknown_label_keeps_its_own_name_in_generic_mode() -> None:
    profile = DomainRegistry().profile_for("Rust")

    assert profile.name == "rust"
    assert profile.label == "Rust"
    assert profile.framework is IntakeFramework.GENERIC
    assert profile.verification is VerificationMode.ARGUMENTATIVE


def test_an_empty_label_falls_back_to_the_shared_generic_profile() -> None:
    assert DomainRegistry().profile_for("   ") is GENERIC_PROFILE


def test_a_declared_unregistered_label_keeps_its_name_in_generic_mode() -> None:
    result = DomainResolver().resolve(CODE, "rust")

    assert result.name == "rust"
    assert result.profile.label == "rust"
    assert result.profile.framework is IntakeFramework.GENERIC
    assert result.method == "declared"


def test_declared_label_wins_and_is_recorded_as_declared() -> None:
    resolver = DomainResolver()
    result = resolver.resolve(CODE, "decision")

    assert result.name == "decision"
    assert result.method == "declared"
    assert result.confidence == 1.0


def test_low_confidence_keeps_the_generic_profile_instead_of_refusing() -> None:
    detector = _Detector(DetectedDomain(None, 0.2, "heuristic"))
    result = DomainResolver(detector=detector).resolve("嗯。")

    assert result.profile is GENERIC_PROFILE
    assert result.confidence == pytest.approx(0.2)
    assert result.method == "heuristic"


def test_a_confident_detection_maps_to_its_registered_profile() -> None:
    detector = _Detector(DetectedDomain("programming", 0.9, "model"))
    result = DomainResolver(detector=detector).resolve(CODE)

    assert result.profile.name == "programming"
    assert result.method == "model"
    assert result.profile.verification is VerificationMode.EXECUTABLE


def test_verification_mode_decides_the_promise_tier() -> None:
    assert verifiability_level(VerificationMode.FORMAL) is VerifiabilityLevel.STRONG
    assert verifiability_level(VerificationMode.EMPIRICAL) is VerifiabilityLevel.PARTIAL
    # No sandbox yet: code may not be certified from prose.
    assert verifiability_level(VerificationMode.EXECUTABLE) is VerifiabilityLevel.NONE
    assert verifiability_level(VerificationMode.ARGUMENTATIVE) is VerifiabilityLevel.NONE


def test_every_default_profile_can_describe_itself() -> None:
    for profile in DEFAULT_PROFILES:
        descriptor = profile.describe(0.75)
        assert descriptor.name
        assert descriptor.label
        assert 0.0 <= descriptor.confidence <= 1.0


def test_the_intake_asks_at_most_one_clarifying_question() -> None:
    low = _reference_free("generic", 0.0, "none")
    high = _reference_free("programming", 0.9, "heuristic")

    low_intake = build_domain_intake(low, GENERIC_PROFILE)
    code_intake = build_domain_intake(high, DomainRegistry().profile_for("programming"))

    assert low_intake.clarifier is not None
    assert low_intake.clarifier.count("？") == 1
    assert code_intake.clarifier is None


def test_the_intake_follows_the_verification_mode() -> None:
    registry = DomainRegistry()
    decision = build_domain_intake(
        _reference_free("decision", 0.8, "heuristic"),
        registry.profile_for("decision"),
    )
    code = build_domain_intake(
        _reference_free("programming", 0.8, "heuristic"),
        registry.profile_for("programming"),
    )

    assert any("取舍" in item or "可逆实验" in item for item in decision.checklist)
    assert any("复现" in item for item in code.checklist)
    assert "唯一正确答案" in decision.disclaimer
    assert "未执行" in code.disclaimer
    # Never a diagnosis: the intake has no card, no step verdict and no answer.
    assert "卡点卡" not in decision.one_line + decision.disclaimer
    assert not hasattr(decision, "diagnosis")


def test_normalize_label_keeps_chinese_labels_distinguishable() -> None:
    assert normalize_label(" Life  Decision ") == "life-decision"
    assert normalize_label("生活决策") == "生活决策"
    assert normalize_label("生活决策") != normalize_label("决策")


def test_a_profile_without_aliases_still_resolves_by_name() -> None:
    profile = DomainProfile(
        name="garden",
        label="园艺",
        verification=VerificationMode.EMPIRICAL,
        framework=IntakeFramework.EMPIRICAL,
    )
    registry = DomainRegistry((profile,))

    assert registry.profile_for("gardening").name == "gardening"
    assert registry.profile_for("garden").name == "garden"
