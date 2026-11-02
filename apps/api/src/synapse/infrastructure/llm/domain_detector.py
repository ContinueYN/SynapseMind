"""Optional model classifier for ambiguous domain labels (Phase 0).

The deterministic detector in ``application.diagnosis.domain_detection`` handles the
common case without a network call. This adapter is only asked when that score
is not decisive, so a normal start does not pay for a second model round trip.

The label vocabulary is **open**: the model may answer any short slug, and an
unregistered slug keeps the caller's label while behaving as generic mode. The
model still cannot pick a graph, a probe or a state; it only supplies a label
and a confidence, both of which the caller may discard.
"""

from __future__ import annotations

import json
import re

from synapse.application.diagnosis.domain_detection import DetectedDomain
from synapse.application.shared.llm import LLMCallFailed, LLMClient, LLMRequest, LLMTimeout

_TIMEOUT_S = 3.0
_MAX_STEM_CHARS = 2000
_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

_SYSTEM = """你是领域分类器。只判断问题属于哪个领域，不解题。
只输出一个 JSON 对象：
{"domain": "math|physics|chemistry|biology|chinese|writing|research",
 "confidence": 0.0, "reason": "不超过 20 字"}
domain 还可以是 programming / decision / work / generic，或英文小写短标签。
规则：
- math：数学题、证明、求范围；
- physics / chemistry / biology：物理、化学、生物的计算或实验设计；
- chinese：中文阅读、文言文、作文、病句；
- writing：非中文的写作、essay、段落结构；
- research：论文、文献、研究设计、统计与证据；
- programming：代码、报错、调试、算法与复杂度；
- decision：该不该、选哪个、取舍与风险这类个人决策；
- work：团队协作、流程、产品与职场问题；
- generic：确实判断不了，或不属于以上任何一类。
- 不要因为题目“像考试题”就判成 math；按问题本身判断。
域名用英文小写短标签，不要输出 markdown、代码块或解释。"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "minLength": 1, "maxLength": 32},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["domain", "confidence"],
}


class LLMDomainDetector:
    def __init__(self, client: LLMClient, *, timeout_s: float = _TIMEOUT_S) -> None:
        self._client = client
        self._timeout_s = timeout_s

    def detect(self, text: str) -> DetectedDomain:
        request = LLMRequest(
            purpose="domain_detect",
            system=_SYSTEM,
            user=f"问题：{text[:_MAX_STEM_CHARS]}",
            schema_name="DomainDetection",
            json_schema=_SCHEMA,
            max_tokens=120,
        )
        try:
            response = self._client.complete(request, timeout_s=self._timeout_s)
        except (LLMCallFailed, LLMTimeout):
            return DetectedDomain(None, 0.0, "model")
        return _parse(response.text)


def _parse(raw: str) -> DetectedDomain:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except (TypeError, ValueError):
        return DetectedDomain(None, 0.0, "model")
    if not isinstance(data, dict):
        return DetectedDomain(None, 0.0, "model")

    domain = data.get("domain")
    if not isinstance(domain, str):
        return DetectedDomain(None, 0.0, "model")
    label = domain.strip().lower()
    if label in {"", "unknown", "generic"}:
        return DetectedDomain(None, 0.0, "model")
    if not _LABEL.match(label):
        return DetectedDomain(None, 0.0, "model")
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if confidence < 0.5:
        return DetectedDomain(None, confidence, "model")
    return DetectedDomain(label, confidence, "model")
