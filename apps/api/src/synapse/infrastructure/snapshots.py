"""Versioned JSON snapshots for the session aggregate and generated problems.

This is an internal storage format, not a public contract: API shapes still live
in ``specs/``. The snapshot is explicit rather than ``pickle`` so a corrupt or
old row fails with a readable error instead of being silently misread.

Only the SQLite adapters and the explicit maintenance command import this
module. The domain and application layers never see JSON.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, cast

from synapse.domain.diagnosis.hypotheses import (
    EvidenceWeights,
    HypothesisSet,
    HypothesisState,
)
from synapse.domain.diagnosis.models import (
    Attribution,
    AttributionDimension,
    DiagnosisCard,
    Hypothesis,
    Layer,
)
from synapse.domain.diagnosis.work import FindingKind, WorkFinding
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.evidence.models import Evidence, EvidenceChain, EvidenceSource
from synapse.domain.problem.models import (
    AlignmentResult,
    Interval,
    Probe,
    Problem,
    SolutionGraph,
    SolutionNode,
    VerificationClaim,
)

SNAPSHOT_VERSION = "0.2"
# Versions that have a registered, explicit migration. Adding a version here
# without adding the matching branch in ``migrate_snapshot`` is a bug.
MIGRATABLE_VERSIONS = frozenset({"0.1"})
MIGRATION_COMMAND = "python scripts/dev/session_store.py --db <path>"
KIND_SESSION = "session"
KIND_PROBLEM = "problem"

_LAYERS = frozenset({"L0", "L1", "L2", "L3", "L4", "L5", "L6"})
_CONFIDENCE_LABELS = frozenset({"high", "medium", "low"})
_FINDING_KINDS = frozenset({"identity", "limit", "quantity"})
_EVIDENCE_SOURCES = frozenset({"alignment", "probe", "self_report"})


class SnapshotError(ValueError):
    """The row exists but cannot be read as the current snapshot version."""


class SnapshotVersionError(SnapshotError):
    """The JSON is readable, but its format version is not current.

    The API never guesses at an older shape and never upgrades a row as a side
    effect of reading it. The message names the explicit migration command;
    ``migratable`` tells the CLI whether a registered path exists.
    """

    def __init__(
        self,
        message: str,
        *,
        version: str,
        kind: str,
        migratable: bool,
    ) -> None:
        super().__init__(message)
        self.version = version
        self.kind = kind
        self.migratable = migratable


def _version_message(version: str, kind: str) -> str:
    if version in MIGRATABLE_VERSIONS:
        return (
            f"{kind} snapshot version {version!r} is older than {SNAPSHOT_VERSION!r}; "
            f"run `{MIGRATION_COMMAND} migrate --apply` before starting the API. "
            "The old snapshot is not read silently."
        )
    return (
        f"{kind} snapshot version {version!r} is not supported "
        f"(expected {SNAPSHOT_VERSION!r}); no migration is registered. "
        f"Back up the database and inspect it with `{MIGRATION_COMMAND} stats`."
    )


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SnapshotError(f"{where}: expected an object")
    return {str(key): item for key, item in value.items()}


def _array(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise SnapshotError(f"{where}: expected an array")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise SnapshotError(f"{where}: expected a string")
    return value


def _optional_text(value: object, where: str) -> str | None:
    if value is None:
        return None
    return _text(value, where)


def _integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"{where}: expected an integer")
    return value


def _revision(value: object, where: str) -> int:
    revision = _integer(value, where)
    if revision < 0:
        raise SnapshotError(f"{where}: expected a non-negative integer")
    return revision


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnapshotError(f"{where}: expected a number")
    return float(value)


def _flag(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise SnapshotError(f"{where}: expected a boolean")
    return value


def _text_tuple(value: object, where: str) -> tuple[str, ...]:
    return tuple(
        _text(item, f"{where}[{index}]") for index, item in enumerate(_array(value, where))
    )


def _layer(value: object, where: str) -> Layer:
    text = _text(value, where)
    if text not in _LAYERS:
        raise SnapshotError(f"{where}: unknown layer {text!r}")
    return cast(Layer, text)


def _confidence_label(value: object, where: str) -> Literal["high", "medium", "low"]:
    text = _text(value, where)
    if text not in _CONFIDENCE_LABELS:
        raise SnapshotError(f"{where}: unknown confidence label {text!r}")
    return cast(Literal["high", "medium", "low"], text)


def _finding_kind(value: object, where: str) -> FindingKind:
    text = _text(value, where)
    if text not in _FINDING_KINDS:
        raise SnapshotError(f"{where}: unknown finding kind {text!r}")
    return cast(FindingKind, text)


def _evidence_source(value: object, where: str) -> EvidenceSource:
    text = _text(value, where)
    if text not in _EVIDENCE_SOURCES:
        raise SnapshotError(f"{where}: unknown evidence source {text!r}")
    return cast(EvidenceSource, text)


def _state(value: object, where: str) -> DialogueState:
    text = _text(value, where)
    try:
        return DialogueState(text)
    except ValueError as exc:
        raise SnapshotError(f"{where}: unknown dialogue state {text!r}") from exc


def _datetime(value: object, where: str) -> datetime:
    text = _text(value, where)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SnapshotError(f"{where}: not an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise SnapshotError(f"{where}: datetime must carry a timezone")
    return parsed


def _header(snapshot: object, kind: str) -> dict[str, object]:
    root = _object(snapshot, "snapshot")
    version = _text(root.get("version"), "snapshot.version")
    if version != SNAPSHOT_VERSION:
        raise SnapshotVersionError(
            _version_message(version, kind),
            version=version,
            kind=kind,
            migratable=version in MIGRATABLE_VERSIONS,
        )
    actual = _text(root.get("kind"), "snapshot.kind")
    if actual != kind:
        raise SnapshotError(f"snapshot kind {actual!r} is not {kind!r}")
    return _object(root.get("data"), "snapshot.data")


# --- session -----------------------------------------------------------------


def _alignment_to_json(alignment: AlignmentResult) -> dict[str, object]:
    return {
        "first_divergence": alignment.first_divergence,
        "matched_node_ids": list(alignment.matched_node_ids),
        "missing_node_ids": list(alignment.missing_node_ids),
        "evidence": list(alignment.evidence),
        "excluded": list(alignment.excluded),
        "partial_node_ids": list(alignment.partial_node_ids),
    }


def _alignment_from_json(value: object, where: str) -> AlignmentResult:
    data = _object(value, where)
    return AlignmentResult(
        first_divergence=_text(data.get("first_divergence"), f"{where}.first_divergence"),
        matched_node_ids=_text_tuple(data.get("matched_node_ids"), f"{where}.matched_node_ids"),
        missing_node_ids=_text_tuple(data.get("missing_node_ids"), f"{where}.missing_node_ids"),
        evidence=_text_tuple(data.get("evidence"), f"{where}.evidence"),
        excluded=_text_tuple(data.get("excluded"), f"{where}.excluded"),
        partial_node_ids=_text_tuple(data.get("partial_node_ids"), f"{where}.partial_node_ids"),
    )


def _hypothesis_to_json(hypothesis: Hypothesis) -> dict[str, object]:
    return {
        "id": hypothesis.id,
        "label": hypothesis.label,
        "layer": hypothesis.layer,
        "node_id": hypothesis.node_id,
        "prior": hypothesis.prior,
    }


def _hypothesis_from_json(value: object, where: str) -> Hypothesis:
    data = _object(value, where)
    return Hypothesis(
        id=_text(data.get("id"), f"{where}.id"),
        label=_text(data.get("label"), f"{where}.label"),
        layer=_layer(data.get("layer"), f"{where}.layer"),
        node_id=_text(data.get("node_id"), f"{where}.node_id"),
        prior=_number(data.get("prior"), f"{where}.prior"),
    )


def _weights_to_json(weights: EvidenceWeights) -> dict[str, object]:
    return {
        probe_id: {
            option_id: {
                hypothesis_id: float(weight) for hypothesis_id, weight in per_hypothesis.items()
            }
            for option_id, per_hypothesis in per_option.items()
        }
        for probe_id, per_option in weights.items()
    }


def _weights_from_json(value: object, where: str) -> dict[str, dict[str, dict[str, float]]]:
    weights: dict[str, dict[str, dict[str, float]]] = {}
    for probe_id, per_option in _object(value, where).items():
        options: dict[str, dict[str, float]] = {}
        for option_id, per_hypothesis in _object(per_option, f"{where}.{probe_id}").items():
            options[option_id] = {
                hypothesis_id: _number(weight, f"{where}.{probe_id}.{option_id}")
                for hypothesis_id, weight in _object(
                    per_hypothesis, f"{where}.{probe_id}.{option_id}"
                ).items()
            }
        weights[probe_id] = options
    return weights


def _hypotheses_to_json(hypotheses: HypothesisSet) -> dict[str, object]:
    return {
        "states": {
            hypothesis_id: {
                "hypothesis": _hypothesis_to_json(state.hypothesis),
                "logit": state.logit,
            }
            for hypothesis_id, state in sorted(hypotheses.states.items())
        },
        "evidence": _weights_to_json(hypotheses.evidence),
    }


def _hypotheses_from_json(value: object, where: str) -> HypothesisSet:
    data = _object(value, where)
    states: dict[str, HypothesisState] = {}
    for hypothesis_id, raw_state in _object(data.get("states"), f"{where}.states").items():
        state = _object(raw_state, f"{where}.states.{hypothesis_id}")
        states[hypothesis_id] = HypothesisState(
            hypothesis=_hypothesis_from_json(
                state.get("hypothesis"), f"{where}.states.{hypothesis_id}.hypothesis"
            ),
            logit=_number(state.get("logit"), f"{where}.states.{hypothesis_id}.logit"),
        )
    return HypothesisSet(
        states=states,
        evidence=_weights_from_json(data.get("evidence"), f"{where}.evidence"),
    )


def _card_to_json(card: DiagnosisCard) -> dict[str, object]:
    data: dict[str, object] = {
        "version": card.version,
        "session_id": card.session_id,
        "problem_id": card.problem_id,
        "layer": card.layer,
        "label": card.label,
        "node_id": card.node_id,
        "one_line": card.one_line,
        "evidence": list(card.evidence),
        "excluded": list(card.excluded),
        "confidence": card.confidence,
        "confidence_label": card.confidence_label,
        "next_action": dict(card.next_action),
        "verify": dict(card.verify),
        "disagree": card.disagree,
    }
    if card.attribution is not None:
        data["attribution"] = {
            "dimensions": [
                {
                    "key": dimension.key,
                    "label": dimension.label,
                    "weight": dimension.weight,
                }
                for dimension in card.attribution.dimensions
            ],
            "note": card.attribution.note,
        }
    return data


def _attribution_from_json(value: object, where: str) -> Attribution:
    data = _object(value, where)
    raw_dimensions = _array(data.get("dimensions"), f"{where}.dimensions")
    if not 1 <= len(raw_dimensions) <= 2:
        raise SnapshotError(f"{where}.dimensions: expected 1 or 2 items")
    dimensions = tuple(
        AttributionDimension(
            key=_text(item.get("key"), f"{where}.dimensions[{index}].key"),
            label=_text(item.get("label"), f"{where}.dimensions[{index}].label"),
            weight=_number(item.get("weight"), f"{where}.dimensions[{index}].weight"),
        )
        for index, raw in enumerate(raw_dimensions)
        for item in (_object(raw, f"{where}.dimensions[{index}]"),)
    )
    return Attribution(
        dimensions=dimensions,
        note=_text(data.get("note"), f"{where}.note"),
    )


def _card_from_json(value: object, where: str) -> DiagnosisCard:
    data = _object(value, where)
    version = _text(data.get("version"), f"{where}.version")
    if version not in {"0.1", "0.2"}:
        raise SnapshotError(f"{where}.version: unsupported card version {version!r}")
    attribution = (
        None
        if data.get("attribution") is None
        else _attribution_from_json(data["attribution"], f"{where}.attribution")
    )
    if version == "0.2" and attribution is None:
        raise SnapshotError(f"{where}: version 0.2 requires attribution")
    return DiagnosisCard(
        version=cast(Literal["0.1", "0.2"], version),
        session_id=_text(data.get("session_id"), f"{where}.session_id"),
        problem_id=_text(data.get("problem_id"), f"{where}.problem_id"),
        layer=_layer(data.get("layer"), f"{where}.layer"),
        label=_text(data.get("label"), f"{where}.label"),
        node_id=_text(data.get("node_id"), f"{where}.node_id"),
        one_line=_text(data.get("one_line"), f"{where}.one_line"),
        evidence=_text_tuple(data.get("evidence"), f"{where}.evidence"),
        excluded=_text_tuple(data.get("excluded"), f"{where}.excluded"),
        confidence=_number(data.get("confidence"), f"{where}.confidence"),
        confidence_label=_confidence_label(
            data.get("confidence_label"), f"{where}.confidence_label"
        ),
        next_action=_object(data.get("next_action"), f"{where}.next_action"),
        verify=_object(data.get("verify"), f"{where}.verify"),
        disagree=_flag(data.get("disagree"), f"{where}.disagree"),
        attribution=attribution,
    )


def _turn_to_json(turn: TurnRecord) -> dict[str, object]:
    return {
        "turn": turn.turn,
        "probe_id": turn.probe_id,
        "question": turn.question,
        "answer": turn.answer,
        "option_id": turn.option_id,
        "action": turn.action,
        "is_unknown": turn.is_unknown,
    }


def _turn_from_json(value: object, where: str) -> TurnRecord:
    data = _object(value, where)
    return TurnRecord(
        turn=_integer(data.get("turn"), f"{where}.turn"),
        probe_id=_text(data.get("probe_id"), f"{where}.probe_id"),
        question=_text(data.get("question"), f"{where}.question"),
        answer=_text(data.get("answer"), f"{where}.answer"),
        option_id=_optional_text(data.get("option_id"), f"{where}.option_id"),
        action=_text(data.get("action"), f"{where}.action"),
        is_unknown=_flag(data.get("is_unknown"), f"{where}.is_unknown"),
    )


def _evidence_to_json(item: Evidence) -> dict[str, object]:
    return {
        "id": item.id,
        "source": item.source,
        "claim": item.claim,
        "supports": list(item.supports),
        "turn": item.turn,
    }


def _evidence_from_json(value: object, where: str) -> Evidence:
    data = _object(value, where)
    turn = data.get("turn")
    return Evidence(
        id=_text(data.get("id"), f"{where}.id"),
        source=_evidence_source(data.get("source"), f"{where}.source"),
        claim=_text(data.get("claim"), f"{where}.claim"),
        supports=_text_tuple(data.get("supports"), f"{where}.supports"),
        turn=None if turn is None else _integer(turn, f"{where}.turn"),
    )


def _work_finding_to_json(finding: WorkFinding) -> dict[str, object]:
    return {
        "kind": finding.kind,
        "left": finding.left,
        "right": finding.right,
        "detail": finding.detail,
        "counterexample": finding.counterexample,
        "summary": finding.summary,
    }


def _work_finding_from_json(value: object, where: str) -> WorkFinding:
    data = _object(value, where)
    return WorkFinding(
        kind=_finding_kind(data.get("kind"), f"{where}.kind"),
        left=_text(data.get("left"), f"{where}.left"),
        right=_text(data.get("right"), f"{where}.right"),
        detail=_text(data.get("detail"), f"{where}.detail"),
        counterexample=_text(data.get("counterexample"), f"{where}.counterexample"),
        summary=_text(data.get("summary"), f"{where}.summary"),
    )


def encode_session(
    session: DialogueSession,
    *,
    revision: int | None = None,
) -> dict[str, object]:
    # ``revision`` is injected by the SQLite adapter so the snapshot carries
    # the value the row is about to have, without mutating the aggregate
    # before the compare-and-swap succeeds.
    stored_revision = session.revision if revision is None else revision
    return {
        "version": SNAPSHOT_VERSION,
        "kind": KIND_SESSION,
        "data": {
            "session_id": session.session_id,
            "problem_id": session.problem_id,
            "state": session.state.value,
            "revision": stored_revision,
            "alignment": _alignment_to_json(session.alignment),
            "hypotheses": _hypotheses_to_json(session.hypotheses),
            "max_turns": session.max_turns,
            "created_at": session.created_at.isoformat(),
            "mode": session.mode,
            "turn": session.turn,
            "asked_probe_ids": list(session.asked_probe_ids),
            "history": [_turn_to_json(turn) for turn in session.history],
            "evidence": {"items": [_evidence_to_json(item) for item in session.evidence.items]},
            "diagnosis": None if session.diagnosis is None else _card_to_json(session.diagnosis),
            "work_findings": [_work_finding_to_json(finding) for finding in session.work_findings],
            "scaffold_level": session.scaffold_level,
            "scaffold_work": session.scaffold_work,
        },
    }


def decode_session(snapshot: object) -> DialogueSession:
    data = _header(snapshot, KIND_SESSION)
    diagnosis = data.get("diagnosis")
    return DialogueSession(
        session_id=_text(data.get("session_id"), "session.session_id"),
        problem_id=_text(data.get("problem_id"), "session.problem_id"),
        state=_state(data.get("state"), "session.state"),
        alignment=_alignment_from_json(data.get("alignment"), "session.alignment"),
        hypotheses=_hypotheses_from_json(data.get("hypotheses"), "session.hypotheses"),
        max_turns=_integer(data.get("max_turns"), "session.max_turns"),
        created_at=_datetime(data.get("created_at"), "session.created_at"),
        mode=_text(data.get("mode"), "session.mode"),
        turn=_integer(data.get("turn"), "session.turn"),
        asked_probe_ids=list(_text_tuple(data.get("asked_probe_ids"), "session.asked_probe_ids")),
        history=[
            _turn_from_json(item, f"session.history[{index}]")
            for index, item in enumerate(_array(data.get("history"), "session.history"))
        ],
        evidence=EvidenceChain(
            items=[
                _evidence_from_json(item, f"session.evidence[{index}]")
                for index, item in enumerate(
                    _array(
                        _object(data.get("evidence"), "session.evidence").get("items"),
                        "session.evidence.items",
                    )
                )
            ]
        ),
        diagnosis=None if diagnosis is None else _card_from_json(diagnosis, "session.diagnosis"),
        work_findings=tuple(
            _work_finding_from_json(item, f"session.work_findings[{index}]")
            for index, item in enumerate(_array(data.get("work_findings"), "session.work_findings"))
        ),
        scaffold_level=_integer(data.get("scaffold_level", 0), "session.scaffold_level"),
        scaffold_work=_text(data.get("scaffold_work", ""), "session.scaffold_work"),
        revision=_revision(data.get("revision"), "session.revision"),
    )


def migrate_snapshot(snapshot: object) -> dict[str, object]:
    """Return a current-version copy of one stored snapshot.

    This is the only place a legacy shape is understood. Callers must run it
    deliberately (the maintenance command), never from ``get()``: a read that
    silently upgrades a row would hide an incomplete deployment.
    """

    root = _object(snapshot, "snapshot")
    version = _text(root.get("version"), "snapshot.version")
    kind = _text(root.get("kind"), "snapshot.kind")
    if version == SNAPSHOT_VERSION:
        # Validate the current shape too, so ``migrate`` fails the whole batch
        # on a corrupt row instead of reporting "nothing to do".
        if kind == KIND_SESSION:
            decode_session(root)
        elif kind == KIND_PROBLEM:
            decode_problem(root)
        else:
            raise SnapshotError(f"snapshot kind {kind!r} is not supported")
        return root
    if version not in MIGRATABLE_VERSIONS:
        raise SnapshotVersionError(
            _version_message(version, kind),
            version=version,
            kind=kind,
            migratable=False,
        )

    migrated = copy.deepcopy(root)
    migrated["version"] = SNAPSHOT_VERSION
    data = _object(migrated.get("data"), "snapshot.data")
    migrated["data"] = data
    if kind == KIND_SESSION:
        # 0.1 stored no revision: the row's separate column was the only
        # token. A migrated session starts at revision 0, matching the
        # column's default; the CLI also rewrites the column to this value.
        data["revision"] = _revision(data.get("revision", 0), "snapshot.data.revision")
        decode_session(migrated)
    elif kind == KIND_PROBLEM:
        decode_problem(migrated)
    else:
        raise SnapshotError(f"snapshot kind {kind!r} has no migration path")
    return migrated


# --- problem -----------------------------------------------------------------


def _probe_evidence_to_json(
    evidence: Mapping[str, Mapping[str, float]],
) -> dict[str, object]:
    return {
        option_id: {
            hypothesis_id: float(weight) for hypothesis_id, weight in per_hypothesis.items()
        }
        for option_id, per_hypothesis in evidence.items()
    }


def _probe_evidence_from_json(value: object, where: str) -> dict[str, dict[str, float]]:
    evidence: dict[str, dict[str, float]] = {}
    for option_id, per_hypothesis in _object(value, where).items():
        evidence[option_id] = {
            hypothesis_id: _number(weight, f"{where}.{option_id}")
            for hypothesis_id, weight in _object(per_hypothesis, f"{where}.{option_id}").items()
        }
    return evidence


def _probe_to_json(probe: Probe) -> dict[str, object]:
    return {
        "id": probe.id,
        "question": probe.question,
        "options": list(probe.options),
        "targets": list(probe.targets),
        "hint_level": probe.hint_level,
        "evidence": _probe_evidence_to_json(probe.evidence),
        "correct_option": probe.correct_option,
    }


def _probe_from_json(value: object, where: str) -> Probe:
    data = _object(value, where)
    return Probe(
        id=_text(data.get("id"), f"{where}.id"),
        question=_text(data.get("question"), f"{where}.question"),
        options=_text_tuple(data.get("options"), f"{where}.options"),
        targets=_text_tuple(data.get("targets"), f"{where}.targets"),
        hint_level=_integer(data.get("hint_level"), f"{where}.hint_level"),
        evidence=_probe_evidence_from_json(data.get("evidence"), f"{where}.evidence"),
        correct_option=_optional_text(data.get("correct_option"), f"{where}.correct_option"),
    )


def _node_to_json(node: SolutionNode) -> dict[str, object]:
    return {
        "id": node.id,
        "type": node.type,
        "text": node.text,
        "demand": {key: float(value) for key, value in node.demand.items()},
        "common_errors": list(node.common_errors),
        "probes": [_probe_to_json(probe) for probe in node.probes],
    }


def _node_from_json(value: object, where: str) -> SolutionNode:
    data = _object(value, where)
    demand = {
        key: _number(item, f"{where}.demand.{key}")
        for key, item in _object(data.get("demand"), f"{where}.demand").items()
    }
    return SolutionNode(
        id=_text(data.get("id"), f"{where}.id"),
        type=_text(data.get("type"), f"{where}.type"),
        text=_text(data.get("text"), f"{where}.text"),
        demand=demand,
        common_errors=_text_tuple(data.get("common_errors"), f"{where}.common_errors"),
        probes=tuple(
            _probe_from_json(item, f"{where}.probes[{index}]")
            for index, item in enumerate(_array(data.get("probes"), f"{where}.probes"))
        ),
    )


def _interval_to_json(interval: Interval) -> dict[str, object]:
    return {
        "lower": interval.lower,
        "upper": interval.upper,
        "lower_inclusive": interval.lower_inclusive,
        "upper_inclusive": interval.upper_inclusive,
    }


def _interval_from_json(value: object, where: str) -> Interval:
    data = _object(value, where)
    return Interval(
        lower=_optional_text(data.get("lower"), f"{where}.lower"),
        upper=_optional_text(data.get("upper"), f"{where}.upper"),
        lower_inclusive=_flag(data.get("lower_inclusive"), f"{where}.lower_inclusive"),
        upper_inclusive=_flag(data.get("upper_inclusive"), f"{where}.upper_inclusive"),
    )


def _claim_to_json(claim: VerificationClaim) -> dict[str, object]:
    return {
        "kind": claim.kind,
        "parameter": claim.parameter,
        "variable": claim.variable,
        "variable_domain": claim.variable_domain,
        "expression": claim.expression,
        "relation": claim.relation,
        "intervals": [_interval_to_json(interval) for interval in claim.intervals],
    }


def _claim_from_json(value: object, where: str) -> VerificationClaim:
    data = _object(value, where)
    return VerificationClaim(
        kind=_text(data.get("kind"), f"{where}.kind"),
        parameter=_text(data.get("parameter"), f"{where}.parameter"),
        variable=_text(data.get("variable"), f"{where}.variable"),
        variable_domain=_text(data.get("variable_domain"), f"{where}.variable_domain"),
        expression=_text(data.get("expression"), f"{where}.expression"),
        relation=_text(data.get("relation"), f"{where}.relation"),
        intervals=tuple(
            _interval_from_json(item, f"{where}.intervals[{index}]")
            for index, item in enumerate(_array(data.get("intervals"), f"{where}.intervals"))
        ),
    )


def _graph_to_json(graph: SolutionGraph) -> dict[str, object]:
    return {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "stem": graph.stem,
        "nodes": [_node_to_json(node) for node in graph.nodes],
        "edges": [list(edge) for edge in graph.edges],
        "claim": None if graph.claim is None else _claim_to_json(graph.claim),
    }


def _edge_from_json(value: object, where: str) -> tuple[str, str]:
    edge = _array(value, where)
    if len(edge) != 2:
        raise SnapshotError(f"{where}: expected a pair")
    return (_text(edge[0], f"{where}[0]"), _text(edge[1], f"{where}[1]"))


def _graph_from_json(value: object, where: str) -> SolutionGraph:
    data = _object(value, where)
    claim = data.get("claim")
    return SolutionGraph(
        problem_id=_text(data.get("problem_id"), f"{where}.problem_id"),
        version=_text(data.get("version"), f"{where}.version"),
        stem=_text(data.get("stem"), f"{where}.stem"),
        nodes=tuple(
            _node_from_json(item, f"{where}.nodes[{index}]")
            for index, item in enumerate(_array(data.get("nodes"), f"{where}.nodes"))
        ),
        edges=tuple(
            _edge_from_json(item, f"{where}.edges[{index}]")
            for index, item in enumerate(_array(data.get("edges"), f"{where}.edges"))
        ),
        claim=None if claim is None else _claim_from_json(claim, f"{where}.claim"),
    )


def encode_problem(problem: Problem) -> dict[str, object]:
    return {
        "version": SNAPSHOT_VERSION,
        "kind": KIND_PROBLEM,
        "data": {
            "id": problem.id,
            "title": problem.title,
            "text": problem.text,
            "subject": problem.subject,
            "grade": problem.grade,
            "annotated": problem.annotated,
            "graph": _graph_to_json(problem.graph),
        },
    }


def decode_problem(snapshot: object) -> Problem:
    data = _header(snapshot, KIND_PROBLEM)
    return Problem(
        id=_text(data.get("id"), "problem.id"),
        title=_text(data.get("title"), "problem.title"),
        text=_text(data.get("text"), "problem.text"),
        subject=_text(data.get("subject"), "problem.subject"),
        grade=_text(data.get("grade"), "problem.grade"),
        annotated=_flag(data.get("annotated"), "problem.annotated"),
        graph=_graph_from_json(data.get("graph"), "problem.graph"),
    )
