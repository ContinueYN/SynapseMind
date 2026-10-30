"""LLM-backed solution-graph builder (M2.5 S4).

Pipeline for one problem, exactly as chapter 13 §13.5 describes it:

    prompt -> JSON -> tolerant parse -> mechanical repair -> structural rules
           -> specs/solution-graph.schema.json -> success, or one retry

The schema is loaded from ``specs/`` rather than duplicated into Pydantic
models, so the contract stays single-sourced. The model is told what is wrong
on the retry (errors only, not the previous output) and gets exactly one
chance, matching the failure table in §13.5.

What the model controls: the decomposition, the wording of steps and probes.
What it cannot control: the problem id, the graph version, the probe target
vocabulary, or whether the result is accepted.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from synapse.application import trace
from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.graph import (
    GraphBuildFailed,
    GraphBuildResult,
    GraphFailureReason,
)
from synapse.application.llm import (
    LLMCallFailed,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.application.verification import (
    GraphVerifier,
    VerificationResult,
    describe_claim,
)
from synapse.domain.diagnosis.hypotheses import HYPOTHESES
from synapse.domain.problem.graph_structure import (
    GraphCheck,
    fingerprint,
    quality_notes,
    review,
)
from synapse.domain.problem.models import (
    Interval,
    Probe,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
    VerificationClaim,
)
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.verification import default_verifier

GRAPH_MAX_TOKENS = 4096
GRAPH_CACHE_SIZE = 128
PROBLEM_ID_PATTERN = re.compile(r"^P_[A-Z0-9_]+$")

# A claim repair returns a handful of interval endpoints, not a graph: its
# completion is bounded separately and it never re-emits nodes/probes. The
# minimum budget is the point below which starting the call can only produce a
# timeout, so the builder drops the claim instead (ADR-0004 §5.4).
CLAIM_REPAIR_MAX_TOKENS = 400
CLAIM_REPAIR_MIN_BUDGET_S = 1.0

# The diagnosis layer is still the M1 one (H_L1/L2/L4), so a generated probe
# must separate two of those hypotheses. S5 replaces the vocabulary together
# with the evidence table.
ALLOWED_PROBE_TARGETS = frozenset(HYPOTHESES)

GRAPH_SYSTEM_PROMPT = """你是高中数学解法图标注器。输入一道高中数学题，输出一张“解法图”JSON。
解法图描述解这道题需要完成的认知步骤，不是完整演算稿。
硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释。顶层只有 nodes / edges（外加可选的 claim），
   探针必须写在**所属节点内部的 probes 数组**里，不要放到顶层：
   {"nodes": [
      {"id": "n1", "type": "READ", "text": "...", "demand": {"V": 0.2},
       "probes": [
         {"id": "p1", "question": "...", "options": ["...", "...", "..."],
          "targets": ["H_L2", "H_L1"],
          "evidence": {"A": {"H_L2": -0.4, "H_L1": 0.2},
                       "B": {"H_L2": 0.35, "H_L1": -0.1},
                       "C": {"H_L1": 0.3}}}
       ]}
    ],
    "edges": [["n1", "n2"]],
    "claim": {...}}
2. nodes 为 5–7 个（硬上限 20）；id 从 n1 连续编号；
   text 不超过 40 字，写这一步做什么，不写最终答案。
3. type 只能是 READ / CONCEPT / CONDITION / STRATEGY / TRANSFORM / COMPUTE / CHECK 之一。
4. demand 只填与这一步相关的维度，取值 0–1：
   V 符号识别、Gf 推理、Gv 空间、WM 工作记忆、Gs 加工速度、LTS 长时记忆、M 元认知。
5. edges 的每一项是 [前置节点, 后继节点]，必须无环；
   第一个节点是 READ，最后一个节点是 CHECK；每个节点至少与另一个节点相连。
6. 整张图**5 个**探针（4–5 个，不要超过 5 个）：只挂在真正能区分假设的 3–4 个节点上，
   其余节点不要写 probes。探针一次只问一个小问题，选项**恰好 3 个**，不给答案。
   每个探针的问题和选项都要短（选项不超过 15 字），整张图越短越好，
   这是一次同步调用，输出长度直接等于学生等待的时间。
   同一个假设在选项上必须既有正的权重也有负的权重：只有一边的话，这个探针
   要么只能抬高它、要么只能压低它，学生答了也攒不出领先差距。
7. 每个探针的 targets 至少写 2 个假设 id，只能从 H_L1、H_L2、H_L4 中选：
   H_L1=概念不清（定义、定理条件）；H_L2=条件转译/参数分类；H_L4=执行/计算错误。
   整张图的探针合起来必须覆盖三个假设：H_L1、H_L2、H_L4 每个都至少出现在一个探针的 targets 里。
8. 不要复述题目，不要输出答案（claim 字段除外，见第 11 条）。
9. 每个探针的每个选项都必须有 evidence；键 A/B/C 依次对应 options 的第 1/2/3 个。
   evidence 的值是 log-odds 权重，范围 -1~1：正数表示选这个选项支持该假设，
   负数表示反对；0 等于没写，不要用。
   权重必须用满量程，不要客气：每个探针至少有一个选项的某个权重达到 ±0.8~1.0，
   不要把所有选项都写成 ±0.3~0.6。权重太弱时，6 轮探针也攒不出可判定的后验，
   这张图就白生成了。
10. evidence 里只能出现该探针 targets 中的假设；每个 target 至少要在一个选项上有非零权重；
    同一探针要让至少两个假设拿到方向相反的权重，否则这个探针没有区分度，不要设。
    同一个假设在不同选项上的权重必须拉开：差值至少 1.0，例如某选项给 H_L2 写 +0.9，
    另一个选项给 H_L2 写 -0.5。差值太小等于没问。
    选项代表“这一层没问题”时就给该层接近 -1 的权重，代表“卡在这一层”时就给接近 +1 的权重。
