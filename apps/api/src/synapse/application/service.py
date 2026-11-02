"""Session use cases (application service / facade).

The service orchestrates domain objects and ports. It contains no FastAPI
imports and no SQL/LLM calls.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter

from synapse.application.agent import (
    AgentInputRejected,
    AgentTrace,
    AgentUnavailable,
    run_agent_trace,
)
from synapse.application.agent_planner import ToolPlanner
from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.card_builder import build_diagnosis_card
from synapse.application.coach import (
    CoachFocus,
    CoachOut,
    CoachRequest,
    CoachService,
    build_coach_context,
)
from synapse.application.commands import (
    StartSessionCommand,
    SubmitAnswerCommand,
    VerifyStepCommand,
)
from synapse.application.commitment import Capabilities, capabilities_for
from synapse.application.composer import ProbeComposer, ProbePrompt
from synapse.application.domain_detection import declared_domain
from synapse.application.domains import (
    DomainDescriptor,
    DomainRegistry,
    VerificationMode,
    verifiability_level,
)
from synapse.application.execution import CodeExecutor, RunCodeCommand
from synapse.application.execution_review import (
    build_execution_review,
    build_skipped_execution_review,
)
from synapse.application.factory import SessionFactory
from synapse.application.hint_builder import build_structure_hint
from synapse.application.intake import (
    INTAKE_NOTICE,
    MAX_INTAKE_PROBES,
    DomainIntake,
    build_domain_intake,
    checklist_for,
)
from synapse.application.knowledge import KnowledgeService
from synapse.application.limits import StepRateLimited, StepRateLimiter
from synapse.application.planner import ProbePlanner
from synapse.application.ports import (
    AnswerStore,
    ProblemRepository,
    SessionRepository,
)
from synapse.application.review import ReviewItem, ReviewQueue
from synapse.application.scaffold import Scaffold, build_scaffold
from synapse.application.subject import (
    StudentStep,
    SubjectRegistry,
    Verdict,
    VerifiabilityLevel,
)
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
from synapse.domain.problem.generic_review import GenericReview
from synapse.domain.problem.models import Probe, Problem, StudentAttempt


class SessionNotFound(LookupError):
    pass


class ReviewRunRejected(RuntimeError):
    """The session's verification mode cannot be checked by running code."""


class DiagnosisNotReady(LookupError):
    """The session exists, but there is no card to disagree with yet."""


class InvalidAnswer(ValueError):
    pass


class ClarifierUnavailable(RuntimeError):
    """The intake has no open clarifying question (or already used its one)."""


class IntakeProbeUnavailable(RuntimeError):
    """The intake has no open structural follow-up (or its budget is used)."""


# A student-named domain is not a detector score. Keep the displayed confidence
# below 1.0: the label is clearer than before, but nothing was verified.
_CLARIFIED_CONFIDENCE = 0.8


