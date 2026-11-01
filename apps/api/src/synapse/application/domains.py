"""The open domain registry and what each verification mode is allowed to claim.

Product boundary (Phase 0): a domain is a **label**, not a route whitelist.
What bounds the product's claims is how a result can be checked:

* ``FORMAL``       — symbolic derivation, counter-examples, boundary checks;
* ``EXECUTABLE``   — run code/tests, reproduce, static analysis;
* ``EMPIRICAL``    — units, magnitudes, consistency, experimental design;
* ``ARGUMENTATIVE``— structure, evidence, reasoning gaps, audience.

The registry is open: ``profile_for()`` returns a registered profile when the
label is known and a generic-mode profile carrying the raw label otherwise.
Nothing here can turn an unknown label into a 422.

The tier a domain gets (``comparison``/``capabilities``) is derived from its
verification mode, not from which plugin happens to exist, so a new domain can
never quietly upgrade its own promise. Two deliberate Phase 0 conservatisms:

* ``EXECUTABLE`` is ``NONE`` until the code sandbox exists (Phase 2): there is
  no way to run the student's code today, and a card based on "we read it"
  would be a false promise. ``EMPIRICAL`` keeps ``PARTIAL`` because unit and
  numeric checks already run.
* ``ARGUMENTATIVE`` is ``NONE``: structure only, never a "correct answer"
  verdict. Decisions (``IntakeFramework.DECISION``) are a sub-mode and are
  explicitly not a request for a single right answer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from synapse.application.domain_detection import (
    MIN_CONFIDENCE,
    DomainDetector,
    HeuristicDomainDetector,
)
from synapse.application.subject import VerifiabilityLevel


class VerificationMode(StrEnum):
    FORMAL = "formal"
    EXECUTABLE = "executable"
    EMPIRICAL = "empirical"
    ARGUMENTATIVE = "argumentative"


class IntakeFramework(StrEnum):
    """Which intake checklist the generic view shows for a domain."""

    FORMAL = "formal"
    EXECUTABLE = "executable"
    EMPIRICAL = "empirical"
    ARGUMENTATIVE = "argumentative"
    DECISION = "decision"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class DomainDescriptor:
    """What the API reports about the resolved label (no graph, no promise)."""

    name: str
    label: str
    verification: VerificationMode
    generic: bool
    confidence: float


@dataclass(frozen=True, slots=True)
class DomainProfile:
    """One registered domain. ``aliases`` are for declared labels only."""

    name: str
    label: str
    verification: VerificationMode
    framework: IntakeFramework
    aliases: tuple[str, ...] = ()

    def describe(self, confidence: float) -> DomainDescriptor:
        return DomainDescriptor(
            name=self.name,
            label=self.label,
            verification=self.verification,
            generic=self.framework is IntakeFramework.GENERIC,
            confidence=max(0.0, min(1.0, confidence)),
        )


GENERIC_PROFILE = DomainProfile(
    name="generic",
    label="通用问题",
    verification=VerificationMode.ARGUMENTATIVE,
    framework=IntakeFramework.GENERIC,
    aliases=("通用", "未知", "unknown", "generic-problem"),
)

# Seeded labels. This tuple is a starting vocabulary, not a whitelist: an
# unlisted label gets a generic-mode profile under its own name.
DEFAULT_PROFILES: tuple[DomainProfile, ...] = (
    DomainProfile(
        name="math",
        label="数学",
        verification=VerificationMode.FORMAL,
        framework=IntakeFramework.FORMAL,
        aliases=("数学", "maths", "mathematics"),
    ),
    DomainProfile(
        name="physics",
        label="物理",
        verification=VerificationMode.EMPIRICAL,
        framework=IntakeFramework.EMPIRICAL,
        aliases=("物理", "phys"),
    ),
    DomainProfile(
        name="chemistry",
        label="化学",
        verification=VerificationMode.EMPIRICAL,
        framework=IntakeFramework.EMPIRICAL,
        aliases=("化学", "chem"),
    ),
    DomainProfile(
        name="biology",
        label="生物",
        verification=VerificationMode.EMPIRICAL,
        framework=IntakeFramework.EMPIRICAL,
        aliases=("生物", "bio"),
    ),
    DomainProfile(
        name="chinese",
        label="语文",
        verification=VerificationMode.ARGUMENTATIVE,
        framework=IntakeFramework.ARGUMENTATIVE,
        aliases=("语文", "中文"),
    ),
    DomainProfile(
        name="writing",
        label="写作",
        verification=VerificationMode.ARGUMENTATIVE,
        framework=IntakeFramework.ARGUMENTATIVE,
        aliases=("写作", "essay", "writing"),
    ),
    DomainProfile(
        name="research",
        label="科研",
        verification=VerificationMode.ARGUMENTATIVE,
        framework=IntakeFramework.ARGUMENTATIVE,
        aliases=("科研", "研究", "论文", "literature"),
    ),
    DomainProfile(
        name="programming",
        label="编程 / 算法",
        verification=VerificationMode.EXECUTABLE,
        framework=IntakeFramework.EXECUTABLE,
        aliases=("编程", "代码", "code", "coding", "算法", "algorithm", "debug", "调试"),
    ),
    DomainProfile(
        name="decision",
        label="生活决策",
        verification=VerificationMode.ARGUMENTATIVE,
        framework=IntakeFramework.DECISION,
        aliases=("决策", "生活决策", "life-decision", "选择", "人生"),
    ),
    DomainProfile(
        name="work",
        label="工作 / 产品",
        verification=VerificationMode.ARGUMENTATIVE,
        framework=IntakeFramework.DECISION,
        aliases=("工作", "职场", "产品", "career", "work"),
    ),
    GENERIC_PROFILE,
)


def normalize_label(label: str) -> str:
    """Stable lookup key: trimmed, lower-cased, spaces/underscores to dashes."""

    return re.sub(r"[\s_]+", "-", label.strip().lower())


class DomainRegistry:
    """Name/alias lookup; unknown labels get a generic-mode profile."""

    def __init__(self, profiles: Iterable[DomainProfile] = DEFAULT_PROFILES) -> None:
        self._profiles = tuple(profiles)
        by_key: dict[str, DomainProfile] = {}
        for profile in self._profiles:
            for key in (profile.name, *profile.aliases):
                by_key.setdefault(normalize_label(key), profile)
        self._by_key = by_key

    @property
    def profiles(self) -> tuple[DomainProfile, ...]:
        return self._profiles

    def find(self, label: str) -> DomainProfile | None:
        if not label.strip():
            return None
        return self._by_key.get(normalize_label(label))

    def profile_for(self, label: str) -> DomainProfile:
        """Registered profile, or a generic-mode profile carrying the label.

        The fallback keeps the caller's own label (``rust``, ``摄影``) instead of
        collapsing it to "generic": the label is the user's vocabulary, and the
        generic behaviour comes from its verification mode, not its name.
        """

        found = self.find(label)
        if found is not None:
            return found
        cleaned = " ".join(label.split()).strip()
        if not cleaned:
            return GENERIC_PROFILE
        return DomainProfile(
            name=normalize_label(cleaned)[:32],
            label=cleaned[:40],
            verification=VerificationMode.ARGUMENTATIVE,
            framework=IntakeFramework.GENERIC,
        )


_MODE_LEVELS: dict[VerificationMode, VerifiabilityLevel] = {
    VerificationMode.FORMAL: VerifiabilityLevel.STRONG,
    VerificationMode.EMPIRICAL: VerifiabilityLevel.PARTIAL,
    # No sandbox yet (Phase 2): a code answer may not be certified from prose.
    VerificationMode.EXECUTABLE: VerifiabilityLevel.NONE,
    VerificationMode.ARGUMENTATIVE: VerifiabilityLevel.NONE,
}


def verifiability_level(mode: VerificationMode) -> VerifiabilityLevel:
    """The promise tier the dialogue may make for this verification mode."""

    return _MODE_LEVELS[mode]


@dataclass(frozen=True, slots=True)
class ResolvedDomain:
    profile: DomainProfile
    confidence: float
    method: str

    @property
    def name(self) -> str:
        return self.profile.name


class DomainResolver:
    """Map a submission to a domain label; it never refuses and never 422s.

    Order: an explicit label (legacy clients, or a user correction), then the
    detector cascade, then the generic profile. Low confidence only means
    "generic + at most one clarifying question"; it does not block the session.
    """

    def __init__(
        self,
        registry: DomainRegistry | None = None,
        detector: DomainDetector | None = None,
        *,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> None:
        self._registry = registry or DomainRegistry()
        self._detector = detector or HeuristicDomainDetector()
        self._min_confidence = min_confidence

    @property
    def registry(self) -> DomainRegistry:
        return self._registry

    def resolve(self, text: str, declared: str | None = None) -> ResolvedDomain:
        if declared is not None and declared.strip():
            return ResolvedDomain(
                profile=self._registry.profile_for(declared),
                confidence=1.0,
                method="declared",
            )
        detected = self._detector.detect(text)
        if detected.domain is not None and detected.confidence >= self._min_confidence:
            return ResolvedDomain(
                profile=self._registry.profile_for(detected.domain),
                confidence=detected.confidence,
                method=detected.method,
            )
        return ResolvedDomain(
            profile=GENERIC_PROFILE,
            confidence=max(0.0, min(1.0, detected.confidence)),
            method=detected.method,
        )