11. 如果题目是“含参数的不等式对定义域内所有 x 恒成立，求参数的取值范围”，**必须**输出 claim，
    把答案写成可验证的形式；其它题型（求一个值、求零点个数、解方程/解集、证明）**不要**输出 claim。
    符合条件的题不写 claim 就等于放弃校验，不要因为答案看起来简单或拿不准就省略。
    claim 的形状：
    "claim":{"kind":"parameter_range","parameter":"a","variable":"x","variable_domain":"(0,+inf)",
             "constraint":{"expression":"log(x)-a*x","relation":"<="},
             "answer":[{"lower":"1/E","upper":null,"lower_inclusive":true,"upper_inclusive":false}]}
    含义：对所有 x∈variable_domain 都有 expression <relation> 0，当且仅当 parameter ∈ answer。
    例：“x^2-a x+1>0 对任意 x∈R 恒成立，求 a 的取值范围”，答案应写成
        {"kind":"parameter_range","parameter":"a","variable":"x","variable_domain":"(-inf,+inf)",
         "constraint":{"expression":"x^2-a*x+1","relation":">"},
         "answer":[{"lower":"-2","upper":"2","lower_inclusive":false,"upper_inclusive":false}]}
    因为 a=±2 时左边可以等于 0，端点必须排除。
    - expression 只用题目的变量、参数和 exp/log/sqrt/Abs/sin/cos 与 + - * / ^；
      乘号可省略（a x 就是 a*x），e 写成 e 或 E，log_2(x) 表示以 2 为底的对数。
    - variable_domain 用区间写法：(0,+inf)、[1,3]、(-inf,+inf)；写无穷的一端必须用圆括号。
    - answer 的端点是数学表达式字符串（如 "0"、"1/E"、"E"）；−∞/+∞ 用 null；
      含端点写 true，不含写 false。
    - 端点必须逐个代回约束检查：把这个端点当作 parameter 代入，若约束成立就必须包含（true），
      不成立就必须排除（false）。分类讨论时先列出所有满足条件的参数值（包括 0、负数、边界值），
      再写成区间；不要用“a>0”直接替换“a≥0”。
    - 负参数分支不能省略：a≤0 时先看 x→−∞ 与 x→+∞ 的极限；若负的一次项会把函数拖到 −∞，
      极限就不满足，负参数整段都要排除；不要拿 a>0 时的最值结论覆盖 a≤0。
    - 对 a<0 的分支代一个具体负数（如 a=−1）与足够小的 x 做数值检查；不满足就把这一段删掉。
    - 写区间前做三个检查：parameter=0、parameter<0、variable→±∞。三项都过不了的区间必须收紧或删掉。
    - relation 只表示恒成立的方向：题目要求 f(x)≥0 恒成立就写 ">="，f(x)≤0 恒成立就写 "<="；
      "="、"!=" 或其它关系不要写 claim。
    - 判断标准是“条件能不能写成对 x 的恒成立不等式”：条件里有“存在 x”“有两个零点”“方程有解”
      这类存在性说法时，不要写 claim（形态不对会被判为无法验证）。确实属于“恒成立求参数范围”的
      题目必须写；端点拿不准就把端点逐个代回约束检验，不要靠印象。
    - 再确认一次：nodes 和 probes 是必填部分，claim 是可选部分；不要因为写 claim 而省掉探针，
      每个探针仍然要有 2–4 个选项和完整的 evidence。
12. 探针属于某个节点：写在那个节点的 "probes" 里。把探针放到顶层、或写成节点数组之外，
    整张图会被判为无效。"""


_CLAIM_CHECKLIST = (
    "检查清单：\n"
    "- 反例的含义：参数落在答案内却违反约束 → 这一段偏宽，必须收紧或删掉；"
    "参数落在答案外却满足约束 → 区间偏窄，必须补上。\n"
    "- 写区间前逐个检查：parameter=0、parameter<0（先看 variable→−∞ 与 variable→+∞ 的极限）、"
    "每个端点代回约束。端点拿不准就代回去，不要靠印象。\n"
    "- 负参数分支不能省略，也不能用参数为正时的最值结论覆盖它。"
)

# A refuted claim only needs its interval rewritten. Asking for a whole graph
# again costs a full completion and is what pushed the slow tail to ≈7.6 s; a
# claim-only reply is a few dozen tokens (ADR-0004 §5.4). The formalisation is
# pinned by the caller: the response may not move the goalposts by editing f(x).
CLAIM_REPAIR_SYSTEM_PROMPT = (
    "你是高中数学答案校验器。你已经为一道题写好了形式化断言，但答案区间被反例推翻。\n"
    "现在只重写参数区间：不要重新解题，不要改动表达式、关系、参数与定义域。\n"
    "输出只有一个 JSON 对象，不要 markdown、代码块或解释：\n"
    '{"answer":[{"lower":"0","upper":"E","lower_inclusive":true,"upper_inclusive":true}]}\n'
    "要求：\n"
    '- answer 是非空的区间数组；端点是数学表达式字符串（如 "0"、"1/E"、"E"），'
    "无界的一端写 null；含端点写 true，不含写 false。\n"
    "- 区间从小到大排列，互不重叠。\n"
    '- 如果你判断不存在满足条件的参数区间，输出 {"answer":null}。\n' + _CLAIM_CHECKLIST
)

# ``verification_malformed`` means the verifier could not even read the claim
# (unknown symbol, empty endpoint, unparsable expression). Pinning the
# expression would pin the defect, so this variant allows rewriting the whole
# claim — still without touching the graph.
CLAIM_REWRITE_SYSTEM_PROMPT = (
    "你是高中数学答案校验器。你已经为一道题写好了形式化断言，但验证器读不懂它。\n"
    "现在重写整个 claim：不要重新解题，也不要改变题目的含义。\n"
    "输出只有一个 JSON 对象，不要 markdown、代码块或解释：\n"
    '{"claim":{"kind":"parameter_range","parameter":"a","variable":"x",'
    '"variable_domain":"(-inf,+inf)",'
    '"constraint":{"expression":"x^2-a*x+1","relation":">"},'
    '"answer":[{"lower":"-2","upper":"2","lower_inclusive":false,"upper_inclusive":false}]}}\n'
    "要求：\n"
    "- kind 只能是 parameter_range；relation 只能是 <=、>=、<、>；"
    "expression 只用题目变量、参数与 exp/log/sqrt/Abs/sin/cos 与 + - * / ^。\n"
    "- variable_domain 用区间写法；写无穷的一端必须用圆括号。\n"
    "- answer 的端点是常数表达式字符串；无界写 null；含端点写 true。\n"
    '- 如果你判断这道题没有可验证的参数区间，输出 {"claim":null}。\n' + _CLAIM_CHECKLIST
)


PHYSICS_SYSTEM_PROMPT = """你是高中物理解法图标注器。输入一道高中物理题，输出一张“解法图”JSON。
解法图描述解这道题需要完成的认知步骤，不是完整演算稿。物理题的重点是：
读题与单位 → 选研究对象/物理模型 → 受力或过程分析 → 列方程 → 求解 → 单位/量级/边界检验。
硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释。顶层只有 nodes / edges，
   探针必须写在**所属节点内部的 probes 数组**里，不要放到顶层：
   {"nodes": [
      {"id": "n1", "type": "READ", "text": "...", "demand": {"V": 0.2},
       "probes": [
         {"id": "p1", "question": "...", "options": ["...", "...", "..."],
          "targets": ["H_L1", "H_L2"],
          "evidence": {"A": {"H_L1": -0.9, "H_L2": 0.4},
                       "B": {"H_L1": 0.9, "H_L2": -0.3},
                       "C": {"H_L2": 0.8, "H_L1": -0.2}}}
       ]}
    ],
    "edges": [["n1", "n2"]]}