@dataclass(frozen=True, slots=True)
class Reveal:
    """Only produced for an explicit exit request; never part of a probe turn."""

    answer: str | None = None
    solution: str | None = None
    notice: str | None = None


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
    # A blank attempt gets an example before any probe. Mutually exclusive with
    # ``prompt`` and ``hint``: it is the only output of the SCAFFOLD state.
    scaffold: Scaffold | None = None
    # A reference-free problem (open domain with no graph yet) returns the
    # generic intake instead of a probe or a card. It is derived from the
    # problem's domain label, never stored, and contains no diagnosis.
    intake: DomainIntake | None = None
    # Explicit exit-with-reveal. Learning-mode views never set this.
    reveal: Reveal | None = None


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
        domains: DomainRegistry | None = None,
        auditor: CallAuditor | None = None,
        step_limiter: StepRateLimiter | None = None,
        review_queue: ReviewQueue | None = None,
        answers: AnswerStore | None = None,
        chc_attribution: bool = False,
        knowledge: KnowledgeService | None = None,
        code_executor: CodeExecutor | None = None,
        tool_planner: ToolPlanner | None = None,
        tool_planner_reason: str = "planner_off",
        coach_service: CoachService | None = None,
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
        # the service needs the registry.
        self._subjects = subjects
        # The promise tier comes from the domain's verification mode, not from
        # the plugin's own declaration: a label is open, a verification mode is
        # not. The default registry is enough for direct callers and tests.
        self._domains = domains or DomainRegistry()
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
        self._answers = answers
        self._chc_attribution = chc_attribution
        # The agent trace is a read-only side path. ``KnowledgeService(None)``
        # keeps it deterministic and offline when RAG is not wired.
        self._knowledge = knowledge or KnowledgeService(None)
        # Explicit code execution is optional here too; ``None`` means the
        # trace must say "not executed" instead of pretending it ran.
        self._code_executor = code_executor
        # Optional tool planner (Phase 4, second slice). ``None`` keeps the
        # deterministic rule choice; the runner also treats a disabled RAG as
        # "planner off" because a search tool could otherwise only be skipped.
        self._tool_planner = tool_planner
        self._tool_planner_reason = tool_planner_reason
        # Process coach: the rule path is always present; the optional model
        # narrator is injected by the composition root. It is read-only and
        # never receives the answer store.
        self._coach = coach_service or CoachService()
        # Owner binding. ``None`` means "no filter" (auth off, local baseline);
        # the composition root binds a user id per request via ``with_owner``.
        self._owner_id: str | None = None

    def with_owner(self, owner_id: str | None) -> SessionService:
        """Return a shallow copy bound to one account's workspace.

        The copy shares every adapter with the original, so it is cheap and
        thread-safe: binding is per request, not mutable global state. Every
        path that loads a session goes through ``_get``, which refuses a session
        whose owner differs.
        """

        bound = copy(self)
        bound._owner_id = owner_id
        return bound

    @property
    def owner_id(self) -> str | None:
        """The account this instance is bound to (``None`` when auth is off)."""

        return self._owner_id

    def start(self, command: StartSessionCommand) -> SessionView:
        # Check the student's own equals signs before alignment: a provable
        # finding is independent of whether a reference step was mentioned, and
        # it must survive until the card is built (see ``work_findings``).
        findings = self._check_work(command.work)
        session = self._factory.create(command)
        # Ownership is set at creation, not at read time: a session with no
        # owner (old snapshot) is inaccessible while auth is on.
        session.owner_id = self._owner_id
        session.work_findings = findings
        # The reference-free path reads the attempt back on every reload to
        # derive what it does and does not mention (application/intake.py). Same
        # lifetime and same class of data as probe answers, so it is kept on the
        # aggregate instead of being re-sent by the client.
        session.initial_answer = command.answer
        # Kept for the process coach: the annotated path does not fold the work
        # into ``initial_answer``, and quoting only the final line would turn
        # "where am I wrong" into a comment on the conclusion.
        session.initial_work = command.work
        problem = self._problem(session.problem_id)

        if self._is_reference_free(problem):
            # The UI keeps the short answer and the worked text in two fields.
            # The intake/review must read both: a writing answer alone ("不该
            # 禁止") has no argument structure, while the work field is exactly
            # where that structure lives. Keep the combined text on the
            # aggregate so a reload reconstructs the same review.
            session.initial_answer = "\n".join(
                part for part in (command.answer.strip(), command.work.strip()) if part
            )

        if self._is_reference_free(problem):
            # Phase 0 generic entry: an open domain (or an unknown label) has no
            # reference graph yet, so the session starts and immediately closes
            # with the domain intake. It never probes, never cards, and never
            # pretends the model saw a structure it did not build.
            self._sessions.add(session)
            view = self._close(session, INTAKE_NOTICE)
            return replace(view, intake=self._intake_for(session))

        capabilities = self._capabilities(problem)
        if capabilities.structure_hint:
            # S7: a NONE-tier subject stops after ALIGN. Asking a probe here
            # would promise a diagnosis we cannot verify, so the session is
            # closed with the structure hint and no card.
            # Closing paths used to rely on ``save`` as an upsert; the
            # repository is compare-and-swap only, so creation is explicit.
            self._sessions.add(session)
            return self._structure_only(session, problem, capabilities)

        if command.knows_nothing and not command.work.strip():
            # Blank/no-idea attempts start with an example, not a probe they
            # cannot answer. The state machine makes the return path explicit.
            session.advance(DialogueEvent.SCAFFOLD_READY)
            session.scaffold_level = 1
            self._sessions.add(session)
            return SessionView(
                session=session,
                scaffold=build_scaffold(problem, session.scaffold_level),
            )

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
        if session.state is DialogueState.SCAFFOLD:
            problem = self._problem(session.problem_id)
            return SessionView(
                session=session,
                scaffold=build_scaffold(problem, session.scaffold_level),
            )
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
            intake=self._intake_for(session),
        )

    def agent_trace(
        self,
        session_id: str,
        *,
        code: str | None = None,
        tests: str | None = None,
    ) -> AgentTrace:
        """Return a bounded tool trace for a reference-free intake.

        This is a side path: it reads the derived intake and never touches the
        session, the answer store, the probe budget or the diagnosis. Explicit
        code is accepted only for an EXECUTABLE framework and is still subject
        to the ``SYNAPSE_EXEC`` switch (``None`` executor means "not run").
        """

        session = self._get(session_id)
        intake = self._intake_for(session)
        if intake is None:
            raise AgentUnavailable("agent trace is only available for generic intake sessions")

        if tests is not None:
            if code is None:
                raise AgentInputRejected("tests require an explicit code submission")
            if not tests.strip() or len(tests) > 20000:
                raise AgentInputRejected("explicit tests must be 1-20000 characters")
        if code is not None and (not code.strip() or len(code) > 20000):
            raise AgentInputRejected("explicit code must be 1-20000 characters")

        return run_agent_trace(
            session_id,
            self._effective_problem(session),
            intake,
            self._knowledge,
            self._code_executor,
            planner=self._tool_planner,
            planner_off_reason=self._tool_planner_reason,
            code=code,
            tests=tests,
        )

    def review_run(
        self,
        session_id: str,
        *,
        code: str,
        tests: str = "",
    ) -> GenericReview:
        """Turn one explicitly submitted run into a code reproduction card.

        The card is derived, never stored: this method does not save the
        session, does not touch the probe budget and does not read the answer
        store. It also never selects code itself — ``code``/``tests`` are the
        caller's explicit submission. Only an ``EXECUTABLE`` domain may use it;
        anything else is rejected instead of being dressed up as a run.

        With ``SYNAPSE_EXEC=off`` the executor is ``None``, so the card reports
        ``skipped`` and the executor is not called at all (an injected test
        adapter cannot bypass the flag; the composition root gates it).
        """

        session = self._get(session_id)
        descriptor = self.domain_for(session)
        if descriptor.verification is not VerificationMode.EXECUTABLE:
            raise ReviewRunRejected(
                "代码复现卡只用于可执行验证的会话；"
                f"这道题的验证方式是 {descriptor.verification.value}。"
            )

        problem = self._effective_problem(session)
        tests_submitted = bool(tests.strip())
        if self._code_executor is None:
            return build_skipped_execution_review(
                session_id=session.session_id,
                problem_id=problem.id,
                domain_name=descriptor.name,
                domain_label=descriptor.label,
                tests_submitted=tests_submitted,
            )

        result = self._code_executor.run(RunCodeCommand(language="python", code=code, tests=tests))
        return build_execution_review(
            session_id=session.session_id,
            problem_id=problem.id,
            domain_name=descriptor.name,
            domain_label=descriptor.label,
            result=result,
            tests_submitted=tests_submitted,
        )

    def coach(self, session_id: str, *, focus: CoachFocus) -> CoachOut:
        """Process feedback for an attempted or a not-yet-started problem.

        Read-only and derived: it does not save the session, advance the state,
        touch the probe budget, or read ``AnswerStore``. The context is built
        from the stored problem and the student's own text; the intake review is
        reused when the session has one, and the domain checklist supplies the
        start plan when it does not.
        """

        session = self._get(session_id)
        problem = self._effective_problem(session)
        profile = self._domains.profile_for(problem.subject)
        intake = self._intake_for(session)
        context = build_coach_context(
            session_id=session.session_id,
            problem_text=problem.text,
            profile=profile,
            checklist=intake.checklist if intake is not None else checklist_for(profile),
            answer_text=session.initial_answer,
            work_text=session.initial_work,
            scaffold_work=session.scaffold_work,
            observed=intake.observed if intake is not None else (),
            gaps=intake.gaps if intake is not None else (),
            review=intake.review if intake is not None else None,
        )
        return self._coach.coach(context, CoachRequest(focus=focus))

    def answer_clarifier(self, session_id: str, answer: str) -> SessionView:
        """Append the one allowed clarification to a reference-free intake.

        This is not a probe and not a state transition: the session stays closed
        and no diagnosis is produced. The text re-derives ``observed``/``gaps``;
        if it explicitly names a registered domain, that label becomes the
        session's display profile so the checklist follows the student's words.
        At most one clarification is accepted; a second call returns the current
        view with a notice instead of silently accumulating prose.
        """

        session = self._get(session_id)
        intake = self._intake_for(session)
        if intake is None or intake.clarifier is None:
            if intake is not None and session.clarifier_answered:
                return SessionView(
                    session=session,
                    intake=intake,
                    notice="这次入口只接受一次补充；补充已经并入入口整理。",
                )
            raise ClarifierUnavailable("this intake has no open clarifying question")

        cleaned = answer.strip()
        if not cleaned:
            raise InvalidAnswer("clarification answer is empty")
        if len(cleaned) > 500:
            raise InvalidAnswer("clarification answer is too long")

        parts = [part for part in (session.initial_answer.strip(), cleaned) if part]
        session.initial_answer = "\n".join(parts)
        session.clarifier_answered = True
        named = declared_domain(cleaned)
        if named is not None:
            session.domain_override = named
        self._sessions.save(session)
        notice = "补充已并入入口整理；它仍然只说明你提到了什么，不定位卡点。"
        if session.domain_override is not None:
            label = self._domains.profile_for(session.domain_override).label
            notice = (
                f"补充已并入入口整理；这轮改按「{label}」处理，检查方式随之变化，"
                "但这一轮仍然不定位卡点。"
            )
        return SessionView(
            session=session,
            intake=self._intake_for(session),
            notice=notice,
        )

    def answer_intake_probe(self, session_id: str, answer: str) -> SessionView:
        """Append one answer to the intake's structural follow-up.

        This is not a probe turn: state, hypotheses and diagnosis stay untouched,
        and the text is only used to re-derive ``observed``/``gaps``. The
        two counters are independent: the domain clarifier can be used once,
        while structural follow-ups stop at ``MAX_INTAKE_PROBES``.
        """

        session = self._get(session_id)
        intake = self._intake_for(session)
        if intake is None or intake.probe is None:
            raise IntakeProbeUnavailable("this intake has no open structural question")

        cleaned = answer.strip()
        if not cleaned:
            raise InvalidAnswer("structural answer is empty")
        if len(cleaned) > 500:
            raise InvalidAnswer("structural answer is too long")

        parts = [part for part in (session.initial_answer.strip(), cleaned) if part]
        session.initial_answer = "\n".join(parts)
        session.intake_probe_count = min(
            session.intake_probe_count + 1,
            MAX_INTAKE_PROBES,
        )
        self._sessions.save(session)
        return SessionView(
            session=session,
            intake=self._intake_for(session),
            notice="补充只增加你写到的结构；它不判断对错，也不定位卡点。",
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
                intake=self._intake_for(session),
            )

        problem = self._problem(session.problem_id)
        if session.state is DialogueState.SCAFFOLD:
            return self._submit_scaffold(session, problem, command)
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
            card = build_diagnosis_card(
                session,
                problem,
                chc_attribution=self._chc_attribution,
            )
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

    def exit(self, session_id: str, *, reveal: bool = False) -> SessionView:
        session = self._get(session_id)
        if session.state is DialogueState.CLOSED:
            view = SessionView(session=session, notice="会话已关闭。")
        else:
            view = self._close(
                session,
                "已退出学习模式；本次不生成卡点卡。解法只在这次显式请求里返回。"
                if reveal
                else "已退出学习模式；本次不生成卡点卡，也不展示最终答案。",
            )
        if not reveal:
            return replace(view, intake=self._intake_for(session))
        return replace(
            view,
            intake=self._intake_for(session),
            reveal=self._reveal(session.problem_id),
        )

    def _reveal(self, problem_id: str) -> Reveal:
        """Read the answer store only for an explicit post-exit request.

        The method is deliberately not called from ``start``/``submit``/
        ``get``: the learning path cannot reach it by accident. Generated
        problems have no stored solution, and the response says so instead of
        inventing one.
        """

        problem = self._problem(problem_id)
        if not problem.annotated:
            return Reveal(notice="这题没有存储解法；生成题不编造答案。")
        if self._answers is None:
            return Reveal(notice="答案库未接入；本次不展示解法。")
        try:
            return Reveal(
                answer=self._answers.answer_for(problem.id),
                solution=self._answers.solution_for(problem.id),
            )
        except KeyError:
            return Reveal(notice="这道题没有存储答案；本次不展示解法。")

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

    def _submit_scaffold(
        self,
        session: DialogueSession,
        problem: Problem,
        command: SubmitAnswerCommand,
    ) -> SessionView:
        """Take work submitted from the SCAFFOLD state and re-enter the dialogue.

        The answer is free text, not an option. It is appended to the work
        accumulated so far so a student who writes one line at a time can keep
        moving; the alignment is recomputed against the whole attempt.
        """

        text = command.answer.strip()
        work = f"{session.scaffold_work}\n{text}".strip()
        before = len(session.alignment.matched_node_ids)
        alignment = self._factory.realign(
            session,
            problem,
            StudentAttempt(answer=command.answer, work=work),
        )
        session.scaffold_work = work

        if alignment.first_divergence == "none":
            return self._close(
                session,
                "这次过程已经覆盖了参考步骤；本轮没有可诊断的断点。",
            )

        if len(alignment.matched_node_ids) > before:
            session.advance(DialogueEvent.WORK_SUBMITTED)
            probe = self._planner.next(session, problem.graph)
            if probe is None:
                return self._close(
                    session,
                    "过程已经接上；没有可用的探针，先不生成卡点卡。",
                )
            session.asked_probe_ids.append(probe.id)
            prompt = self._compose(session, problem, probe)
            self._sessions.save(session)
            return SessionView(session=session, prompt=prompt)

        if session.scaffold_level < 2:
            session.scaffold_level += 1
            self._sessions.save(session)
            return SessionView(
                session=session,
                scaffold=build_scaffold(problem, session.scaffold_level),
            )

        return self._stop_without_card(
            session,
            "还是没有看到过程。先写一行——哪怕只写“定义域是 x>0”也可以，再回来诊断。",
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

    def _profile_level(self, problem: Problem) -> VerifiabilityLevel:
        """The tier the domain's verification mode allows (Phase 0).

        The domain profile is authoritative, not the plugin: ``programming``
        has no plugin yet and is still ``NONE``, because nothing has executed
        the student's code.
        """

        profile = self._domains.profile_for(problem.subject)
        return verifiability_level(profile.verification)

    def _capabilities(self, problem: Problem) -> Capabilities:
        """What this domain's verification mode lets the dialogue promise (S7)."""

        return capabilities_for(self._profile_level(problem))

    def _check_work(self, work: str) -> tuple[WorkFinding, ...]:
        """Run the optional equality checker; no checker means the old path."""

        if self._equality_checker is None or not work.strip():
            return ()
        return self._equality_checker.findings(work)

    @staticmethod
    def _is_reference_free(problem: Problem) -> bool:
        """No reviewed graph and no generated one: the generic intake floor."""

        return not problem.annotated and not problem.graph.nodes

    def _effective_problem(self, session: DialogueSession) -> Problem:
        """The stored problem, with a student-named domain layered on top.

        ``Problem`` is immutable and shared by every session that submitted the
        same text, so the override lives on the session. Only the display/intake
        profile changes; the submitted label and graph are untouched.
        """

        problem = self._problem(session.problem_id)
        if session.domain_override is None:
            return problem
        return replace(
            problem,
            subject=session.domain_override,
            domain_confidence=_CLARIFIED_CONFIDENCE,
            domain_method="clarified",
        )

    def _intake_for(self, session: DialogueSession) -> DomainIntake | None:
        """Derive the generic intake; ``None`` for anything with a graph."""

        problem = self._effective_problem(session)
        if not self._is_reference_free(problem):
            return None
        profile = self._domains.profile_for(problem.subject)
        return build_domain_intake(
            problem,
            profile,
            session.initial_answer,
            session_id=session.session_id,
            clarifier_answered=session.clarifier_answered,
            probe_count=session.intake_probe_count,
            knowledge=self._knowledge,
        )

    def _hint(self, session: DialogueSession) -> StructureHint | None:
        """Rebuild the structure hint for a NONE-tier session.

        Derived from the alignment and the graph, so a reloaded session shows
        the same text without the aggregate having to store it. A reference-free
        problem has no graph to point at, so it gets the intake instead.
        """

        problem = self._problem(session.problem_id)
        if not problem.graph.nodes:
            return None
        level = self._profile_level(problem)
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
            level=self._profile_level(problem).value,
        )
        view = self._close(session, capabilities.note)
        return SessionView(session=view.session, notice=view.notice, hint=hint)

    def _get(self, session_id: str) -> DialogueSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        if self._owner_id is not None and session.owner_id != self._owner_id:
            # Same error as "no such session": a 404 must not confirm that
            # another account owns this id.
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
        """The plugin key for this problem (internal routing, not display).

        The UI displays ``domain_for(session)`` instead: the subject says which
        plugin built the graph, the domain says what the product may promise.
        """

        return self._problem(problem_id).subject

    def problem_domain(self, problem_id: str) -> DomainDescriptor:
        """The open domain label plus how it was resolved (Phase 0).

        Kept separate from ``problem_subject``: the subject is still the plugin
        key, while the domain descriptor is what the client displays and what
        decides the verification promise. This method has no session, so it
        reports the submitted problem; HTTP responses use ``domain_for``.
        """

        problem = self._problem(problem_id)
        profile = self._domains.profile_for(problem.subject)
        return profile.describe(problem.domain_confidence)

    def domain_for(self, session: DialogueSession) -> DomainDescriptor:
        """The displayed domain for this session, including a clarification.

        A student who answers "这是决策问题" gets the decision checklist and
        label, but the submitted subject is still what the graph/plugin code
        sees; the override is display and intake only.
        """

        problem = self._effective_problem(session)
        profile = self._domains.profile_for(problem.subject)
        return profile.describe(problem.domain_confidence)

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
