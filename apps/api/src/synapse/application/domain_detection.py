"""Pick an open domain label from the stem, without a whitelist.

The product is a general problem diagnoser, not a K12 tutor: a submitted stem can
be a math problem, a code bug, an algorithm, a writing task, a research question,
a life decision, a work problem, or something the system has never seen. A
domain is therefore an *open label*, and detection is advisory only:

* deterministic term/formula scoring runs first and covers the domains whose
  vocabulary is distinctive enough to score cheaply;
* a model classifier is consulted only when the score is not decisive;
* when neither is confident the caller gets ``domain=None`` and enters the
  generic profile. That is not an error and never becomes a 422.

Detection never chooses a graph, writes a diagnosis or moves the dialogue: it
only supplies a label plus the provenance the intake view reports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

MIN_CONFIDENCE = 0.6

# Weights are intentionally small and hand-checked. A single weak cue is not
# enough to pass ``MIN_CONFIDENCE``; two strong cues are. The first three
# tables are unchanged from the M2.5 detector so math/physics/chinese keep
# their measured behaviour; the open-domain tables are additive and use
# vocabulary that does not occur in those three subjects' seeds.
_TERMS: dict[str, tuple[tuple[str, int], ...]] = {
    "math": (
        ("函数", 2),
        ("方程", 2),
        ("不等式", 2),
        ("导数", 2),
        ("求导", 2),
        ("积分", 2),
        ("数列", 2),
        ("向量", 2),
        ("几何", 2),
        ("概率", 2),
        ("恒成立", 2),
        ("取值范围", 2),
        ("定义域", 2),
        ("判别式", 2),
        ("轨迹", 2),
        ("对数", 2),
        ("指数", 2),
        ("三角函数", 2),
        ("证明", 1),
        ("求解", 1),
        ("最大值", 1),
        ("最小值", 1),
        ("三角形", 1),
        ("坐标", 1),
        ("任意", 1),
        ("求", 1),
        ("已知", 1),
        ("计算", 1),
    ),
    "physics": (
        ("重力", 2),
        ("支持力", 2),
        ("摩擦力", 2),
        ("摩擦", 2),
        ("合力", 2),
        ("受力", 2),
        ("拉力", 2),
        ("速度", 2),
        ("加速度", 2),
        ("质量", 2),
        ("动能", 2),
        ("势能", 2),
        ("动量", 2),
        ("电场", 2),
        ("磁场", 2),
        ("电阻", 2),
        ("电压", 2),
        ("电流", 2),
        ("功率", 2),
        ("波长", 2),
        ("频率", 2),
        ("折射", 2),
        ("透镜", 2),
        ("压强", 2),
        ("浮力", 2),
        ("密度", 2),
        ("热量", 2),
        ("温度", 1),
        ("电荷", 2),
        ("磁通", 2),
        ("斜面", 2),
        ("滑轮", 2),
        ("弹簧", 2),
        ("碰撞", 2),
        ("圆周运动", 2),
        ("简谐", 2),
        ("物块", 1),
        ("水平面", 1),
        ("单位", 1),
    ),
    "chinese": (
        ("阅读", 2),
        ("文章", 2),
        ("文字", 1),
        ("段落", 2),
        ("主旨", 2),
        ("作者", 2),
        ("修辞", 2),
        ("赏析", 2),
        ("文言文", 2),
        ("文言", 2),
        ("古诗", 2),
        ("诗句", 2),
        ("概括", 2),
        ("句子", 1),
        ("词语", 2),
        ("病句", 2),
        ("标点", 2),
        ("作文", 2),
        ("标题", 1),
        ("论证", 2),
        ("说明文", 2),
        ("记叙文", 2),
        ("人物", 1),
        ("情节", 1),
        ("环境", 1),
        ("描写", 1),
        ("表达方式", 2),
        ("含义", 1),
    ),
    # --- open domains (Phase 0) ---------------------------------------------
    # Cues stay domain-specific: "函数" is not a programming cue, "假设" alone is
    # not a research cue, and "选择" alone is not a decision cue (math exams have
    # 选择题). A stem that genuinely mixes two of these lands below the margin
    # and goes to the generic profile, which is the honest outcome.
    "programming": (
        ("python", 2),
        ("javascript", 2),
        ("typescript", 2),
        ("java", 2),
        ("c++", 2),
        ("代码", 2),
        ("脚本", 2),
        ("报错", 2),
        ("异常", 2),
        ("traceback", 2),
        ("编译", 2),
        ("调试", 2),
        ("bug", 2),
        ("npm", 2),
        ("git", 2),
        ("docker", 2),
        ("sql", 2),
        ("数据库", 2),
        ("接口", 1),
        ("单元测试", 2),
        ("测试用例", 2),
        ("复现", 1),
        ("递归", 2),
        ("排序", 1),
        ("二分", 2),
        ("哈希", 2),
        ("链表", 2),
        ("二叉树", 2),
        ("时间复杂度", 2),
        ("空间复杂度", 2),
        ("算法", 2),
        ("动态规划", 2),
        ("堆栈", 2),
        ("进程", 1),
        ("线程", 1),
        ("部署", 1),
    ),
    "research": (
        ("论文", 2),
        ("文献", 2),
        ("综述", 2),
        ("样本量", 2),
        ("样本", 1),
        ("实验设计", 2),
        ("对照组", 2),
        ("显著性", 2),
        ("p值", 2),
        ("引用", 1),
        ("研究方法", 2),
        ("可重复", 2),
        ("预注册", 2),
        ("科研", 2),
        ("假设检验", 2),
        ("统计", 1),
        ("访谈", 1),
        ("问卷", 1),
    ),
    "writing": (
        ("写作", 2),
        ("essay", 2),
        ("thesis", 2),
        ("paragraph", 2),
        ("draft", 1),
        ("文风", 2),
        ("初稿", 2),
        ("改写", 2),
        ("润色", 2),
    ),
    "decision": (
        ("该不该", 2),
        ("要不要", 2),
        ("选哪个", 2),
        ("怎么选", 2),
        ("选择哪", 2),
        ("还是留", 2),
        ("还是去", 2),
        ("留在", 1),
        ("跳槽", 2),
        ("offer", 2),
        ("取舍", 2),
        ("利弊", 2),
        ("纠结", 2),
        ("值得吗", 2),
        ("陪家人", 2),
        ("工作机会", 2),
        ("买房", 2),
        ("考研", 2),
        ("分手", 2),
        ("结婚", 2),
        ("人生", 1),
    ),
    "work": (
        ("团队", 2),
        ("同事", 2),
        ("上级", 2),
        ("领导", 1),
        ("汇报", 2),
        ("排期", 2),
        ("需求评审", 2),
        ("产品经理", 2),
        ("会议", 1),
        ("绩效", 2),
        ("晋升", 2),
        ("协作", 2),
        ("交付", 1),
        ("客户", 2),
        ("公司", 1),
        ("职场", 2),
        ("流程", 1),
    ),
    "chemistry": (
        ("化学", 2),
        ("化学式", 2),
        ("分子式", 2),
        ("摩尔", 2),
        ("浓度", 2),
        ("溶液", 2),
        ("反应式", 2),
        ("催化剂", 2),
        ("酸碱", 2),
        ("氧化", 2),
        ("还原", 2),
        ("离子", 2),
        ("方程式", 1),
    ),
    "biology": (
        ("细胞", 2),
        ("基因", 2),
        ("蛋白质", 2),
        ("生态", 2),
        ("遗传", 2),
        ("dna", 2),
        ("rna", 2),
        ("酶", 1),
        ("种群", 2),
        ("免疫", 2),
        ("生物", 1),
    ),
}

_MATH_FORMULA = re.compile(r"[A-Za-z]\s*\([A-Za-z]+\)|[=<>≤≥]|[+\-*/^]|√|∫|∑")
_PHYSICS_UNIT = re.compile(r"(?<![A-Za-z])(?:kg|m/s\^?2|m/s|Ω|Pa|Hz|mol)(?![A-Za-z])")


@dataclass(frozen=True, slots=True)
class DetectedDomain:
    """An advisory label; ``None`` means "no decisive cue, use generic"."""

    domain: str | None
    confidence: float
    method: str = "heuristic"


class DomainDetector(Protocol):
    def detect(self, text: str) -> DetectedDomain: ...


class HeuristicDomainDetector:
    """Term counting with a margin-aware confidence.

    ``confidence = min(1, top / 3) * (top - second) / top``. This makes one
    weak cue (``top=1``) insufficient and a near-tie (``3 vs 2``) low even when
    there are many cues, so ambiguous stems go to the model or to the generic
    profile instead of being forced into a domain.
    """

    def detect(self, text: str) -> DetectedDomain:
        lowered = text.lower()
        scores = {
            domain: sum(weight for term, weight in terms if term in lowered)
            for domain, terms in _TERMS.items()
        }
        if _MATH_FORMULA.search(text):
            scores["math"] += 2
        if _PHYSICS_UNIT.search(text):
            scores["physics"] += 2

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        domain, top = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0
        if top <= 0:
            return DetectedDomain(None, 0.0, "none")

        evidence = min(1.0, top / 3.0)
        margin = (top - second) / top
        confidence = round(evidence * margin, 3)
        if confidence < MIN_CONFIDENCE:
            return DetectedDomain(None, confidence)
        return DetectedDomain(domain, confidence)


class CascadeDomainDetector:
    """Try deterministic detectors first; the model only sees undecided stems.

    The first detector's non-decisive result is returned when no later detector
    is confident, so the caller still learns *how close* the cheap pass was
    (the intake view uses that confidence to decide whether to ask one
    clarifying question).
    """

    def __init__(self, *detectors: DomainDetector) -> None:
        self._detectors = tuple(detectors)

    def detect(self, text: str) -> DetectedDomain:
        first: DetectedDomain | None = None
        for detector in self._detectors:
            result = detector.detect(text)
            if first is None:
                first = result
            if result.domain is not None and result.confidence >= MIN_CONFIDENCE:
                return result
        if first is not None:
            return first
        return DetectedDomain(None, 0.0, "none")