2. nodes 为 5–7 个（硬上限 20）；id 从 n1 连续编号；text 不超过 40 字，
   写这一步做什么，不写最终数值答案。
3. type 只能是 READ / CONCEPT / CONDITION / STRATEGY / TRANSFORM / COMPUTE / CHECK 之一。
   物理建议：READ 读题与单位，CONCEPT 选定律/公式，CONDITION 受力/过程条件，
   STRATEGY 分段/正方向/参考系，TRANSFORM 列方程或分解，COMPUTE 代入求解，CHECK 检验。
4. demand 只填与这一步相关的维度，取值 0–1：
   V 符号识别、Gf 推理、Gv 空间、WM 工作记忆、Gs 加工速度、LTS 长时记忆、M 元认知。
5. edges 的每一项是 [前置节点, 后继节点]，必须无环；第一个节点是 READ，最后一个节点是 CHECK；
   每个节点至少与另一个节点相连。
6. 整张图**5 个**探针（4–5 个，不要超过 5 个）：只挂在真正能区分假设的 3–4 个节点上，
   其余节点不要写 probes。探针一次只问一个小问题，选项**恰好 3 个**，不给最终答案或数值。
   问题和选项都要短（选项不超过 15 字），输出长度直接等于学生等待的时间。
   同一个假设在选项上必须既有正的权重也有负的权重，否则这个探针只能单向移动它。
7. 每个探针的 targets 至少写 2 个假设 id，只能从 H_L1、H_L2、H_L4 中选：
   H_L1=概念/公式条件不清（定律适用条件、研究对象或参考系选错）；
   H_L2=物理模型/条件转译（过程阶段、正方向、守恒/临界条件没转成方程）；
   H_L4=执行/计算错误（代入、单位换算、矢量分解、代数）。
   整张图的探针合起来必须覆盖三个假设：H_L1、H_L2、H_L4 每个都至少出现在一个探针的 targets 里。
8. 不要复述题目，不要输出答案或最终数值。
9. 每个探针的每个选项都必须有 evidence；键 A/B/C/D 依次对应 options 的第 1/2/3/4 个。
   evidence 的值是 log-odds 权重，范围 -1~1：正数表示选这个选项支持该假设，
   负数表示反对；0 等于没写，不要用。
   权重必须用满量程：每个探针至少有一个选项的某个权重达到 ±0.8~1.0，不要都写成 ±0.3~0.6。
10. evidence 里只能出现该探针 targets 中的假设；每个 target 至少要在一个选项上有非零权重；
    同一探针要让至少两个假设拿到方向相反的权重，否则这个探针没有区分度，不要设。
    同一个假设在不同选项上的权重必须拉开：差值至少 1.0。
    选项代表“这一层没问题”时给该层接近 -1 的权重，代表“卡在这一层”时给接近 +1 的权重。
11. **物理图不要输出 claim。** v1 的 SymPy 验证器只覆盖数学参数范围，物理答案带单位、矢量
    或实验条件，硬套会给出错误的“已核对”。把检验写进 CHECK 节点的 text（单位、量级、
    边界/极限、极端情况），不要写 claim 字段。
12. 探针属于某个节点：写在那个节点的 "probes" 里。把探针放到顶层、或写成节点数组之外，
    整张图会被判为无效。"""


CHINESE_SYSTEM_PROMPT = """你是高中语文解法图标注器。
输入一道高中语文题（现代文阅读、古诗文阅读、写作），输出一张“解题步骤图”JSON。
这张图只描述**答题需要完成的认知动作**，不写答案、不写范文。
语文题的重点是：读题干与限制语 → 定题型与答题角度 → 定位原文/确定依据 → 提取并转写要点
→ 组织成文（分点、术语、结合原文） → 检查扣题与分值。

硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释。顶层只有 nodes / edges：
   {"nodes": [
      {"id": "n1", "type": "READ", "text": "...", "demand": {"V": 0.2}},
      {"id": "n2", "type": "CONDITION", "text": "...", "demand": {"WM": 0.4}}
    ],
    "edges": [["n1", "n2"]]}
2. nodes 为 3–10 个（硬上限 20）；id 从 n1 连续编号；text 不超过 60 字，
   写这一步要做什么，不写答案内容，也不要复述题干。
3. type 只能是 READ / CONCEPT / CONDITION / STRATEGY / TRANSFORM / COMPUTE / CHECK 之一。
   语文建议：READ 读题干、圈出限制语与分值；CONCEPT 判定题型/文体/答题角度；
   CONDITION 定位原文区间、确认依据与筛选条件；STRATEGY 选答题框架、判定手法；
   TRANSFORM 把原文信息转成要点；COMPUTE 分点组织语言、写完整句子；
   CHECK 检查扣题、要点齐全、分值对应、有无错别字。
