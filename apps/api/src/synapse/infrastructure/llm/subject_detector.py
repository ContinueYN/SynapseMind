"""Optional model classifier for ambiguous subject detection.

The deterministic detector in ``application.subject_detection`` handles the
common case without a network call. This adapter is only asked when that score
is not decisive, so a normal start does not pay for a second model round trip.
"""

from __future__ import annotations

import json
import re

from synapse.application.llm import LLMCallFailed, LLMClient, LLMRequest, LLMTimeout
from synapse.application.subject_detection import DetectedSubject

_SUBJECTS = frozenset({"math", "physics", "chinese"})
_TIMEOUT_S = 3.0
_MAX_STEM_CHARS = 2000

_SYSTEM = """你是学科分类器。只判断题目属于哪一科，不解题。
只输出一个 JSON 对象：
{"subject": "math|physics|chinese|unknown", "confidence": 0.0, "reason": "不超过 20 字"}
规则：
- math：数学，含函数、方程、不等式、导数、几何、概率、数列等；
- physics：物理，含力、速度、加速度、质量、能量、电路、光学等；
- chinese：语文，含阅读、文言文、赏析、概括、修辞、作文等；
- 无法判断时 subject 填 unknown，confidence 填 0。
不要输出 markdown、代码块或解释。"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"enum": ["math", "physics", "chinese", "unknown"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["subject", "confidence"],
}


class LLMSubjectDetector:
    def __init__(self, client: LLMClient, *, timeout_s: float = _TIMEOUT_S) -> None:
        self._client = client
        self._timeout_s = timeout_s

    def detect(self, text: str) -> DetectedSubject:
        request = LLMRequest(
            purpose="subject_detect",
            system=_SYSTEM,
            user=f"题目：{text[:_MAX_STEM_CHARS]}",
            schema_name="SubjectDetection",
            json_schema=_SCHEMA,
            max_tokens=120,
        )
        try:
            response = self._client.complete(request, timeout_s=self._timeout_s)
        except (LLMCallFailed, LLMTimeout):
            return DetectedSubject(None, 0.0, "model")
        return _parse(response.text)


def _parse(raw: str) -> DetectedSubject:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except (TypeError, ValueError):
        return DetectedSubject(None, 0.0, "model")
    if not isinstance(data, dict):
        return DetectedSubject(None, 0.0, "model")

    subject = data.get("subject")
    if not isinstance(subject, str) or subject.lower() not in _SUBJECTS:
        return DetectedSubject(None, 0.0, "model")
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if confidence < 0.5:
        return DetectedSubject(None, confidence, "model")
    return DetectedSubject(subject.lower(), confidence, "model")
