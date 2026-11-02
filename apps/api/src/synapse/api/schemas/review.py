"""Generic review and review-queue DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from synapse.api.schemas.common import StrictModel


class GenericReviewDomainOut(StrictModel):
    """The open domain label plus what the review could be checked against."""

    name: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=40)
    verification: Literal["formal", "executable", "empirical", "argumentative"]


class GenericFindingOut(StrictModel):
    """One "saw / did not see" item; always tied to evidence in the same review."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=40)
    severity: Literal["blocking", "notable"]
    summary: str = Field(min_length=1, max_length=240)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class GenericEvidenceOut(StrictModel):
    """One source behind a finding; ``ref`` points at the source itself."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    source: Literal["student", "graph", "execution", "knowledge"]
    ref: str = Field(min_length=1, max_length=80)
    excerpt: str | None = Field(default=None, min_length=1, max_length=200)


class ReviewOptionOut(StrictModel):
    """One decision option. The contract has no score, rank or recommendation."""

    label: str = Field(min_length=1, max_length=80)
    costs: list[str] = Field(max_length=6)
    risks: list[str] = Field(max_length=6)
    reversible_test: str = Field(max_length=200)


class ReviewExecutionOut(StrictModel):
    """A code reproduction record from an explicit run. ``skipped`` means nothing ran."""

    status: Literal["pass", "fail", "timeout", "rejected", "skipped"]
    first_failure: str | None = Field(default=None, min_length=1, max_length=300)
    stdout_excerpt: str | None = Field(default=None, max_length=400)
    tests_submitted: bool = False


class GenericReviewOut(StrictModel):
    """Generic review contract v0.1: structure, decision or code reproduction.

    Mirrors ``specs/generic-review.schema.json``. The API attaches it to an
    ``intake`` response or returns it from ``review/run``; it is derived, never
    stored, and never a diagnosis.
    """

    version: Literal["0.1"]
    session_id: str = Field(pattern=r"^S_[A-Za-z0-9_]+$", max_length=40)
    problem_id: str = Field(pattern=r"^P_[A-Za-z0-9_]+$", max_length=48)
    kind: Literal["structure", "decision", "execution"]
    domain: GenericReviewDomainOut
    headline: str = Field(min_length=1, max_length=200)
    findings: list[GenericFindingOut] = Field(max_length=12)
    evidence: list[GenericEvidenceOut] = Field(max_length=24)
    not_checked: list[str] = Field(max_length=8)
    next_step: str = Field(min_length=1, max_length=240)
    disclaimer: str = Field(min_length=1, max_length=300)
    options: list[ReviewOptionOut] | None = Field(
        default=None,
        min_length=2,
        max_length=6,
        exclude_if=lambda value: value is None,
    )
    tradeoff_question: str | None = Field(
        default=None,
        max_length=300,
        exclude_if=lambda value: value is None,
    )
    execution: ReviewExecutionOut | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ReviewRunRequest(StrictModel):
    """Explicit code for one reproduction card; ``tests`` is optional.

    The API never extracts code from the problem or the attempt: the caller must
    paste it. A blank ``tests`` string means "no tests submitted", while blank
    code is a validation error.
    """

    code: str = Field(min_length=1, max_length=20000)
    tests: str = Field(default="", max_length=20000)

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be blank")
        return value

    @field_validator("tests")
    @classmethod
    def blank_tests_mean_not_submitted(cls, value: str) -> str:
        return "" if not value.strip() else value


class ReviewItemOut(StrictModel):
    """One disagreed card, as the internal review page sees it.

    It deliberately carries the card's conclusion and location only: the
    student's own work is not copied into the queue (v0.1,
    ``specs/review-queue.schema.json``).
    """

    session_id: str = Field(pattern=r"^S_[A-Z0-9]+$")
    problem_id: str = Field(pattern=r"^P_[A-Z0-9_]+$")
    layer: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
    label: str = Field(min_length=1, max_length=40)
    node_id: str = Field(pattern=r"^n[0-9]+$")
    one_line: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
    created_at: str = Field(min_length=1, max_length=40)


class ReviewItemsOut(StrictModel):
    version: Literal["0.1"]
    items: list[ReviewItemOut]