4. demand 只填与这一步相关的维度，取值 0–1：
   V 符号识别、Gf 推理、Gv 空间、WM 工作记忆、Gs 加工速度、LTS 长时记忆、M 元认知。
5. edges 的每一项是 [前置节点, 后继节点]，必须无环；第一个节点是 READ，最后一个节点是 CHECK；
   每个节点至少与另一个节点相连。
6. **不要输出探针（probes）。** 该学科不做追问，探针会被直接丢弃；写了也只是浪费长度。
   同理**不要输出 claim**：语文答案没有被自动验证的手段，任何“答案已验证”的字段都不该出现。
7. 每个节点都必须能在学生作答里**看出来有没有做到**：写“定位第 3 段的关键句”“点出比喻的作用”，
   不要写“理解文章”“体会情感”这类无法观察的动作。
8. 不要给出答案、范文或得分点全文；这张图是步骤，不是标准答案。
9. 步骤之间要能看出先后依赖：没有前一步的产出，后一步写不出来。"""


@dataclass(frozen=True, slots=True)
class _GraphProfile:
    """Per-subject generation contract (M2.5 S4/S6/S7).

    ``probes``/``claim`` say what the tier can actually use. A NONE-tier
    subject never asks a probe and has no verifier, so its graph is generated
    without either; asking the model for them would cost tokens and imply a
    promise the product does not make.

    ``version`` is the audit/cache label of *this* prompt. A subject whose
    prompt text did not change keeps its old label when the math prompt is
    revised; otherwise an audit row would claim a prompt revision that never
    happened. Empty means "use ``settings.graph_prompt_version``" (math).
    """

    system: str
    probes: bool
    claim: bool
    version: str = ""


_PROFILES: dict[str, _GraphProfile] = {
    "math": _GraphProfile(GRAPH_SYSTEM_PROMPT, probes=True, claim=True),
    "physics": _GraphProfile(
        PHYSICS_SYSTEM_PROMPT, probes=True, claim=False, version="graph-v9-physics"
    ),
    "chinese": _GraphProfile(
        CHINESE_SYSTEM_PROMPT, probes=False, claim=False, version="graph-v6-chinese"
    ),
}


def _profile(subject: str) -> _GraphProfile:
    # An unregistered subject cannot reach the generator (the resolver refuses
    # it first); defaulting to the math profile keeps the failure mode readable
    # instead of inventing a fourth shape.
    return _PROFILES.get(subject, _PROFILES["math"])


def _system_prompt(subject: str) -> str:
    return _profile(subject).system


def _prompt_version(settings: LLMSettings, subject: str) -> str:
    """Audit label; math still follows the environment override."""

    profile = _profile(subject)
    return profile.version or settings.graph_prompt_version


_ISSUE_HINTS = {
    "bad_json": "只输出一个合法 JSON 对象",
    "not_object": "只输出一个 JSON 对象",
    "edge_shape": "edges 的每一项必须是 [前置, 后继]",
    "duplicate_node_id": "节点 id 不能重复",
    "node_count": "节点数必须在 3–20 之间",
    "no_edges": "节点之间必须用 edges 连接",
    "unknown_node_type": "type 只能取允许的七种认知动作",
    "empty_node_text": "每个节点都要有步骤描述",
    "isolated_node": "每个节点都必须接入解法流程",
    "empty_probe_id": "探针必须有 id",
    "empty_probe_question": "探针必须有问题文本",
    "probe_options_too_few": "每个探针至少要有 2 个选项",
    "probe_targets_too_few": "每个探针至少指向 2 个假设",
    "probe_target_unknown": "探针 targets 只能取 H_L1 / H_L2 / H_L4",
    "no_probes": "解法图至少要有一个探针",
    "probes_top_level": "探针必须写在所属节点的 probes 数组里，不能放在顶层",
    "probe_evidence_missing": "每个探针的每个选项都要有 evidence 权重",
    "probe_evidence_option_missing": "选项 A/B/C 每一个都要有 evidence",
    "probe_evidence_empty": "选项权重不能全为 0，否则答了也不更新后验",
    "probe_evidence_target_unknown": "evidence 的假设键必须在该探针的 targets 里",
    "probe_evidence_target_unused": "每个 target 至少在一个选项上有非零权重",
    "probe_evidence_no_contrast": "同一探针的权重必须有正有负，否则无法区分假设",
    "evidence_option_dropped": "evidence 的选项键只能是 A/B/C，并与 options 数量一致",
    "evidence_value_dropped": "evidence 的权重必须是有限数字",
    "evidence_clamped": "evidence 权重必须在 -1~1 之间",
    "claim_expression_empty": "claim 必须给出约束表达式",
    "claim_answer_empty": "claim 必须给出至少一个答案区间",
    "claim_endpoint_empty": "区间端点不能是空字符串；无界的一端写 null",
    "claim": "claim 必须是第 11 条描述的对象",
    "claim.constraint": "claim.constraint 必须是含 expression 与 relation 的对象",
    "claim.answer": "claim.answer 必须是非空的区间数组",
    "claim.answer[0]": "claim.answer 的每一项必须是含 lower 与 upper 的对象",
    "verification_counterexample": (
        "答案区间与约束不一致：偏宽就收紧或删掉这一段，偏窄就补上漏掉的区间"
        "（尤其检查 0、负数分支和端点是否包含）；修完后重新检查端点。"
        "若反例的 parameter<0，说明答案里的负参数段已被推翻：除非你能证明该段整体满足约束，"
        "否则删除所有 parameter<0 的取值；保留已知反例所在的分支就是错的。"
        "不要用参数为正时的最值结论覆盖负参数分支。"
    ),
    "verification_malformed": (
        "claim 写法不符合要求：只用量词变量与参数、exp/log/sqrt/Abs/sin/cos；端点必须是常数"
    ),
}

_DEGENERATE_CODES = frozenset({"node_count", "no_edges", "isolated_node", "no_probes"})


class _Rejected(Exception):
    def __init__(self, reason: GraphFailureReason, issues: Sequence[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class _ClaimRepair:
    """Outcome of the claim-only repair call.

    ``attempted`` distinguishes "the budget said no" from "the call ran and was
    not accepted"; the builder turns those into ``retry_skipped_budget`` versus
    ``claim_retry_*`` repair codes.
    """

    attempted: bool
    claim: VerificationClaim | None = None
    verification: VerificationResult | None = None
    codes: tuple[str, ...] = ()


class _ProbePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    evidence: dict[str, dict[str, float]] = Field(default_factory=dict)
    hint_level: int = 0


class _NodePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str
    type: str
    text: str
    demand: dict[str, float] = Field(default_factory=dict)
    common_errors: list[str] = Field(default_factory=list)
    probes: list[_ProbePayload] = Field(default_factory=list)


class _GraphPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nodes: list[_NodePayload]
    edges: list[list[str]] = Field(default_factory=list)


def build_request(draft: ProblemDraft, *, issues: Sequence[str] = ()) -> LLMRequest:
    """One generation request; ``issues`` carries the previous attempt's errors."""
    user = (
        f"学科：{draft.subject}\n"
        f"学段：{draft.grade}\n"
        f"题目：\n{draft.text.strip()}\n\n"
        "请输出解法图 JSON。"
    )
    feedback = _feedback(issues)
    if feedback:
        # The retry is the second half of the first-question budget: a minimal
        # graph that passes the rules is worth more than a rich one that costs
        # another four seconds of generation (chapter 12 §12.8).
        user += (
            "\n\n上一次输出未通过校验，必须修正以下问题后重新输出完整 JSON：\n"
            f"{feedback}\n\n"
            "这次请输出**最小可用图**：5 个节点、3 个探针，宁短勿长；"
            "结构规则与证据规则一条都不能少。"
        )
    return LLMRequest(
        purpose="graph_build",
        system=_system_prompt(draft.subject),
        user=user,
        schema_name="solution_graph",
        json_schema=None,
        max_tokens=GRAPH_MAX_TOKENS,
    )


