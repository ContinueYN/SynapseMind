"""Pick a subject plugin from the stem when the caller did not declare one.

The API used to default a missing subject to ``math``. That is no longer a
viable generic entry: the student should not have to classify the problem, and
silently treating a Chinese or physics stem as math produces a confident card
for the wrong graph. Detection is deliberately conservative:

* deterministic term/formula scoring runs first;
* a model classifier is only consulted when the score is not decisive;
* if neither is confident, the resolver returns 422 instead of guessing.

The detector only chooses *which plugin* builds the graph. It never writes a
diagnosis or selects a dialogue state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

MIN_CONFIDENCE = 0.6

# Weights are intentionally small and hand-checked. A single weak cue is not
# enough to pass ``MIN_CONFIDENCE``; two strong cues are.
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
}

_MATH_FORMULA = re.compile(r"[A-Za-z]\s*\([A-Za-z]+\)|[=<>≤≥]|[+\-*/^]|√|∫|∑")
_PHYSICS_UNIT = re.compile(r"(?<![A-Za-z])(?:kg|m/s\^?2|m/s|Ω|Pa|Hz|mol)(?![A-Za-z])")


@dataclass(frozen=True, slots=True)
class DetectedSubject:
    subject: str | None
    confidence: float
    method: str = "heuristic"


class SubjectDetector(Protocol):
    def detect(self, text: str) -> DetectedSubject: ...


class HeuristicSubjectDetector:
    """Term counting with a margin-aware confidence.

    ``confidence = min(1, top / 3) * (top - second) / top``. This makes one
    weak cue (``top=1``) insufficient and a near-tie (``3 vs 2``) low even when
    there are many cues, so ambiguous stems go to the model or to 422.
    """

    def detect(self, text: str) -> DetectedSubject:
        scores = {
            subject: sum(weight for term, weight in terms if term in text)
            for subject, terms in _TERMS.items()
        }
        if _MATH_FORMULA.search(text):
            scores["math"] += 2
        if _PHYSICS_UNIT.search(text):
            scores["physics"] += 2

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        subject, top = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0
        if top <= 0:
            return DetectedSubject(None, 0.0, "none")

        evidence = min(1.0, top / 3.0)
        margin = (top - second) / top
        confidence = round(evidence * margin, 3)
        if confidence < MIN_CONFIDENCE:
            return DetectedSubject(None, confidence)
        return DetectedSubject(subject, confidence)


class CompositeSubjectDetector:
    """Use the model only when the deterministic detector is not decisive."""

    def __init__(
        self,
        heuristic: SubjectDetector,
        fallback: SubjectDetector | None = None,
    ) -> None:
        self._heuristic = heuristic
        self._fallback = fallback

    def detect(self, text: str) -> DetectedSubject:
        first = self._heuristic.detect(text)
        if first.confidence >= MIN_CONFIDENCE or self._fallback is None:
            return first
        second = self._fallback.detect(text)
        if second.subject is not None and second.confidence >= MIN_CONFIDENCE:
            return second
        return first
