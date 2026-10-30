"""Session use cases (application service / facade).

The service orchestrates domain objects and ports. It contains no FastAPI
imports and no SQL/LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from synapse.application.card_builder import build_diagnosis_card
from synapse.application.commands import StartSessionCommand, SubmitAnswerCommand
from synapse.application.commitment import Capabilities, capabilities_for
from synapse.application.composer import ProbeComposer, ProbePrompt
from synapse.application.factory import SessionFactory
from synapse.application.hint_builder import build_structure_hint
from synapse.application.planner import ProbePlanner
from synapse.application.ports import (
    ProblemRepository,
    SessionRepository,
)
from synapse.application.trace import tracing
from synapse.domain.diagnosis.hint import StructureHint
from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.dialogue.events import DialogueEvent
from synapse.domain.dialogue.session import DialogueSession, TurnRecord
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.evidence.models import Evidence
from synapse.domain.problem.alignment import normalize
from synapse.domain.problem.models import Probe, Problem


class SessionNotFound(LookupError):
    pass


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
    ) -> None:
        self._sessions = sessions
        self._problems = problems
        self._factory = factory
        self._planner = planner
        self._composer = composer

    def start(self, command: StartSessionCommand) -> SessionView:
        session = self._factory.create(command)
        problem = self._problem(session.problem_id)

        capabilities = self._capabilities(problem)
        if capabilities.structure_hint:
            # S7: a NONE-tier subject stops after ALIGN. Asking a probe here
            # would promise a diagnosis we cannot verify, so the session is
            # closed with the structure hint and no card.
            return self._structure_only(session, problem, capabilities)

        if session.alignment.first_divergence == "none":
            return self._close(
                session,
                "过程覆盖了定义域、最值、参数分类与合并；本轮没有可诊断的断点。",
            )

        probe = self._planner.next(session, problem.graph)
        if probe is None:
            return self._close(session, "没有可用的探针，先不生成卡点卡。")
        session.asked_probe_ids.append(probe.id)
        prompt = self._compose(session, problem, probe)
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
    ) -> ProbePrompt:
        _, confidence = session.hypotheses.top()
        with tracing(session.session_id, session.turn + 1):
            return self._composer.compose(
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