def build_claim_repair_request(
    draft: ProblemDraft,
    claim: VerificationClaim,
    verification: VerificationResult,
) -> LLMRequest:
    """The second call after a refuted claim: intervals only, no graph.

    The problem and the pinned formalisation are repeated so the model repairs
    the same statement it wrote; the counterexample is the only new evidence.
    """
    malformed = verification.reason == "malformed"
    lines = [
        f"学科：{draft.subject}",
        f"学段：{draft.grade}",
        "题目：",
        draft.text.strip(),
        "",
        f"原来的形式化断言：{describe_claim(claim)}",
        f"表达式：{claim.expression}",
        f"关系：{claim.relation}",
        f"参数：{claim.parameter}",
        f"变量：{claim.variable}",
        f"定义域：{claim.variable_domain}",
        f"上次验证结论：{verification.status}/{verification.reason}",
    ]
    counter = verification.counterexample
    if counter is not None:
        witness = f"，{counter.variable}={counter.variable_value}" if counter.variable_value else ""
        lines.append(f"反例：{counter.parameter}={counter.parameter_value}{witness}")
    if verification.detail:
        lines.append(f"说明：{verification.detail}")
    lines.append(f"验证问题：{verification.as_issue()}")
    if malformed:
        lines += [
            "",
            "上面的形式化无法被验证器解析。请重写整个 claim，只输出：",
            '{"claim":{...}}；如果这道题没有可验证的参数区间，输出 {"claim":null}。',
        ]
    else:
        lines += [
            "",
            "只重写 answer（参数区间），只输出：",
            '{"answer":[...]}；如果不存在满足条件的参数区间，输出 {"answer":null}。',
            "不要改动表达式、关系、参数与定义域。",
        ]
    return LLMRequest(
        purpose="graph_claim_repair",
        system=CLAIM_REWRITE_SYSTEM_PROMPT if malformed else CLAIM_REPAIR_SYSTEM_PROMPT,
        user="\n".join(lines),
        schema_name="claim_answer",
        json_schema=None,
        max_tokens=CLAIM_REPAIR_MAX_TOKENS,
    )


def to_payload(graph: SolutionGraph) -> dict[str, object]:
    """Serialise a graph into the shape the spec validates.

    ``Probe.correct_option`` is deliberately absent: the schema forbids it and
    the builder never receives answer keys.
    """
    payload: dict[str, object] = {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "stem": graph.stem,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "text": node.text,
                "demand": dict(node.demand),
                "common_errors": list(node.common_errors),
                "probes": [
                    {
                        "id": probe.id,
                        "question": probe.question,
                        "options": list(probe.options),
                        "targets": list(probe.targets),
                        "evidence": {
                            option: dict(weights) for option, weights in probe.evidence.items()
                        },
                        "hint_level": probe.hint_level,
                    }
                    for probe in node.probes
                ],
            }
            for node in graph.nodes
        ],
        "edges": [[source, target] for source, target in graph.edges],
    }
    if graph.claim is not None:
        payload["claim"] = claim_payload(graph.claim)
    return payload


def claim_payload(claim: VerificationClaim) -> dict[str, object]:
    """The claim in the shape ``specs/solution-graph.schema.json`` publishes."""
    return {
        "kind": claim.kind,
        "parameter": claim.parameter,
        "variable": claim.variable,
        "variable_domain": claim.variable_domain,
        "constraint": {"expression": claim.expression, "relation": claim.relation},
        "answer": [
            {
                "lower": interval.lower,
                "upper": interval.upper,
                "lower_inclusive": interval.lower_inclusive,
                "upper_inclusive": interval.upper_inclusive,
            }
            for interval in claim.intervals
        ],
    }


