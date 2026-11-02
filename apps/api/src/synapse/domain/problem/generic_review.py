"""The ``GenericReview`` product shape, as pure domain data.

A generic review is the first product the open-domain path can show: a structure
review, a decision frame or a code reproduction card. This module only pins the
shape — who composes it (``application/review/generic.py``, later phases) and how
it is displayed are deliberately out of scope.

Two rules are enforced here rather than left to the composer:

* every finding must cite at least one evidence id that exists in the same
  review; an observation with no evidence belongs in ``not_checked``. JSON
  Schema cannot express a cross-array reference, so the constructor is the
  authority (the published schema documents the rule);
* a decision review needs at least two options, one of them "什么都不做", and an
  ``execution=skipped`` record may not carry output or a failure. These are
  honesty rules: they keep a skipped run from being rendered as a pass and keep
  the decision frame from collapsing into a recommendation.

The model imports nothing from FastAPI, SQLite or the network. It also does not
know about ``GenericGraph``: a composer turns graph nodes into evidence refs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

REVIEW_VERSION = "0.1"

MAX_FINDINGS = 12
MAX_EVIDENCE = 24
MAX_NOT_CHECKED = 8
MAX_OPTIONS = 6
MAX_EVIDENCE_REFS = 8
MAX_BLOCKING_FINDINGS = 3

# A decision frame must always offer the option of not deciding yet.
NO_ACTION_OPTION = "什么都不做"

_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_FINDING_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SESSION_RE = re.compile(r"^S_[A-Za-z0-9_]+$")
_PROBLEM_RE = re.compile(r"^P_[A-Za-z0-9_]+$")


class ReviewKind(StrEnum):
    STRUCTURE = "structure"
    DECISION = "decision"
    EXECUTION = "execution"


class FindingSeverity(StrEnum):
    BLOCKING = "blocking"
    NOTABLE = "notable"


class EvidenceSource(StrEnum):
    STUDENT = "student"
    GRAPH = "graph"
    EXECUTION = "execution"
    KNOWLEDGE = "knowledge"


class ReviewVerification(StrEnum):
    """Mirror of ``VerificationMode``; the domain layer cannot import application."""

    FORMAL = "formal"
    EXECUTABLE = "executable"
    EMPIRICAL = "empirical"
    ARGUMENTATIVE = "argumentative"


class ExecutionStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    SKIPPED = "skipped"


def _text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class ReviewDomain:
    """The open domain label plus what a result can actually be checked against."""

    name: str
    label: str
    verification: ReviewVerification

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "domain name"))
        object.__setattr__(self, "label", _text(self.label, "domain label"))
        object.__setattr__(self, "verification", ReviewVerification(self.verification))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "verification": self.verification.value,
        }


@dataclass(frozen=True, slots=True)
class GenericEvidence:
    """One source behind a finding. ``ref`` points at the source, ``id`` is local."""

    id: str
    source: EvidenceSource
    ref: str
    excerpt: str | None = None

    def __post_init__(self) -> None:
        if not _TOKEN_RE.match(self.id):
            raise ValueError(f"evidence id is not a stable token: {self.id!r}")
        object.__setattr__(self, "source", EvidenceSource(self.source))
        object.__setattr__(self, "ref", _text(self.ref, f"evidence {self.id} ref"))
        if self.excerpt is not None:
            object.__setattr__(self, "excerpt", _text(self.excerpt, f"evidence {self.id} excerpt"))

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "source": self.source.value,
            "ref": self.ref,
        }
        if self.excerpt is not None:
            payload["excerpt"] = self.excerpt
        return payload


@dataclass(frozen=True, slots=True)
class GenericFinding:
    """One thing the review did or did not see, always tied to evidence.

    ``kind`` is an open snake_case label (``missing_evidence``,
    ``option_without_cost``, …), not an enum: later phases add kinds without a
    contract bump, but every kind still needs an evidence ref.
    """

    id: str
    kind: str
    label: str
    severity: FindingSeverity
    summary: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _TOKEN_RE.match(self.id):
            raise ValueError(f"finding id is not a stable token: {self.id!r}")
        if not _FINDING_KIND_RE.match(self.kind):
            raise ValueError(f"finding kind must be a snake_case label: {self.kind!r}")
        object.__setattr__(self, "label", _text(self.label, f"finding {self.id} label"))
        object.__setattr__(self, "severity", FindingSeverity(self.severity))
        object.__setattr__(self, "summary", _text(self.summary, f"finding {self.id} summary"))
        refs = tuple(_text(ref, f"finding {self.id} evidence_ref") for ref in self.evidence_refs)
        if not refs:
            raise ValueError(
                f"finding {self.id} has no evidence_refs; "
                "an observation without evidence belongs in not_checked"
            )
        if len(refs) > MAX_EVIDENCE_REFS:
            raise ValueError(
                f"finding {self.id} has {len(refs)} evidence refs; "
                f"at most {MAX_EVIDENCE_REFS} are allowed"
            )
        if len(set(refs)) != len(refs):
            raise ValueError(f"finding {self.id} repeats an evidence ref")
        object.__setattr__(self, "evidence_refs", refs)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "severity": self.severity.value,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class ReviewOption:
    """One decision option. No score, rank or recommendation field exists."""

    label: str
    costs: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    reversible_test: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _text(self.label, "option label"))
        object.__setattr__(
            self,
            "costs",
            tuple(_text(item, f"option {self.label} cost") for item in self.costs),
        )
        object.__setattr__(
            self,
            "risks",
            tuple(_text(item, f"option {self.label} risk") for item in self.risks),
        )
        object.__setattr__(self, "reversible_test", self.reversible_test.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "costs": list(self.costs),
            "risks": list(self.risks),
            "reversible_test": self.reversible_test,
        }


@dataclass(frozen=True, slots=True)
class ReviewExecution:
    """A code reproduction result. ``skipped``/``rejected`` mean nothing ran."""

    status: ExecutionStatus
    first_failure: str | None = None
    stdout_excerpt: str | None = None
    tests_submitted: bool = False

    def __post_init__(self) -> None:
        status = ExecutionStatus(self.status)
        object.__setattr__(self, "status", status)
        first_failure = None if self.first_failure is None else self.first_failure.strip() or None
        stdout_excerpt = (
            None if self.stdout_excerpt is None else self.stdout_excerpt.strip() or None
        )
        object.__setattr__(self, "first_failure", first_failure)
        object.__setattr__(self, "stdout_excerpt", stdout_excerpt)
        if status is ExecutionStatus.PASS and first_failure is not None:
            raise ValueError("a pass execution cannot carry a first_failure")
        if status in (ExecutionStatus.SKIPPED, ExecutionStatus.REJECTED) and (
            first_failure is not None or stdout_excerpt is not None
        ):
            raise ValueError(
                f"{status} means the code did not run; it cannot carry output or a failure"
            )

    @property
    def ran(self) -> bool:
        """False when no code was executed; callers must not render this as a pass."""

        return self.status not in (ExecutionStatus.SKIPPED, ExecutionStatus.REJECTED)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "tests_submitted": self.tests_submitted,
        }
        if self.first_failure is not None:
            payload["first_failure"] = self.first_failure
        if self.stdout_excerpt is not None:
            payload["stdout_excerpt"] = self.stdout_excerpt
        return payload


@dataclass(frozen=True, slots=True)
class GenericReview:
    """The product shape. Building one is the only way to claim evidence exists."""

    session_id: str
    problem_id: str
    kind: ReviewKind
    domain: ReviewDomain
    headline: str
    next_step: str
    disclaimer: str
    findings: tuple[GenericFinding, ...] = ()
    evidence: tuple[GenericEvidence, ...] = ()
    not_checked: tuple[str, ...] = ()
    options: tuple[ReviewOption, ...] = ()
    tradeoff_question: str | None = None
    execution: ReviewExecution | None = None
    version: str = REVIEW_VERSION

    def __post_init__(self) -> None:
        if self.version != REVIEW_VERSION:
            raise ValueError(f"unsupported generic review version: {self.version!r}")
        if not _SESSION_RE.match(self.session_id):
            raise ValueError(f"invalid session id: {self.session_id!r}")
        if not _PROBLEM_RE.match(self.problem_id):
            raise ValueError(f"invalid problem id: {self.problem_id!r}")
        object.__setattr__(self, "kind", ReviewKind(self.kind))
        object.__setattr__(self, "headline", _text(self.headline, "headline"))
        object.__setattr__(self, "next_step", _text(self.next_step, "next_step"))
        object.__setattr__(self, "disclaimer", _text(self.disclaimer, "disclaimer"))

        evidence = tuple(self.evidence)
        findings = tuple(self.findings)
        not_checked = tuple(_text(item, "not_checked item") for item in self.not_checked)
        options = tuple(self.options)

        if len(findings) > MAX_FINDINGS:
            raise ValueError(f"at most {MAX_FINDINGS} findings; got {len(findings)}")
        if len(evidence) > MAX_EVIDENCE:
            raise ValueError(f"at most {MAX_EVIDENCE} evidence items; got {len(evidence)}")
        if len(not_checked) > MAX_NOT_CHECKED:
            raise ValueError(f"at most {MAX_NOT_CHECKED} not_checked items; got {len(not_checked)}")
        if len(options) > MAX_OPTIONS:
            raise ValueError(f"at most {MAX_OPTIONS} options; got {len(options)}")

        evidence_ids = [item.id for item in evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence ids must be unique inside one review")
        finding_ids = [item.id for item in findings]
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("finding ids must be unique inside one review")

        known = set(evidence_ids)
        for finding in findings:
            missing = [ref for ref in finding.evidence_refs if ref not in known]
            if missing:
                raise ValueError(
                    f"finding {finding.id} cites evidence that is not in this review: "
                    f"{missing}; an observation without evidence belongs in not_checked"
                )

        blocking = [item for item in findings if item.severity is FindingSeverity.BLOCKING]
        if len(blocking) > MAX_BLOCKING_FINDINGS:
            raise ValueError(
                f"at most {MAX_BLOCKING_FINDINGS} blocking findings; got {len(blocking)}"
            )

        if self.kind is ReviewKind.DECISION:
            if len(options) < 2:
                raise ValueError("a decision review needs at least two options")
            if not any(NO_ACTION_OPTION in option.label for option in options):
                raise ValueError(f'a decision review needs an explicit "{NO_ACTION_OPTION}" option')

        if self.tradeoff_question is not None:
            object.__setattr__(
                self, "tradeoff_question", _text(self.tradeoff_question, "tradeoff_question")
            )

        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "not_checked", not_checked)
        object.__setattr__(self, "options", options)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "version": self.version,
            "session_id": self.session_id,
            "problem_id": self.problem_id,
            "kind": self.kind.value,
            "domain": self.domain.to_dict(),
            "headline": self.headline,
            "findings": [finding.to_dict() for finding in self.findings],
            "evidence": [evidence.to_dict() for evidence in self.evidence],
            "not_checked": list(self.not_checked),
            "next_step": self.next_step,
            "disclaimer": self.disclaimer,
        }
        if self.options:
            payload["options"] = [option.to_dict() for option in self.options]
        if self.tradeoff_question is not None:
            payload["tradeoff_question"] = self.tradeoff_question
        if self.execution is not None:
            payload["execution"] = self.execution.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GenericReview:
        """Rebuild a review from the published shape.

        Shape errors surface as ``KeyError``/``TypeError``/``ValueError``; the
        semantic rules (evidence refs, decision options) are checked by
        ``__post_init__`` so both construction paths agree.
        """

        domain = payload["domain"]
        raw_tradeoff = payload.get("tradeoff_question")
        raw_execution = payload.get("execution")
        return cls(
            session_id=str(payload["session_id"]),
            problem_id=str(payload["problem_id"]),
            kind=ReviewKind(payload["kind"]),
            domain=ReviewDomain(
                name=str(domain["name"]),
                label=str(domain["label"]),
                verification=ReviewVerification(domain["verification"]),
            ),
            headline=str(payload["headline"]),
            next_step=str(payload["next_step"]),
            disclaimer=str(payload["disclaimer"]),
            findings=tuple(_finding_from_dict(item) for item in payload.get("findings") or ()),
            evidence=tuple(_evidence_from_dict(item) for item in payload.get("evidence") or ()),
            not_checked=tuple(str(item) for item in payload.get("not_checked") or ()),
            options=tuple(_option_from_dict(item) for item in payload.get("options") or ()),
            tradeoff_question=None if raw_tradeoff is None else str(raw_tradeoff),
            execution=None if raw_execution is None else _execution_from_dict(raw_execution),
            version=str(payload.get("version", REVIEW_VERSION)),
        )


def _evidence_from_dict(payload: Mapping[str, Any]) -> GenericEvidence:
    excerpt = payload.get("excerpt")
    return GenericEvidence(
        id=str(payload["id"]),
        source=EvidenceSource(payload["source"]),
        ref=str(payload["ref"]),
        excerpt=None if excerpt is None else str(excerpt),
    )


def _finding_from_dict(payload: Mapping[str, Any]) -> GenericFinding:
    return GenericFinding(
        id=str(payload["id"]),
        kind=str(payload["kind"]),
        label=str(payload["label"]),
        severity=FindingSeverity(payload["severity"]),
        summary=str(payload["summary"]),
        evidence_refs=tuple(str(ref) for ref in payload["evidence_refs"]),
    )


def _option_from_dict(payload: Mapping[str, Any]) -> ReviewOption:
    return ReviewOption(
        label=str(payload["label"]),
        costs=tuple(str(item) for item in payload["costs"]),
        risks=tuple(str(item) for item in payload["risks"]),
        reversible_test=str(payload["reversible_test"]),
    )


def _execution_from_dict(payload: Mapping[str, Any]) -> ReviewExecution:
    first_failure = payload.get("first_failure")
    stdout_excerpt = payload.get("stdout_excerpt")
    return ReviewExecution(
        status=ExecutionStatus(payload["status"]),
        first_failure=None if first_failure is None else str(first_failure),
        stdout_excerpt=None if stdout_excerpt is None else str(stdout_excerpt),
        tests_submitted=bool(payload.get("tests_submitted", False)),
    )
