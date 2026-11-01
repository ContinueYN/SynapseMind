"""Turn a submission into a generic graph, without a model.

The generic graph needs a source before a key exists. The honest source is the
student's own text: if the attempt says "我想两周内上线，但不能加班，我试过改缓存",
then the submission *mentions* a goal, a constraint and an attempt, and a
structural check may say "没看到什么算解决". It may never say the goal is right.

So this is a cue scanner, not a parser:

* the text is split on sentence punctuation, newlines and Chinese commas, so one
  sentence can fill more than one slot ("我想…，但不能…");
* each clause is tested against a small hand-written cue table per node kind;
* a kind is recorded once per *clause*, except ``DECISION``: options are often
  written as one clause ("要么 A 要么 B", "A 还是 B"), so that clause is split on
  its option markers and each part becomes one option node. Two options must be
  countable, or the decision check would falsely say "只有一条路";
* the text is copied verbatim — nothing is summarised, rewritten or inferred;
* when no cue matches, nothing is recorded. An empty graph is a valid answer
  ("没看到任何结构"), not a failure.

The consequence is deliberately conservative: a coincidental cue can hide a real
gap (a missing constraint looks present), but it cannot invent a conclusion. For
a structure display that is the right trade-off; anything stronger needs a
verifier that can falsify, not a bigger cue table.
"""

from __future__ import annotations

import re
from typing import Protocol

from synapse.domain.problem.generic import GenericGraph, GenericNode, NodeKind

# Split on sentence punctuation, newlines and Chinese commas. Commas matter:
# "我想两周上线，但不能加班" is one sentence with a goal *and* a constraint, and
# treating it as one indivisible unit would report a false "没看到约束".
_CLAUSE_SPLIT = re.compile(r"[。！？；!?;\n，,、]+")
# Options are usually written inside one clause; these markers separate them.
_OPTION_SPLIT = re.compile(r"要么|还是|或者|任选")
_MIN_CLAUSE = 4

# Cues are multi-character on purpose: single characters ("要", "先", "想") occur
# in almost any sentence and would mark every slot present.
_CUES: dict[NodeKind, tuple[str, ...]] = {
    NodeKind.GOAL: (
        "我想",
        "我希望",
        "想要",
        "目标是",
        "我的目标",
        "为了",
        "需要解决",
        "打算",
        "想问",
    ),
    NodeKind.GIVEN: (
        "已知",
        "手上",
        "目前有",
        "现在有",
        "材料",
        "数据",
        "背景",
        "条件是",
        "给我",
    ),
    NodeKind.CONSTRAINT: (
        "不能",
        "必须",
        "只能",
        "预算",
        "截止",
        "期限",
        "最多",
        "至少",
        "不允许",
        "限制",
        "只有",
    ),
    NodeKind.ASSUMPTION: (
        "假设",
        "以为",
        "我猜",
        "大概会",
        "应该会",
    ),
    NodeKind.PLAN: (
        "计划",
        "准备",
        "思路",
        "方案是",
        "步骤",
        "因此",
        "所以",
        "推理",
    ),
    # EXECUTABLE's reproduction gap is ACTION, so a minimal-reproduction phrase
    # belongs here. Bare "复现" is deliberately not a cue: "没有复现" would
    # otherwise count as a reproduction. CHECK is for what was changed.
    NodeKind.ACTION: (
        "试过",
        "我做了",
        "我改了",
        "我写了",
        "跑了",
        "执行了",
        "尝试过",
        "已经改",
        "最小复现",
        "复现步骤",
        "复现方式",
    ),
    NodeKind.EVIDENCE: (
        "因为",
        "证据",
        "日志",
        "报错",
        "数据显示",
        "测试结果",
        "输出是",
        "traceback",
        "截图",
    ),
    NodeKind.CHECK: (
        "验证",
        "检查",
        "对比",
        "确认",
        "怎么判断",
        "算解决",
        "测一下",
    ),
    NodeKind.DECISION: (
        "还是",
        "或者",
        "要么",
        "选择",
        "纠结",
        "取舍",
        "二选一",
    ),
    NodeKind.RISK: (
        "风险",
        "担心",
        "我怕",
        "代价",
        "失去",
        "后果",
        "万一",
        "副作用",
    ),
    NodeKind.NEXT: (
        "下一步",
        "接下来",
        "先试",
        "试试",
        "再决定",
        "小实验",
        "可逆",
    ),
}


class SlotExtractor(Protocol):
    """Port: submission text -> mentioned nodes. Implementations are stateless."""

    def extract(self, problem_id: str, text: str) -> GenericGraph: ...


class CueSlotExtractor:
    """Deterministic cue scanner; the only extractor that works with no key."""

    def extract(self, problem_id: str, text: str) -> GenericGraph:
        nodes: list[GenericNode] = []
        seen: set[NodeKind] = set()
        for clause in _CLAUSE_SPLIT.split(text):
            candidate = clause.strip(" \t\r：:")
            if len(candidate) < _MIN_CLAUSE:
                continue
            for kind in self._classify(candidate):
                if kind is NodeKind.DECISION:
                    self._add_options(nodes, candidate)
                    continue
                if kind in seen:
                    continue
                seen.add(kind)
                nodes.append(self._node(nodes, kind, candidate))
        return GenericGraph(problem_id=problem_id, version="g1", nodes=tuple(nodes))

    @staticmethod
    def _add_options(nodes: list[GenericNode], clause: str) -> None:
        parts = [
            part.strip(" \t\r：:")
            for part in _OPTION_SPLIT.split(clause)
            if len(part.strip(" \t\r：:")) >= 3
        ]
        if len(parts) < 2:
            parts = [clause]
        known = {node.text for node in nodes if node.kind is NodeKind.DECISION}
        for part in parts:
            if part in known:
                continue
            nodes.append(CueSlotExtractor._node(nodes, NodeKind.DECISION, part))
            known.add(part)

    @staticmethod
    def _node(nodes: list[GenericNode], kind: NodeKind, text: str) -> GenericNode:
        return GenericNode(id=f"GN{len(nodes) + 1}", kind=kind, text=text)

    @staticmethod
    def _classify(clause: str) -> tuple[NodeKind, ...]:
        """Every kind the clause mentions.

        One clause may mention a goal *and* a constraint. Recording only the
        first would produce a false "没看到约束", which is exactly the sentence
        this feature must never say. Recording a coincidental match only hides a
        gap, which is the safe direction.
        """

        lowered = clause.lower()
        return tuple(kind for kind in NodeKind if any(cue in lowered for cue in _CUES[kind]))
