"""Golden-case replay against the real state machine.

Chapter 12 §12.3 defines the M2 exit condition as a replayable claim: within
five turns the posterior separates two hypotheses by ``margin >= 0.25`` and the
top-1 layer matches the human label. This module turns that sentence into code.

It drives the same use cases a student drives (no HTTP, no mocks), so the
report measures the shipped path. File loading lives here too because both
``pytest`` and ``scripts/eval/m2_exit.py`` need exactly the same parser.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand
from synapse.application.service import SessionService
from synapse.domain.diagnosis.hypotheses import HYPOTHESES
from synapse.domain.dialogue.states import DialogueState

CATEGORIES = frozenset(
    {"wrong_answer", "right_answer_missing_case", "no_idea", "negative"}
)
# "NONE" labels a case with no gap at all (a complete solution), where a
# cognitive layer would be meaningless.
LAYERS = frozenset({"L1", "L2", "L4", "NONE"})
EXPECTATIONS = frozenset({"diagnose", "stop"})

Expectation = Literal["diagnose", "stop"]


class GoldenCaseError(ValueError):
    """A golden line is malformed; fail loudly instead of skipping it."""


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    category: str
    problem_text: str
    answer: str
    work: str
    label_layer: str
    answers: tuple[str, ...]
    max_turn: int = 5
    expect: Expectation = "diagnose"
    notes: str = ""
    student_id_hash: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> GoldenCase:
        required = (
            "case_id",
            "category",
            "problem_text",
            "answer",
            "label_layer",
            "answers",
        )
        missing = [key for key in required if key not in raw]
        if missing:
            raise GoldenCaseError(f"missing fields: {', '.join(missing)}")

        case_id = _text(raw["case_id"], "case_id")
        category = _text(raw["category"], "category")
        if category not in CATEGORIES:
            raise GoldenCaseError(f"{case_id}: unknown category {category!r}")

        label_layer = _text(raw["label_layer"], "label_layer")
        if label_layer not in LAYERS:
            raise GoldenCaseError(f"{case_id}: unknown layer {label_layer!r}")

        answers = raw["answers"]
        if not isinstance(answers, list) or not answers:
            raise GoldenCaseError(f"{case_id}: answers must be a non-empty list")
        option_ids = tuple(_text(item, "answers[]").upper() for item in answers)
        for option_id in option_ids:
            if option_id not in {"A", "B", "C", "D", "UNKNOWN"}:
                raise GoldenCaseError(f"{case_id}: bad option id {option_id!r}")

        expect = _text(raw.get("expect", "diagnose"), "expect").lower()
        if expect not in EXPECTATIONS:
            raise GoldenCaseError(f"{case_id}: expect must be diagnose|stop")

        max_turn = int(raw.get("max_turn", 5))
        if max_turn < 1 or max_turn > 6:
            raise GoldenCaseError(f"{case_id}: max_turn outside 1..6")

        return cls(
            case_id=case_id,
            category=category,
            problem_text=_text(raw["problem_text"], "problem_text"),
            answer=str(raw["answer"]),
            work=str(raw.get("work", "")),
            label_layer=label_layer,
            answers=option_ids,
            max_turn=max_turn,
            expect="diagnose" if expect == "diagnose" else "stop",
            notes=str(raw.get("notes", "")),
            student_id_hash=str(raw.get("student_id_hash", "")),
        )


@dataclass(frozen=True, slots=True)
class TurnSnapshot:
    """One row of the exit-condition table: ``(turn, top1, margin, kind)``."""

    turn: int
    probe_id: str
    top1: str
    posterior: float
    margin: float
    kind: str
    state: str

    def as_row(self) -> tuple[object, ...]:
        return (
            self.turn,
            self.probe_id,
            self.top1,
            f"{self.posterior:.3f}",
            f"{self.margin:.3f}",
            self.kind,
            self.state,
        )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    case_id: str
    turns: tuple[TurnSnapshot, ...]
    outcome: str
    diagnosis_layer: str | None
    leak_fallbacks: int = 0

    @property
    def last_turn(self) -> int:
        return self.turns[-1].turn if self.turns else 0

    @property
    def final_kind(self) -> str:
        return self.turns[-1].kind if self.turns else "none"


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    reason: str


def load_cases(path: Path) -> tuple[GoldenCase, ...]:
    """Read a JSONL golden file; one case per line, comments not allowed."""
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldenCaseError(f"{path.name}:{number}: {exc}") from exc
        if not isinstance(raw, dict):
            raise GoldenCaseError(f"{path.name}:{number}: expected a JSON object")
        case = GoldenCase.from_mapping(raw)
        if case.case_id in seen:
            raise GoldenCaseError(f"{path.name}:{number}: duplicate {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise GoldenCaseError(f"{path}: no cases")
    return tuple(cases)


def replay_case(service: SessionService, case: GoldenCase) -> ReplayResult:
    """Replay one case answer by answer and return the per-turn posterior trace."""
    view = service.start(
        StartSessionCommand(
            problem_text=case.problem_text,
            answer=case.answer,
            work=case.work,
            self_report="no_idea" if case.category == "no_idea" else None,
        )
    )
    session_id = view.session.session_id
    snapshots: list[TurnSnapshot] = []
    leaks = 0

    for option_id in case.answers:
        if view.prompt is None:
            break
        probe_id = view.session.current_probe_id or ""
        leaks += int(view.prompt.reason_code == "LEAK_FALLBACK")

        view = service.submit(
            session_id,
            SubmitAnswerCommand(answer=option_id, option_id=option_id),
        )
        session = view.session
        top_id, posterior = session.hypotheses.top()
        _, second = session.hypotheses.runner_up()
        decision = session.hypotheses.decide(session.turn, session.max_turns)
        snapshots.append(
            TurnSnapshot(
                turn=session.turn,
                probe_id=probe_id,
                top1=top_id,
                posterior=round(posterior, 4),
                margin=round(posterior - second, 4),
                kind=decision.kind,
                state=session.state.value,
            )
        )
        if view.diagnosis is not None or session.state in {
            DialogueState.STOP,
            DialogueState.CLOSED,
        }:
            break

    if view.diagnosis is not None and snapshots:
        outcome = "diagnose"
        layer: str | None = HYPOTHESES[snapshots[-1].top1].layer
    elif not snapshots and view.prompt is None:
        outcome = "no_gap"
        layer = None
    elif view.session.state in {DialogueState.STOP, DialogueState.CLOSED}:
        outcome = "stop"
        layer = None
    else:
        outcome = "incomplete"
        layer = None

    return ReplayResult(
        case_id=case.case_id,
        turns=tuple(snapshots),
        outcome=outcome,
        diagnosis_layer=layer,
        leak_fallbacks=leaks,
    )


def judge(case: GoldenCase, result: ReplayResult) -> Verdict:
    """Apply chapter 12 §12.3 (plus the negative-case expectation)."""
    if result.leak_fallbacks:
        return Verdict(False, f"leak fallback hit {result.leak_fallbacks}x")
    if result.outcome == "no_gap":
        if case.expect == "stop":
            return Verdict(True, "完整过程：不生成探针，直接收束")
        return Verdict(False, "过程已完整，没有可诊断的断点")
    if case.expect == "stop":
        if result.outcome != "stop":
            return Verdict(False, f"expected a safe stop, got {result.outcome}")
        return Verdict(True, "低置信安全收束：未断言卡点层")
    if result.outcome != "diagnose":
        return Verdict(False, f"expected diagnose, got {result.outcome}")
    if result.last_turn > case.max_turn:
        return Verdict(False, f"diagnosed at turn {result.last_turn} > {case.max_turn}")
    if result.diagnosis_layer != case.label_layer:
        return Verdict(
            False,
            f"top-1 layer {result.diagnosis_layer} != label {case.label_layer}",
        )
    return Verdict(True, f"turn {result.last_turn} 定位到 {case.label_layer}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenCaseError(f"{field} must be a non-empty string")
    return value.strip()