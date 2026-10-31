"""Session use cases (application service / facade).

The service orchestrates domain objects and ports. It contains no FastAPI
imports and no SQL/LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter

from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.card_builder import build_diagnosis_card
from synapse.application.commands import (
    StartSessionCommand,
    SubmitAnswerCommand,
    VerifyStepCommand,
)
from synapse.application.commitment import Capabilities, capabilities_for
from synapse.application.composer import ProbeComposer, ProbePrompt
from synapse.application.factory import SessionFactory
from synapse.application.hint_builder import build_structure_hint
from synapse.application.limits import StepRateLimited, StepRateLimiter
from synapse.application.planner import ProbePlanner
from synapse.application.ports import (
    ProblemRepository,
    SessionRepository,
)
from synapse.application.review import ReviewItem, ReviewQueue
from synapse.application.subject import StudentStep, SubjectRegistry, Verdict
from synapse.application.trace import tracing
from synapse.application.work_check import EqualityChecker
from synapse.domain.diagnosis.hint import StructureHint
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.diagnosis.work import WorkFinding
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.evidence.models import Evidence
from synapse.domain.problem.alignment import normalize
from synapse.domain.problem.models import Probe, Problem


class SessionNotFound(LookupError):
    pass


class DiagnosisNotReady(LookupError):
    """The session exists, but there is no card to disagree with yet."""


class InvalidAnswer(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionView:
    session: DialogueSession
    prompt: ProbePrompt | None = None
    diagnosis: DiagnosisCard | None = None
    notice: str | None = None
    # NONE-tier subjects get a structure hint instead of a card (M2.5 S7).
    # The two are mutually exclusive by construction: the tier decides before a
    # probe is ever asked, and ``hint`` is derived, not stored.
    hint: StructureHint | None = None


class SessionService:
    def __init__(
        self,
        sessions: SessionRepository,
        problems: ProblemRepository,
        factory: SessionFactory,
        planner: ProbePlanner,
        composer: ProbeComposer,
        *,
        opening_composer: ProbeComposer | None = None,
        equality_checker: EqualityChecker | None = None,
        subjects: SubjectRegistry | None = None,
        auditor: CallAuditor | None = None,
        step_limiter: StepRateLimiter | None = None,
        review_queue: ReviewQueue | None = None,
    ) -> None:
        self._sessions = sessions
        self._problems = problems
        self._factory = factory
        self._planner = planner
        self._composer = composer
        # The first question of an on-demand built problem is composed by the
        # deterministic renderer (see ``_compose``); ``None`` means "same
        # composer as every other turn", which is what the rule baseline and
        # the tests get.
        self._opening_composer = opening_composer
        # Off by default: ``None`` means the baseline path, byte-identical to
        # the cards the golden set was measured against. The switch lives in the
        # composition root (``api/deps.py``), not here.
        self._equality_checker = equality_checker
        # Step verification asks the subject plugin after the session exists, so
        # the service needs the registry (the factory only exposes level_for).
        self._subjects = subjects
        # Optional operational trail for single-step checks. It is not session
        # state: the endpoint stays read-only, and the student's text is not
        # copied into the audit (see ``_audit_step_verification``).
        self._auditor = auditor
        # Optional process-local throttle. The composition root owns the
        # production default; ``None`` keeps direct callers unthrottled.
        self._step_limiter = step_limiter
        # Optional local review queue. Disagreeing with a card is the only writer;
        # the queue stores the card's conclusion, never the student's work.
        self._review_queue = review_queue

    def start(self, command: StartSessionCommand) -> SessionView:
        # Check the student's own equals signs before alignment: a provable
        # finding is independent of whether a reference step was mentioned, and
        # it must survive until the card is built (see ``work_findings``).
        findings = self._check_work(command.work)
        session = self._factory.create(command)
        session.work_findings = findings
        problem = self._problem(session.problem_id)

        capabilities = self._capabilities(problem)
        if capabilities.structure_hint:
            # S7: a NONE-tier subject stops after ALIGN. Asking a probe here
            # would promise a diagnosis we cannot verify, so the session is
            # closed with the structure hint and no card.
            # Closing paths used to rely on ``save`` as an upsert; the
            # repository is compare-and-swap only, so creation is explicit.
            self._sessions.add(session)
            return self._structure_only(session, problem, capabilities)

        if session.alignment.first_divergence == "none":
            self._sessions.add(session)
            return self._close(
                session,
                "过程覆盖了定义域、最值、参数分类与合并；本轮没有可诊断的断点。",
            )

        probe = self._planner.next(session, problem.graph)
        if probe is None:
            self._sessions.add(session)
            return self._close(session, "没有可用的探针，先不生成卡点卡。")
        session.asked_probe_ids.append(probe.id)
        prompt = self._compose(session, problem, probe, opening=True)
        self._sessions.add(session)
        return SessionView(session=session, prompt=prompt)

    def get(self, session_id: str) -> SessionView:
        session = self._get(session_id)
        if session.state is DialogueState.PROBE and session.current_probe_id:
            problem = self._problem(session.problem_id)
            probe = problem.graph.probe(session.current_probe_id)
            return SessionView(
                session=session,
                prompt=self._compose(session, problem, probe),
            )
        return SessionView(
            session=session,
            diagnosis=session.diagnosis,
            hint=self._hint(session),
        )

    def mark_card_disagree(self, session_id: str) -> DiagnosisCard:
        """Persist the student's disagreement with the current card.

        This is deliberately narrow: the card keeps its diagnosis, evidence and
        confidence; only the ``disagree`` flag changes. The flag survives a
        reload because it is stored with the session, and a copy is appended to
        the optional local review queue. It is not a state transition.
        """

        session = self._get(session_id)
        if session.diagnosis is None:
            raise DiagnosisNotReady("diagnosis card is not ready")
        if session.diagnosis.disagree:
            return session.diagnosis

        card = replace(session.diagnosis, disagree=True)
        session.diagnosis = card
        # Save before the review-queue append: a losing compare-and-swap must
        # not leave a queue row for a disagreement the session never stored.
        self._sessions.save(session)
        if self._review_queue is not None:
            self._review_queue.record(
                ReviewItem.from_card(
                    card,
                    created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                )
            )
        return card

    def submit(self, session_id: str, command: SubmitAnswerCommand) -> SessionView:
        session = self._get(session_id)

        if session.diagnosis is not None:
            return SessionView(
                session=session,
                diagnosis=session.diagnosis,
                notice="卡点卡已生成，可进入复核或迁移验证。",
            )
        if session.state in {DialogueState.STOP, DialogueState.CLOSED}:
            return SessionView(
                session=session,
                notice="会话已结束，不再接受新的回答。",
                hint=self._hint(session),
            )

        problem = self._problem(session.problem_id)
        current_probe_id = session.current_probe_id
        if current_probe_id is None:
            return self._stop_without_card(session, "当前没有待回答的问题。")
        probe = problem.graph.probe(current_probe_id)

        if self._is_unknown(command):
            return self._handle_unknown(session, problem, probe, command)

        option_id = self._resolve_option(probe, command)
        if option_id is None:
            raise InvalidAnswer("answer does not match any option and option_id is missing")

        session.hypotheses.observe(probe.id, option_id)
        session.advance(DialogueEvent.PROBE_ANSWERED)
        session.record_turn(
            TurnRecord(
                turn=session.turn + 1,
                probe_id=probe.id,
                question=probe.question,
                answer=command.answer,
                option_id=option_id,
                action="answer",
            )
        )
        self._record_probe_evidence(session, probe, option_id)

        decision = session.hypotheses.decide(session.turn, session.max_turns)
        if decision.kind == "diagnose":
            card = build_diagnosis_card(session, problem)
            session.advance(DialogueEvent.DIAGNOSIS_READY)
            session.diagnosis = card
            self._sessions.save(session)
            return SessionView(session=session, diagnosis=card)

        if decision.kind == "stop":
            session.advance(DialogueEvent.TURN_LIMIT)
            return self._close(
                session,
                "到轮次上限仍低于 0.55 置信度；先不给确定卡点，建议补一步过程再测。",
            )

        next_probe = self._planner.next(session, problem.graph)
        if next_probe is None:
            return self._stop_without_card(
                session,
                "探针已用完，但置信度还不够；先不给确定卡点。",
            )

        session.asked_probe_ids.append(next_probe.id)
        prompt = self._compose(session, problem, next_probe)
        self._sessions.save(session)
        return SessionView(session=session, prompt=prompt)

    def exit(self, session_id: str) -> SessionView:
        session = self._get(session_id)
        if session.state is DialogueState.CLOSED:
            return SessionView(session=session, notice="会话已关闭。")
        return self._close(
            session,
            "已退出学习模式；本次不生成卡点卡，也不展示最终答案。",
        )

    def verify_step(self, session_id: str, command: VerifyStepCommand) -> Verdict:
        """Verify one submitted step without advancing the dialogue.

        This is deliberately read-only: a subject's ``verify()`` may say
        ``pass``/``fail``/``unknown``, but it must never become a state
        transition or a card. The student can ask about a step at any point;
        only the plugin that owns the problem's subject is consulted.

        A per-session limiter, when wired, is checked before the plugin runs:
        a 429 is not a verdict and is not written to the step audit.
        """

        session = self._get(session_id)
        problem = self._problem(session.problem_id)
        if self._step_limiter is not None:
            retry_after = self._step_limiter.consume(session.session_id)
            if retry_after is not None:
                raise StepRateLimited(retry_after)
        started = perf_counter()
        try:
            verdict = self._verify_step(session, problem.subject, command)
        except Exception as exc:
            # Keep the failure visible in the operational trail, then let the
            # API surface it. The audit must never hide a broken verifier.
            self._audit_step_verification(
                session,
                problem.subject,
                command,
                verdict=None,
                started=started,
                error=type(exc).__name__,
            )
            raise
        self._audit_step_verification(
            session,
            problem.subject,
            command,
            verdict=verdict,
            started=started,
        )
        return verdict

    def _verify_step(
        self,
        session: DialogueSession,
        subject: str,
        command: VerifyStepCommand,
    ) -> Verdict:
        if self._subjects is None:
            return Verdict(
                status="unknown",
                detail="没有注册学科插件，未对这一步作断言。",
            )
        plugin = self._subjects.for_subject(subject)
        if plugin is None:
            return Verdict(
                status="unknown",
                detail=f"没有注册「{subject}」的学科插件，未对这一步作断言。",
            )
        return plugin.verify(
            StudentStep(
                node_id=command.node_id,
                text=command.text,
                turn=session.turn,
                data=command.data,
            )
        )

    def _audit_step_verification(
        self,
        session: DialogueSession,
        subject: str,
        command: VerifyStepCommand,
        *,
        verdict: Verdict | None,
        started: float,
        error: str | None = None,
    ) -> None:
        if self._auditor is None:
            return
        self._auditor.record(
            AuditEntry(
                kind="step_verify",
                session_id=session.session_id,
                turn=session.turn,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                verification_status="error" if verdict is None else verdict.status,
                fallback_reason=error,
                subject=subject,
                finding_count=0 if verdict is None else len(verdict.findings),
                step_chars=len(command.text),
            )
        )

    def _handle_unknown(
        self,
        session: DialogueSession,
        problem: Problem,
        probe: Probe,
        command: SubmitAnswerCommand,
    ) -> SessionView:
        session.hypotheses.observe_unknown(probe.id)
        session.advance(DialogueEvent.PROBE_ANSWERED)
        session.record_turn(
            TurnRecord(
                turn=session.turn + 1,
                probe_id=probe.id,
                question=probe.question,
                answer=command.answer,
                option_id=None,
                action="hint",
                is_unknown=True,
            )
        )
        session.evidence.add(
            Evidence(
                id=f"probe:{probe.id}:{session.turn}",
                source="probe",
                claim=f"第 {session.turn} 轮说“不知道”，降低了对已掌握该步的置信",
                supports=("H_L1",),
                turn=session.turn,
            )
        )
        if session.turn >= session.max_turns:
            session.advance(DialogueEvent.TURN_LIMIT)
            return self._close(
                session,
                "连续说“不知道”且到轮次上限；先降级为补概念，不硬判卡点。",
            )

        next_probe = self._planner.next(session, problem.graph)
        if next_probe is None:
            return self._stop_without_card(
                session,
                "没有更简单的探针了；先给一个具体例子，不硬判卡点。",
            )
        session.asked_probe_ids.append(next_probe.id)
        prompt = self._compose(
            session,
            problem,
            next_probe,
            hint_level=min(probe.hint_level + 1, 3),
        )
        self._sessions.save(session)
        return SessionView(session=session, prompt=prompt)

    def _compose(
        self,
        session: DialogueSession,
        problem: Problem,
        probe: Probe,
        *,
        hint_level: int = 0,
        opening: bool = False,
    ) -> ProbePrompt:
        """Compose one prompt; the first question may skip the model rewrite.

        Turn 1 is the only composition inside the 8s first-question budget. A
        *generated* probe was written by the graph model seconds earlier, so a
        second model pass that may only re-word it buys nothing and costs a
        whole round trip (measured 1–4s, mostly time-to-first-token). The
        hand-written seed probe still gets the T3 rewrite: its wording is not
        model output, and the annotated path has no graph build to pay for.
        """
        composer = self._composer
        if opening and not problem.annotated and self._opening_composer is not None:
            composer = self._opening_composer
        _, confidence = session.hypotheses.top()
        with tracing(session.session_id, session.turn + 1):
            return composer.compose(
                problem,
                probe,
                confidence=confidence,
                hint_level=hint_level,
            )

    @staticmethod
    def _record_probe_evidence(
        session: DialogueSession,
        probe: Probe,
        option_id: str,
    ) -> None:
        supports = session.hypotheses.supported_by(probe.id, option_id)
        if not supports:
            return
        labels = "、".join(
            session.hypotheses.states[hyp_id].hypothesis.label
            for hyp_id in supports
            if hyp_id in session.hypotheses.states
        )
        session.evidence.add(
            Evidence(
                id=f"probe:{probe.id}:{session.turn}",
                source="probe",
                claim=f"第 {session.turn} 轮的回答支持“{labels}”假设",
                supports=supports,
                turn=session.turn,
            )
        )

    def _resolve_option(self, probe: Probe, command: SubmitAnswerCommand) -> str | None:
        if command.option_id:
            option = command.option_id.strip().upper()
            if option in {"A", "B", "C", "D"}:
                index = ord(option) - ord("A")
                if index < len(probe.options):
                    return option
                return None

        answer = normalize(command.answer)
        for index, option in enumerate(probe.options):
            if normalize(option) == answer:
                return chr(ord("A") + index)

        for index, option in enumerate(probe.options):
            normalized_option = normalize(option)
            if answer and (answer in normalized_option or normalized_option in answer):
                return chr(ord("A") + index)
        return None

    @staticmethod
    def _is_unknown(command: SubmitAnswerCommand) -> bool:
        if command.option_id and command.option_id.lower() in {
            "unknown",
            "idk",
            "dont_know",
        }:
            return True
        return not command.option_id and normalize(command.answer) in {
            "不会",
            "不知道",
            "完全不会",
        }

    def _capabilities(self, problem: Problem) -> Capabilities:
        """What this subject's tier lets the dialogue promise (S7)."""

        return capabilities_for(self._factory.level_for(problem.subject))

    def _check_work(self, work: str) -> tuple[WorkFinding, ...]:
        """Run the optional equality checker; no checker means the old path."""

        if self._equality_checker is None or not work.strip():
            return ()
        return self._equality_checker.findings(work)

    def _hint(self, session: DialogueSession) -> StructureHint | None:
        """Rebuild the structure hint for a NONE-tier session.

        Derived from the alignment and the graph, so a reloaded session shows
        the same text without the aggregate having to store it.
        """

        problem = self._problem(session.problem_id)
        level = self._factory.level_for(problem.subject)
        if not capabilities_for(level).structure_hint:
            return None
        return build_structure_hint(session, problem, level=level.value)

    def _structure_only(
        self,
        session: DialogueSession,
        problem: Problem,
        capabilities: Capabilities,
    ) -> SessionView:
        """Close a NONE-tier session after ALIGN with a structure hint."""

        hint = build_structure_hint(
            session,
            problem,
            level=self._factory.level_for(problem.subject).value,
        )
        view = self._close(session, capabilities.note)
        return SessionView(session=view.session, notice=view.notice, hint=hint)

    def _get(self, session_id: str) -> DialogueSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    def _problem(self, problem_id: str) -> Problem:
        problem = self._problems.get(problem_id)
        if problem is None:
            raise LookupError(f"unknown problem: {problem_id}")
        return problem

    def problem_title(self, problem_id: str) -> str:
        return self._problem(problem_id).title

    def problem_text(self, problem_id: str) -> str:
        """题面全文。追问时前端要能随时回看整道题——只给题面，不给答案。"""
        return self._problem(problem_id).text

    def problem_subject(self, problem_id: str) -> str:
        """Whose plugin owns this problem; the UI uses it to gate step checks."""
        return self._problem(problem_id).subject

    def _stop_without_card(self, session: DialogueSession, notice: str) -> SessionView:
        if session.state is not DialogueState.STOP:
            session.advance(DialogueEvent.ABORT)
        return self._close(session, notice)

    def _close(self, session: DialogueSession, notice: str) -> SessionView:
        if session.state is DialogueState.DIAGNOSE or session.state is DialogueState.STOP:
            session.advance(DialogueEvent.CLOSE)
        elif session.state is not DialogueState.CLOSED:
            session.advance(DialogueEvent.ABORT)
            session.advance(DialogueEvent.CLOSE)
        self._sessions.save(session)
        return SessionView(session=session, notice=notice)