def validate_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Run the real spec; returns human-readable errors, empty when valid."""
    validator = Draft202012Validator(_solution_graph_schema())
    errors = sorted(
        validator.iter_errors(dict(payload)),
        key=lambda error: "/".join(str(part) for part in error.absolute_path),
    )
    formatted: list[str] = []
    for error in errors:
        path = "/".join(str(part) for part in error.absolute_path)
        formatted.append(f"{path or '$'}: {error.message}")
    return tuple(formatted)


class LLMGraphGenerator:
    def __init__(
        self,
        client: LLMClient,
        *,
        settings: LLMSettings,
        auditor: CallAuditor | None = None,
        verifier: GraphVerifier | None = None,
        cache_size: int = GRAPH_CACHE_SIZE,
    ) -> None:
        self._client = client
        self._settings = settings
        self._auditor = auditor
        # The default verifier imports SymPy lazily, so a build without a claim
        # never pays for it.
        self._verifier: GraphVerifier = verifier if verifier is not None else default_verifier()
        self._cache: dict[str, GraphBuildResult] = {}
        self._cache_size = max(0, cache_size)

    def warm(self) -> None:
        """Let the verifier pay its import before a learner waits for it.

        Optional on the port: a verifier without ``warm`` (the tests' fakes)
        is simply left alone.
        """
        warm = getattr(self._verifier, "warm", None)
        if callable(warm):
            warm()

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        if not self._settings.llm_enabled:
            raise GraphBuildFailed(
                "disabled",
                detail="SYNAPSE_LLM_MODE=off 或缺少 API key；没有可用的规则建图路径",
            )
        if not PROBLEM_ID_PATTERN.fullmatch(draft.id):
            raise GraphBuildFailed(
                "invalid_draft",
                detail=f"problem id {draft.id!r} 不符合 ^P_[A-Z0-9_]+$",
            )

        cache_key = _cache_key(draft, self._settings)
        audit_version = _prompt_version(self._settings, draft.subject)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return replace(cached, cached=True)

        started_at = time.perf_counter()
        check, response, graph_calls = self._generate_graph(draft, audit_version)
        verification = self._verifier.verify(check.graph)

        if verification.status != "fail":
            digest = fingerprint(check.graph)
            self._audit(
                response,
                schema_ok=True,
                retried=graph_calls > 1,
                fingerprint=digest,
                verification_status=verification.status,
                prompt_version=audit_version,
            )
            result = GraphBuildResult(
                graph=check.graph,
                fingerprint=digest,
                attempts=graph_calls,
                repairs=check.repairs,
                notes=quality_notes(check.graph),
                verification=verification,
            )
            self._store(cache_key, result)
            return result

        # The graph is usable; only its answer range is wrong. A refuted claim
        # is repaired by rewriting the interval, not the whole graph: the graph
        # already passed every structural rule, and regenerating it is what used
        # to push the tail to ≈7.6s (ADR-0004 §5.4).
        self._audit(
            response,
            schema_ok=False,
            retried=graph_calls > 1,
            reason=verification.reason,
            verification_status=verification.status,
            prompt_version=audit_version,
        )
        repair = self._repair_claim(
            draft,
            check.graph,
            verification,
            started_at=started_at,
            prompt_version=audit_version,
        )
        calls = graph_calls + (1 if repair.attempted else 0)

        if repair.claim is not None:
            graph = replace(check.graph, claim=repair.claim)
            digest = fingerprint(graph)
            result = GraphBuildResult(
                graph=graph,
                fingerprint=digest,
                attempts=calls,
                repairs=tuple(sorted({*check.repairs, "claim_repaired"})),
                notes=quality_notes(graph),
                verification=repair.verification,
            )
            self._store(cache_key, result)
            return result

        # Keep the graph (its probes are what the dialogue uses) but refuse to
        # certify the answer; the counterexample stays in ``verification``.
        graph = replace(check.graph, claim=None)
        digest = fingerprint(graph)
        repairs = {*check.repairs, "claim_dropped_refuted", *repair.codes}
        if not repair.attempted:
            repairs.add("retry_skipped_budget")
        result = GraphBuildResult(
            graph=graph,
            fingerprint=digest,
            attempts=calls,
            repairs=tuple(sorted(repairs)),
            notes=quality_notes(graph),
            verification=repair.verification or verification,
        )
        self._store(cache_key, result)
        return result

    def _generate_graph(
        self, draft: ProblemDraft, prompt_version: str
    ) -> tuple[GraphCheck, LLMResponse, int]:
        """Generate the graph itself, with one schema-driven retry.

        ``max_attempts`` counts graph calls only; a later claim repair is a
        separate, cheaper call and is not bounded by it.
        """
        attempts = max(1, self._settings.max_attempts)
        issues: tuple[str, ...] = ()
        reason: GraphFailureReason = "schema_invalid"
        for attempt in range(attempts):
            request = build_request(draft, issues=issues)
            try:
                response = self._client.complete(
                    request,
                    timeout_s=self._settings.graph_timeout_s,
                )
            except LLMTimeout as exc:
                # A timeout is not a schema failure: retrying it is how the
                # first-question budget gets blown (chapter 12 §12.8).
                self._audit(
                    None,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason="timeout",
                    prompt_version=prompt_version,
                )
                raise GraphBuildFailed(
                    "timeout",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc
            except LLMCallFailed as exc:
                self._audit(
                    None,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason="transport",
                    prompt_version=prompt_version,
                )
                raise GraphBuildFailed(
                    "transport",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc

            try:
                check = _build_graph(draft, response.text)
            except _Rejected as exc:
                reason = exc.reason
                issues = exc.issues
                self._audit(
                    response,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason=exc.reason,
                    prompt_version=prompt_version,
                )
                continue
            return check, response, attempt + 1

        raise GraphBuildFailed(
            reason,
            detail="; ".join(issues[:5]),
            attempts=attempts,
        )

    def _repair_claim(
        self,
        draft: ProblemDraft,
        graph: SolutionGraph,
        verification: VerificationResult,
        *,
        started_at: float,
        prompt_version: str,
    ) -> _ClaimRepair:
        claim = graph.claim
        if claim is None:  # the verifier only returns ``fail`` for an existing claim
            return _ClaimRepair(attempted=False)
        remaining = self._settings.graph_retry_budget_s - (time.perf_counter() - started_at)
        if remaining < CLAIM_REPAIR_MIN_BUDGET_S:
            return _ClaimRepair(attempted=False)
        request = build_claim_repair_request(draft, claim, verification)
        try:
            response = self._client.complete(
                request,
                # The repair may only use what is left of the budget, so a slow
                # first attempt cannot turn into an SLO-breaking second call.
                timeout_s=min(remaining, self._settings.graph_timeout_s),
            )
        except LLMTimeout:
            self._audit(
                None,
                schema_ok=False,
                retried=True,
                reason="timeout",
                prompt_version=prompt_version,
            )
            return _ClaimRepair(
                attempted=True,
                verification=verification,
                codes=("claim_retry_timeout",),
            )
        except LLMCallFailed:
            self._audit(
                None,
                schema_ok=False,
                retried=True,
                reason="transport",
                prompt_version=prompt_version,
            )
            return _ClaimRepair(
                attempted=True,
                verification=verification,
                codes=("claim_retry_transport",),
            )

        try:
            repaired = read_claim_repair(response.text, graph, verification)
        except _Rejected as exc:
            self._audit(
                response,
                schema_ok=False,
                retried=True,
                reason=exc.reason,
                prompt_version=prompt_version,
            )
            return _ClaimRepair(
                attempted=True,
                verification=verification,
                codes=("claim_retry_malformed",),
            )

        if repaired is None:
            self._audit(
                response,
                schema_ok=False,
                retried=True,
                reason="claim_declined",
                verification_status=verification.status,
                prompt_version=prompt_version,
            )
            return _ClaimRepair(
                attempted=True,
                verification=verification,
                codes=("claim_repair_declined",),
            )

        verdict = self._verifier.verify(replace(graph, claim=repaired))
        accepted = verdict.status == "pass"
        self._audit(
            response,
            schema_ok=accepted,
            retried=True,
            reason=None if accepted else verdict.reason,
            verification_status=verdict.status,
            prompt_version=prompt_version,
        )
        if accepted:
            return _ClaimRepair(attempted=True, claim=repaired, verification=verdict)
        code = "claim_repair_refuted" if verdict.status == "fail" else "claim_repair_undecided"
        return _ClaimRepair(attempted=True, verification=verdict, codes=(code,))

    def _store(self, key: str, result: GraphBuildResult) -> None:
        if self._cache_size <= 0:
            return
        if len(self._cache) >= self._cache_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result

    def _audit(
        self,
        response: LLMResponse | None,
        *,
        schema_ok: bool,
        retried: bool,
        reason: str | None = None,
        fingerprint: str = "",
        verification_status: str = "",
        prompt_version: str = "",
    ) -> None:
        if self._auditor is None:
            return
        context = trace.current()
        self._auditor.record(
            AuditEntry(
                kind="graph_build",
                session_id=context.session_id if context else "",
                turn=context.turn if context else 0,
                model=response.model if response else self._settings.model,
                prompt_version=prompt_version or self._settings.graph_prompt_version,
                latency_ms=response.latency_ms if response else 0,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                retried=retried,
                fallback_reason=reason,
                schema_ok=schema_ok,
                graph_fingerprint=fingerprint,
                verification_status=verification_status,
            )
        )


def _build_graph(draft: ProblemDraft, text: str) -> GraphCheck:
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Rejected("bad_json", (f"bad_json: {exc.msg}",)) from exc
    if not isinstance(raw, dict):
        raise _Rejected("bad_json", ("not_object: 响应必须是 JSON 对象",))

    try:
        payload = _GraphPayload.model_validate(raw)
    except ValidationError as exc:
        raise _Rejected("schema_invalid", _format_validation(exc)) from exc

    # Observed with graph-v3: the model sometimes flattens probes to the top
    # level, where a probe has no owner. Guessing an owner would invent
    # structure, so say exactly what is wrong and let the retry fix it.
    top_level_probes = raw.get("probes")
    if isinstance(top_level_probes, list) and top_level_probes:
        raise _Rejected(
            "schema_invalid",
            ("probes_top_level: 探针必须写在所属节点的 probes 数组里，不能放在顶层",),
        )

    nodes = tuple(_node(item) for item in payload.nodes)
    edges: list[tuple[str, str]] = []
    for edge in payload.edges:
        if len(edge) != 2:
            raise _Rejected("schema_invalid", ("edge_shape: edges 的每一项必须是 [前置, 后继]",))
        edges.append((edge[0], edge[1]))

    profile = _profile(draft.subject)
    repairs: set[str] = set()
    if not profile.probes:
        # A NONE-tier subject never asks a probe (S7). Keeping the model's
        # probes would imply a promise the product does not make, so they are
        # dropped like an unsupported claim: the structure survives, the
        # probing does not.
        if any(node.probes for node in nodes):
            repairs.add("probes_dropped_unsupported")
        nodes = tuple(replace(node, probes=()) for node in nodes)

    graph = SolutionGraph(
        problem_id=draft.id,
        version="g1",
        stem=draft.text,
        nodes=nodes,
        edges=tuple(edges),
        # v1's claim verifier is a math parameter-range tool. A physics answer
        # carries units/vectors and a language answer has no formal statement at
        # all, so a claim-shaped block in those subjects is never trusted; the
        # CHECK node is where the model is told to put its own checks.
        claim=_claim(raw.get("claim")) if profile.claim else None,
    )
    check = review(
        graph,
        allowed_targets=ALLOWED_PROBE_TARGETS,
        require_evidence=profile.probes,
        calibrate_evidence=profile.probes,
        require_probes=profile.probes,
    )
    if not check.ok:
        raise _Rejected(_classify(check.issues), check.issues)
    if not profile.claim and raw.get("claim") is not None:
        repairs.add("claim_dropped_unsupported")
    if repairs:
        check = replace(check, repairs=tuple(sorted({*check.repairs, *repairs})))

    spec_errors = validate_payload(to_payload(check.graph))
    if spec_errors:
        raise _Rejected("schema_invalid", spec_errors)
    return check


def read_claim_repair(
    text: str,
    graph: SolutionGraph,
    verification: VerificationResult,
) -> VerificationClaim | None:
    """Read the claim-only reply; ``None`` means the model declined.

    A counterexample repair may only change the intervals: the formalisation is
    pinned so the model cannot dodge the counterexample by quietly editing f(x).
    A malformed claim is different — the expression itself was unreadable, so
    the whole claim may be rewritten.
    """
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Rejected("bad_json", (f"bad_json: {exc.msg}",)) from exc
    if not isinstance(raw, Mapping):
        raise _Rejected("bad_json", ("not_object: 响应必须是 JSON 对象",))

    previous = graph.claim
    if previous is None:
        raise _Rejected("schema_invalid", ("claim: 原先没有 claim，无法只重写区间",))

    if verification.reason == "malformed":
        nested = raw.get("claim")
        if nested is None:
            return None
        claim = _claim(nested)
    else:
        answer: object = raw.get("answer")
        if answer is None:
            block = raw.get("claim")
            if isinstance(block, Mapping):
                answer = block.get("answer")
        if answer is None:
            return None
        if not isinstance(answer, list) or not answer:
            raise _Rejected("schema_invalid", ("claim.answer: 必须是非空的区间数组",))
        errors: list[str] = []
        intervals: list[Interval] = []
        for index, item in enumerate(answer):
            interval = _interval(item, index, errors)
            if interval is not None:
                intervals.append(interval)
        if errors:
            raise _Rejected("schema_invalid", tuple(errors))
        claim = replace(previous, intervals=tuple(intervals))

    if claim is None:
        return None
    spec_errors = validate_payload(to_payload(replace(graph, claim=claim)))
    if spec_errors:
        raise _Rejected("schema_invalid", spec_errors)
    return claim


def _node(item: _NodePayload) -> SolutionNode:
    return SolutionNode(
        id=item.id,
        type=item.type,
        text=item.text,
        demand=dict(item.demand),
        common_errors=tuple(item.common_errors),
        probes=tuple(
            Probe(
                id=probe.id,
                question=probe.question,
                options=tuple(probe.options),
                targets=tuple(probe.targets),
                hint_level=probe.hint_level,
                evidence={option: dict(weights) for option, weights in probe.evidence.items()},
            )
            for probe in item.probes
        ),
    )


def _claim(raw: object) -> VerificationClaim | None:
    """Read the optional ``claim`` block; the spec validates it again later.

    Parsing it here (rather than leaning on the final schema run) means a
    malformed claim is reported before the graph is built, with the same
    retry-with-feedback path as every other model mistake.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _Rejected("schema_invalid", ("claim: 必须是对象",))

    errors: list[str] = []
    interval_items = raw.get("answer")
    intervals: list[Interval] = []
    if not isinstance(interval_items, list) or not interval_items:
        errors.append("claim.answer: 必须是非空的区间数组")
    else:
        for index, item in enumerate(interval_items):
            interval = _interval(item, index, errors)
            if interval is not None:
                intervals.append(interval)

    constraint = raw.get("constraint")
    expression = ""
    relation = ""
    if not isinstance(constraint, Mapping):
        errors.append("claim.constraint: 必须是含 expression 与 relation 的对象")
    else:
        expression = _text_field(constraint, "expression", "claim.constraint", errors)
        relation = _text_field(constraint, "relation", "claim.constraint", errors)

    claim = VerificationClaim(
        kind=_text_field(raw, "kind", "claim", errors),
        parameter=_text_field(raw, "parameter", "claim", errors),
        variable=_text_field(raw, "variable", "claim", errors),
        variable_domain=_text_field(raw, "variable_domain", "claim", errors),
        expression=expression,
        relation=relation,
        intervals=tuple(intervals),
    )
    if errors:
        raise _Rejected("schema_invalid", tuple(errors))
    return claim


def _interval(item: object, index: int, errors: list[str]) -> Interval | None:
    prefix = f"claim.answer[{index}]"
    if not isinstance(item, Mapping):
        errors.append(f"{prefix}: 必须是含 lower 与 upper 的对象")
        return None
    endpoints: dict[str, str | None] = {}
    for key in ("lower", "upper"):
        if key not in item:
            errors.append(f"{prefix}.{key}: 缺少这个字段（无界的一端写 null）")
            endpoints[key] = None
            continue
        value = item[key]
        if value is None or isinstance(value, str):
            endpoints[key] = value
        else:
            errors.append(f"{prefix}.{key}: 必须是字符串或 null")
            endpoints[key] = None
    return Interval(
        lower=endpoints["lower"],
        upper=endpoints["upper"],
        lower_inclusive=_bool_field(item, "lower_inclusive", prefix, errors),
        upper_inclusive=_bool_field(item, "upper_inclusive", prefix, errors),
    )


def _text_field(
    raw: Mapping[str, object],
    key: str,
    prefix: str,
    errors: list[str],
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}.{key}: 必须是非空字符串")
        return ""
    return value.strip()


def _bool_field(
    raw: Mapping[str, object],
    key: str,
    prefix: str,
    errors: list[str],
) -> bool:
    value = raw.get(key, True)
    if not isinstance(value, bool):
        errors.append(f"{prefix}.{key}: 必须是 true 或 false")
        return True
    return value


def _classify(issues: Sequence[str]) -> GraphFailureReason:
    codes = {issue.split(":", 1)[0].strip() for issue in issues}
    return "degenerate" if codes & _DEGENERATE_CODES else "schema_invalid"


def _format_validation(exc: ValidationError) -> tuple[str, ...]:
    formatted: list[str] = []
    for error in exc.errors():
        location = "/".join(str(part) for part in error["loc"])
        formatted.append(f"{location or '$'}: {error['msg']}")
    return tuple(formatted)


def _feedback(issues: Sequence[str]) -> str:
    lines: list[str] = []
    for issue in issues[:12]:
        code = issue.split(":", 1)[0].strip()
        hint = _ISSUE_HINTS.get(code, "")
        lines.append(f"- {hint}（{issue}）" if hint else f"- {issue}")
    return "\n".join(lines)


def _cache_key(draft: ProblemDraft, settings: LLMSettings) -> str:
    raw = "\x1f".join(
        (
            draft.id,
            draft.subject,
            draft.grade,
            settings.model,
            _prompt_version(settings, draft.subject),
            draft.text.strip(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _solution_graph_schema() -> dict[str, object]:
    path = _repo_root() / "specs" / "solution-graph.schema.json"
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return cast(dict[str, object], loaded)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "specs" / "solution-graph.schema.json").is_file():
            return parent
    raise RuntimeError(
        "specs/solution-graph.schema.json not found; graph generation requires the repo checkout"
    )
