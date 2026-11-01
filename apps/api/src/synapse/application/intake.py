"""The generic intake: what a domain with no reference graph can honestly say.

Phase 0 opens the entry but does not invent a generic graph. When a submission
has no annotated graph and no plugin can build one (unknown domain, or
``SYNAPSE_LLM_MODE=off``), the session still starts — but it may only report:

* the resolved domain label and its verification mode;
* a checklist derived from that mode (goal / constraints / reproduction /
  trade-offs…), which is guidance, not a diagnosis;
* at most one clarifying question when the label was not confident;
* one next step, and a disclaimer naming what was **not** checked.

It must not claim the student missed a step, must not produce a 卡点卡, and for
a decision it must not produce a single right answer. Those are Phase 1+
capabilities; this module is the honest floor until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from synapse.application.domain_detection import MIN_CONFIDENCE
from synapse.application.domains import (
    DomainProfile,
    IntakeFramework,
    VerificationMode,
)
from synapse.domain.problem.models import Problem

VERSION: Literal["0.1"] = "0.1"

# Shown as the closed session's notice so a client that only reads ``notice``
# still learns why there is no card.
INTAKE_NOTICE = "通用模式：这一轮只做入口整理，不给出卡点结论。"

_MODE_LABELS: dict[VerificationMode, str] = {
    VerificationMode.FORMAL: "形式验证",
    VerificationMode.EXECUTABLE: "可执行验证",
    VerificationMode.EMPIRICAL: "经验验证",
    VerificationMode.ARGUMENTATIVE: "论证结构",
}

_CLARIFIER = (
    "只问一个：这更像代码问题、决策问题，还是学习/证明题？"
    "在入口的「领域」里写一个词再交一次，就能换到对应的检查方式。"
)


@dataclass(frozen=True, slots=True)
class _IntakeCopy:
    summary: str
    checklist: tuple[str, ...]
    next_step: str
    disclaimer: str


_COPY: dict[IntakeFramework, _IntakeCopy] = {
    IntakeFramework.FORMAL: _IntakeCopy(
        summary="能查的是符号、反例和边界；当前这一轮没有参考结构，所以先不判断卡点。",
        checklist=(
            "目标：最终要证明或求出什么",
            "已知：可用的条件与取值范围",
            "约束：定义域、参数范围、边界情形",
            "尝试：写到哪一步，卡在哪一行",
        ),
        next_step="把条件、目标和你写到的最后一行补全再交一次；有式子就原样贴进来。",
        disclaimer="本节没有做任何符号验证，也没有把这一步判成对或错。",
    ),
    IntakeFramework.EXECUTABLE: _IntakeCopy(
        summary="能跑的验证是可执行验证，但当前环境还没接代码执行，这一节不跑代码。",
        checklist=(
            "目标：这段代码或算法应该做到什么",
            "复现：最小片段、输入和完整报错",
            "预期与实际：你以为什么、实际发生了什么",
            "环境：语言版本、依赖、平台",
            "已试过：改过哪几处，结果如何",
        ),
        next_step="把最小复现和完整 traceback 贴进来再交一次；没跑过的地方会标「未执行」。",
        disclaimer="未执行任何代码；这里只给排查结构，不保证定位到 bug。",
    ),
    IntakeFramework.EMPIRICAL: _IntakeCopy(
        summary="能查的是单位、量纲、数量级和一致性；当前这一轮没有参考结构。",
        checklist=(
            "目标：要解释或预测哪个量",
            "已知：给了哪些量、单位是什么",
            "模型：用了哪条定律或假设，适用条件是什么",
            "检查：量纲、数量级、极端情况",
        ),
        next_step="把已知量、单位和你用的公式写出来再交一次；有数值就带上单位。",
        disclaimer="本节没有校验单位或数值，也不替代真实实验。",
    ),
    IntakeFramework.ARGUMENTATIVE: _IntakeCopy(
        summary="这里只看结构、证据和推理跳跃，不判断观点对错，也不给分数。",
        checklist=(
            "结论：你想让读者接受什么",
            "证据：哪些事实或引文在支撑它",
            "推理：从证据到结论之间，哪一步是跳过去的",
            "反方：最强的反对意见是什么",
            "受众：写给谁、希望他们做什么",
        ),
        next_step="先补上结论和支撑证据各一句，再交一次；缺证据的地方会被标出来。",
        disclaimer="不判断观点对错、不评分、不代写；只说结构缺口。",
    ),
    IntakeFramework.DECISION: _IntakeCopy(
        summary="这是决策问题：不替你选，只把目标、约束、选项、取舍与风险摆开。",
        checklist=(
            "目标：你最看重什么（先只选一个）",
            "约束：时间、钱、关系、不可逆性",
            "选项：至少两个，包含「什么都不做」",
            "代价与风险：每个选项会失去什么",
            "可逆实验：1–2 周内能先试哪一步",
        ),
        next_step="写下最看重的约束和一个可逆的小实验，再交一次；不急着做最终决定。",
        disclaimer="不提供唯一正确答案，也不提供医疗、法律或金融专业建议。",
    ),
    IntakeFramework.GENERIC: _IntakeCopy(
        summary="系统还没有把握把它归到某个领域，先按通用结构理清，不硬贴标签。",
        checklist=(
            "目标：这次希望得到什么结果",
            "已知：手上有哪些材料或事实",
            "约束：哪些条件不能动",
            "尝试：已经试过什么，结果如何",
            "判定：什么算「解决了」",
        ),
        next_step="把这些补成三五句再交一次；确定领域的话，在入口的「领域」里写一个词。",
        disclaimer="通用模式不判断对错，也不生成卡点卡；这是入口整理，不是诊断结论。",
    ),
}


@dataclass(frozen=True, slots=True)
class DomainIntake:
    """The view a reference-free session returns; derived, never stored."""

    version: Literal["0.1"]
    profile: DomainProfile
    confidence: float
    one_line: str
    checklist: tuple[str, ...]
    clarifier: str | None
    next_step: str
    disclaimer: str


def build_domain_intake(problem: Problem, profile: DomainProfile) -> DomainIntake:
    """Compose the intake for a reference-free problem.

    ``problem.domain_confidence`` carries the detector's confidence from
    intake; it decides the single clarifying question, not whether the session
    may start.
    """

    copy = _COPY[profile.framework]
    confidence = max(0.0, min(1.0, problem.domain_confidence))
    one_line = f"按「{profile.label}」处理（{_MODE_LABELS[profile.verification]}）。{copy.summary}"
    return DomainIntake(
        version=VERSION,
        profile=profile,
        confidence=confidence,
        one_line=one_line,
        checklist=copy.checklist,
        clarifier=_CLARIFIER if confidence < MIN_CONFIDENCE else None,
        next_step=copy.next_step,
        disclaimer=copy.disclaimer,
    )
