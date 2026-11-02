"""Fixed case set for the product behavior / contract harness.

These cases are **regression pins, not a benchmark**. Each one states the
contract the product currently promises (an entry is accepted, a skipped run is
not a pass, a decision is not ranked, an answer is not shown in learning mode)
and a fixed input that exercises it. The harness in ``product_behavior.py`` runs
them in-process with the model, RAG and execution switches off.

Nothing here measures learning gains, diagnostic accuracy or real-student
performance. A green run means "the behavior boundaries still hold on this fixed
set", not "the product works".

Adding a case: keep the id stable, describe the *contract* (not the expected
implementation), and set ``expected="expected_fail"`` only for a documented
boundary with a reason. A boundary that starts passing is reported as drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Expectation = Literal["pass", "expected_fail"]


@dataclass(frozen=True, slots=True)
class Check:
    """One assertion over a scenario observation field."""

    label: str
    key: str
    op: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class Case:
    """One fixed behavior case.

    ``intent`` says why the case exists; ``contract`` is the promise being
    pinned; ``reason`` is required only for an accepted boundary.
    """

    id: str
    category: str
    intent: str
    contract: str
    scenario: str
    params: dict[str, Any]
    checks: tuple[Check, ...]
    expected: Expectation = "pass"
    reason: str = ""
    subset: bool = False


# --- Fixed inputs ------------------------------------------------------------
#
# The two math/physics texts are deliberately *not* the annotated seed problem:
# they are recognized domains whose graph cannot be built with the model off.

WRITING_TEXT = "学校是否应该禁止中学生带手机进校园？请写一段议论，说明你的立场和理由。"
WRITING_ANSWER = "不应该禁止"
WRITING_WORK = (
    "我想论证的是：中学生不该被禁止带手机进校园。"
    "手机能查资料，也方便联系家长。"
    "学校禁止手机，是担心课堂被打断。"
)
WRITING_SHORT = "我想论证学校应该禁止学生带手机。很多同学都这样。"
WRITING_NEEDLE = "手机能查资料"

DECISION_TEXT = "我应该接受北京的工作机会，还是留在上海陪家人？"
DECISION_ATTEMPT = (
    "我要决定接受北京的工作还是留在上海还是先读研。"
    "接受北京的工作，代价是异地分居，先试试远程三个月再决定。"
    "留在上海，担心发展变慢。"
    "先读研，代价是再花两年。"
)
DECISION_TWO = "接受北京的工作还是什么都不做。"
DECISION_ONE = "我在纠结要不要接北京的工作。"
DECISION_MISSING = "我在纠结接受北京的工作还是留在上海。"
DECISION_BLANK = "不知道选哪个"

CODE_TEXT = "我的 Python 脚本报错了：IndexError: list index out of range，应该怎么修？"
CODE_SNIPPET = "def sort(items):\n    return items\n"
CODE_TESTS = "assert True\n"
CODE_MARKER = "print('HARNESS_CODE_MARKER')\n"

UNKNOWN_TEXT = "我最近很烦，不知道该怎么办。"
UNKNOWN_ANSWER = "不知道先做哪个。"
UNKNOWN_CLARIFIER = "我纠结要不要换城市工作：要么留下，要么跳槽，但我担心收入下降。"
UNKNOWN_NO_CUE = "我卡在第二步：不知道先做哪个。"
OPEN_LABEL_TEXT = "我的乐高结构总是一推就散，该怎么加固？"
OPEN_LABEL = "乐高结构"

MATH_SEED_TEXT = "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"
MATH_SEED_ANSWER = "a∈[1/e,+∞)"
MATH_WORK = (
    "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。"
)
MATH_UNSEEN = "解方程 x^2 - 5x + 6 = 0。"
PHYSICS_UNSEEN = (
    "质量为 2 kg 的物块放在水平面上，受到与水平方向成 30° 的拉力 F=10 N，"
    "动摩擦因数 0.2，求物块的加速度。"
)

CHC_KEYS = ["V", "Gf", "Gv", "WM", "Gs", "LTS", "M"]


def _eq(label: str, key: str, value: Any) -> Check:
    return Check(label, key, "eq", value)


def _true(label: str, key: str) -> Check:
    return Check(label, key, "truthy")


def _false(label: str, key: str) -> Check:
    return Check(label, key, "falsy")


CASES: tuple[Case, ...] = (
    # --- Writing structure review (T7: answer and work are separate fields) ---
    Case(
        id="W01",
        category="写作结构复盘",
        intent="短答案 + 独立过程字段时，结构复盘读取过程字段（T7）",
        contract="work 进入复盘证据；findings 非空；学习态响应不含 answer/solution 键",
        scenario="start",
        params={
            "text": WRITING_TEXT,
            "answer": WRITING_ANSWER,
            "work": WRITING_WORK,
            "subject": "写作",
            "evidence_needle": WRITING_NEEDLE,
        },
        checks=(
            _eq("创建成功", "status", 201),
            _eq("停在 CLOSED", "state", "CLOSED"),
            _eq("识别为写作", "domain_name", "writing"),
            _eq("验证方式为论证结构", "verification", "argumentative"),
            _true("带结构复盘", "has_review"),
            _eq("复盘类型为 structure", "review_kind", "structure"),
            Check("至少一条 finding", "review_findings_count", "ge", 1),
            _true("每条 finding 都引用存在的证据", "review_refs_ok"),
            _true("过程字段进入证据", "work_in_evidence"),
            _false("不含 answer 键", "has_answer_key"),
            _false("不含 solution 键", "has_solution_key"),
        ),
        subset=True,
    ),
    Case(
        id="W02",
        category="写作结构复盘",
        intent="只有短答案、没有过程时，不编造结构缺口",
        contract="review 仍在，但 findings=0；用 not_checked 和一个补充问题收束",
        scenario="start",
        params={"text": WRITING_TEXT, "answer": WRITING_ANSWER, "subject": "写作"},
        checks=(
            _eq("创建成功", "status", 201),
            _true("带结构复盘", "has_review"),
            _eq("复盘类型为 structure", "review_kind", "structure"),
            _eq("没有编造 finding", "review_findings_count", 0),
            Check("not_checked 说明没检查什么", "review_not_checked_count", "ge", 1),
            Check("下一步是一个补充问题", "review_next_step", "ends_with", "？"),
        ),
    ),
    Case(
        id="W03",
        category="写作结构复盘",
        intent="过程字段单独提交也能被复盘读取",
        contract="仅有 work 时 findings 与证据仍非空，且证据包含过程原话",
        scenario="start",
        params={
            "text": WRITING_TEXT,
            "answer": "不知道",
            "work": WRITING_WORK,
            "subject": "写作",
            "evidence_needle": WRITING_NEEDLE,
        },
        checks=(
            _eq("创建成功", "status", 201),
            _true("带结构复盘", "has_review"),
            Check("至少一条 finding", "review_findings_count", "ge", 1),
            _true("过程字段进入证据", "work_in_evidence"),
            _true("每条 finding 都引用存在的证据", "review_refs_ok"),
        ),
    ),
    Case(
        id="W04",
        category="写作结构复盘",
        intent="论据只有一句概括时，复盘报缺证据与推理跳跃",
        contract="finding_kinds 同时包含 missing_evidence 与 reasoning_jump",
        scenario="start",
        params={"text": WRITING_TEXT, "answer": WRITING_SHORT, "subject": "写作"},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("复盘类型为 structure", "review_kind", "structure"),
            Check("报出缺证据", "finding_kinds", "contains", "missing_evidence"),
            Check("报出推理跳跃", "finding_kinds", "contains", "reasoning_jump"),
            _true("每条 finding 都引用存在的证据", "review_refs_ok"),
        ),
    ),
    Case(
        id="W05",
        category="写作结构复盘",
        intent="结构复盘不评分、不排序、不说“你错了”",
        contract="review 与响应中无 score/rank/recommended/best；copy 无禁止措辞",
        scenario="start",
        params={"text": WRITING_TEXT, "answer": WRITING_SHORT, "subject": "写作"},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("review 内没有评分/排序字段", "review_forbidden_keys", []),
            _eq("响应内没有评分/排序字段", "body_forbidden_keys", []),
            _eq("review copy 没有禁止措辞", "review_copy_hits", []),
            Check("至少一条 finding", "review_findings_count", "ge", 1),
        ),
        subset=True,
    ),
    Case(
        id="W06",
        category="写作结构复盘",
        intent="复盘每次读取都从同一次提交重新推导（刷新不漂移）",
        contract="GET 返回的 review/intake 与创建响应一致；GET 仍无 answer/solution 键",
        scenario="start_reload",
        params={
            "text": WRITING_TEXT,
            "answer": WRITING_ANSWER,
            "work": WRITING_WORK,
            "subject": "写作",
        },
        checks=(
            _eq("创建成功", "status", 201),
            _eq("重新读取成功", "get_status", 200),
            _true("review 与创建时一致", "review_equal"),
            _true("intake 与创建时一致", "intake_equal"),
            _false("GET 响应仍不含 answer 键", "get_has_answer_key"),
        ),
    ),
    # --- Decision frame -------------------------------------------------------
    Case(
        id="D01",
        category="决策框",
        intent="决策框列出学生选项并自动补上「什么都不做」",
        contract=(
            "options>=2 且恰好一个「什么都不做」；选项字段只有 label/costs/risks/reversible_test"
        ),
        scenario="start",
        params={"text": DECISION_TEXT, "answer": DECISION_ATTEMPT},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("复盘类型为 decision", "review_kind", "decision"),
            Check("至少两个选项", "options_count", "ge", 2),
            _eq("恰好一个「什么都不做」", "do_nothing_count", 1),
            _eq("选项没有额外字段", "option_bad_keys_count", 0),
            Check("用取舍问题代替推荐", "tradeoff_question", "ends_with", "？"),
            _eq("review 内没有评分/排序字段", "review_forbidden_keys", []),
            _eq("review copy 没有禁止措辞", "review_copy_hits", []),
        ),
        subset=True,
    ),
    Case(
        id="D02",
        category="决策框",
        intent="决策响应整体不携带排序或推荐字段",
        contract="响应任意层级的键都不含 score/rank/recommended/best；copy 无推荐措辞",
        scenario="start",
        params={"text": DECISION_TEXT, "answer": DECISION_ATTEMPT},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("响应内没有评分/排序字段", "body_forbidden_keys", []),
            _eq("review 内没有评分/排序字段", "review_forbidden_keys", []),
            _eq("review copy 没有禁止措辞", "review_copy_hits", []),
        ),
    ),
    Case(
        id="D03",
        category="决策框",
        intent="学生自己写了「什么都不做」时不重复添加",
        contract="两个选项，其中恰好一个包含「什么都不做」",
        scenario="start",
        params={"text": DECISION_TEXT, "answer": DECISION_TWO},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("复盘类型为 decision", "review_kind", "decision"),
            _eq("选项数为 2", "options_count", 2),
            _eq("恰好一个「什么都不做」", "do_nothing_count", 1),
        ),
    ),
    Case(
        id="D04",
        category="决策框",
        intent="只有一个选项时退回结构复盘，不凭空造第二个选项",
        contract="kind=structure；options 为空；not_checked 说明决策框需要两个选项",
        scenario="start",
        params={"text": DECISION_TEXT, "answer": DECISION_ONE},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("退回结构复盘", "review_kind", "structure"),
            _eq("没有生成的选项", "options_count", 0),
            Check(
                "not_checked 说明至少两个选项",
                "review_not_checked_text",
                "contains",
                "至少两个选项",
            ),
            Check("下一步要求补第二个选项", "review_next_step", "contains", "第二个选项"),
            Check("下一步是一个问题", "review_next_step", "ends_with", "？"),
        ),
    ),
    Case(
        id="D05",
        category="决策框",
        intent="选项缺代价/风险/可逆实验时逐项报出",
        contract=(
            "finding_kinds 含 option_without_cost、option_without_risk、missing_reversible_test"
        ),
        scenario="start",
        params={"text": DECISION_TEXT, "answer": DECISION_MISSING},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("复盘类型为 decision", "review_kind", "decision"),
            Check("至少两个选项", "options_count", "ge", 2),
            Check("报出缺代价", "finding_kinds", "contains", "option_without_cost"),
            Check("报出缺风险", "finding_kinds", "contains", "option_without_risk"),
            Check("报出缺可逆实验", "finding_kinds", "contains", "missing_reversible_test"),
        ),
    ),
    Case(
        id="D06",
        category="决策框",
        intent="结构补充一次只问一个，三次后停止",
        contract="answered 依次为 1/2/None；第四次请求 409；会话始终 CLOSED 且无诊断",
        scenario="probe_flow",
        params={
            "text": DECISION_TEXT,
            "answer": DECISION_BLANK,
            "answers": [
                "目标：两年内转做后端。",
                "目标：两年内转做后端。",
                "目标：两年内转做后端。",
            ],
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _true("第一次有结构补充问题", "first_probe"),
            _eq("三次补充都成功", "statuses", [200, 200, 200]),
            _eq("预算递减", "answered", [1, 2, None]),
            _true("第三次后不再提问", "last_probe_none"),
            _eq("第四次请求冲突", "fourth_status", 409),
            _eq("始终停在 CLOSED", "state", "CLOSED"),
            _false("没有生成诊断", "has_diagnosis"),
        ),
    ),
    Case(
        id="D07",
        category="决策框",
        intent="空白结构补充被拒绝，不写入会话",
        contract="POST /intake/probe 的空字符串返回 422",
        scenario="intake_answer",
        params={
            "text": DECISION_TEXT,
            "answer": DECISION_BLANK,
            "endpoint": "intake/probe",
            "post": "   ",
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("空白补充返回 422", "status", 422),
        ),
    ),
    Case(
        id="D08",
        category="决策框",
        intent="决策会话不接受诊断探针作答",
        contract="POST /turns 返回 200 / CLOSED，diagnosis=None，notice 说明已结束",
        scenario="turn_on_generic",
        params={"text": DECISION_TEXT, "answer": DECISION_BLANK},
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("作答接口仍返回 200", "status", 200),
            _eq("停在 CLOSED", "state", "CLOSED"),
            _false("没有生成诊断", "has_diagnosis"),
            Check("notice 说明已结束", "notice", "contains", "已结束"),
            _true("仍带通用入口", "has_intake"),
        ),
    ),
    # --- Executable mode is off ----------------------------------------------
    Case(
        id="C01",
        category="可执行关闭",
        intent="代码问题进入可执行入口，但复盘与诊断都不伪造",
        contract="入口 verdict=executable；intake.review=None；disclaimer 写明未执行",
        scenario="start",
        params={"text": CODE_TEXT, "answer": "不知道"},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("停在 CLOSED", "state", "CLOSED"),
            _eq("验证方式为可执行", "verification", "executable"),
            _false("没有结构复盘", "has_review"),
            Check("disclaimer 写明未执行", "intake_disclaimer", "contains", "未执行"),
            _false("不含 answer 键", "has_answer_key"),
            _false("不含 solution 键", "has_solution_key"),
            _false("没有生成诊断", "has_diagnosis"),
        ),
        subset=True,
    ),
    Case(
        id="C02",
        category="可执行关闭",
        intent="SYNAPSE_EXEC=off 时显式提交返回 skipped，绝不冒充 pass",
        contract="execution.status=skipped；headline 说“没有运行”；findings/evidence 为空",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_SNIPPET,
            "tests": CODE_TESTS,
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("复盘接口返回 200", "status", 200),
            _eq("复盘类型为 execution", "kind", "execution"),
            _eq("状态是 skipped", "execution_status", "skipped"),
            _true("记录 tests 已提交", "tests_submitted"),
            _eq("没有编造 finding", "review_findings_count", 0),
            _eq("没有编造证据", "review_evidence_count", 0),
            Check("headline 说没有运行", "headline", "contains", "没有运行"),
            Check("headline 不说通过", "headline", "not_contains", "通过"),
            _false("不含 answer 键", "has_answer_key"),
        ),
        subset=True,
    ),
    Case(
        id="C03",
        category="可执行关闭",
        intent="执行开关关闭时，即使注入了执行器也不会被调用",
        contract="skipped 且 executor_calls=0（开关是外层闸门）",
        scenario="review_run",
        params={
            "config": "off_sentinel",
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_SNIPPET,
            "tests": CODE_TESTS,
        },
        checks=(
            _eq("复盘接口返回 200", "status", 200),
            _eq("状态是 skipped", "execution_status", "skipped"),
            _eq("执行器调用次数为 0", "executor_calls", 0),
        ),
    ),
    Case(
        id="C04",
        category="可执行关闭",
        intent="执行端点关闭时返回 403，而不是假的结果",
        contract="POST /executions -> 403，detail 提示 SYNAPSE_EXEC=on；执行器调用 0 次",
        scenario="executions",
        params={"config": "off_sentinel"},
        checks=(
            _eq("执行端点返回 403", "status", 403),
            Check("detail 指向开关", "detail", "contains", "SYNAPSE_EXEC=on"),
            _eq("执行器调用次数为 0", "executor_calls", 0),
        ),
    ),
    Case(
        id="C05",
        category="可执行关闭",
        intent="非可执行会话拒绝代码复现卡",
        contract="决策会话 POST /review/run -> 409，detail 提到可执行验证",
        scenario="review_run",
        params={
            "text": DECISION_TEXT,
            "answer": DECISION_BLANK,
            "code": "print(1)\n",
            "tests": "",
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("非可执行会话返回 409", "status", 409),
            Check("detail 说明只用于可执行验证", "detail", "contains", "可执行验证"),
        ),
    ),
    Case(
        id="C06",
        category="可执行关闭",
        intent="空白代码在校验层被拒绝",
        contract="review/run 的 code 只有空白 -> 422",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": "   ",
            "tests": "",
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("空白代码返回 422", "status", 422),
        ),
    ),
    Case(
        id="C07",
        category="可执行关闭",
        intent="空白 tests 视为未提交，而不是空测试通过",
        contract="tests_submitted=false；执行状态仍是 skipped",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": "print(1)\n",
            "tests": "   \n",
        },
        checks=(
            _eq("复盘接口返回 200", "status", 200),
            _eq("状态是 skipped", "execution_status", "skipped"),
            _false("tests 视为未提交", "tests_submitted"),
        ),
    ),
    Case(
        id="C08",
        category="可执行关闭",
        intent="代码复现卡不回显提交代码，也不返回答案",
        contract="响应不含提交代码原文，且没有 answer/solution 键",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_MARKER,
            "tests": "",
        },
        checks=(
            _eq("复盘接口返回 200", "status", 200),
            _false("不回显提交代码", "code_echoed"),
            _false("不含 answer 键", "has_answer_key"),
            _false("不含 solution 键", "has_solution_key"),
        ),
    ),
    Case(
        id="C09",
        category="可执行关闭",
        intent="review/run 响应符合已发布的 generic-review v0.1 schema",
        contract="按 specs/generic-review.schema.json 校验零错误",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_SNIPPET,
            "tests": CODE_TESTS,
        },
        checks=(
            _eq("复盘接口返回 200", "status", 200),
            _eq("schema 校验零错误", "schema_errors_count", 0),
        ),
    ),
    Case(
        id="C10",
        category="可执行关闭",
        intent="Agent 轨迹只读，显式代码在开关关闭时记为 skipped",
        contract="3 步以内；run 步骤 skipped；planner=off；会话前后不变；无 answer 键",
        scenario="agent_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_SNIPPET,
            "tests": CODE_TESTS,
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("轨迹返回 200", "status", 200),
            _eq("最多 3 步", "steps_count", 3),
            _true("轨迹包含执行步骤", "has_run_step"),
            _eq("执行步骤是 skipped", "run_step_status", "skipped"),
            _eq("规划器默认 off", "planner_status", "off"),
            _true("会话没有被写入", "session_unchanged"),
            _false("轨迹不含 answer 键", "has_answer_key"),
        ),
    ),
    # --- Open domain entry ----------------------------------------------------
    Case(
        id="O01",
        category="开放领域入口",
        intent="未知领域不返回 422，而是进入通用入口",
        contract="201/CLOSED；domain=generic、generic=true、confidence=0；intake 存在且无诊断",
        scenario="start",
        params={"text": UNKNOWN_TEXT, "answer": UNKNOWN_ANSWER},
        checks=(
            _eq("未知领域仍创建成功", "status", 201),
            _eq("停在 CLOSED", "state", "CLOSED"),
            _eq("领域标签为 generic", "domain_name", "generic"),
            _true("标记为通用领域", "generic"),
            _eq("置信度为 0", "confidence", 0.0),
            _true("带通用入口", "has_intake"),
            _false("没有生成诊断", "has_diagnosis"),
        ),
        subset=True,
    ),
    Case(
        id="O02",
        category="开放领域入口",
        intent="未知领域的结构复盘只给 not_checked 与一个问题",
        contract="review.kind=structure；not_checked 非空；next_step 是一个问题",
        scenario="start",
        params={"text": UNKNOWN_TEXT, "answer": UNKNOWN_ANSWER},
        checks=(
            _eq("创建成功", "status", 201),
            _true("带结构复盘", "has_review"),
            _eq("复盘类型为 structure", "review_kind", "structure"),
            Check("not_checked 非空", "review_not_checked_count", "ge", 1),
            Check("下一步是一个问题", "review_next_step", "ends_with", "？"),
            _true("findings 都引用存在的证据", "review_refs_ok"),
        ),
    ),
    Case(
        id="O03",
        category="开放领域入口",
        intent="开放的领域标签被接受并原样保留",
        contract="domain.name/label 都是提交的标签；generic=true；有 intake",
        scenario="start",
        params={"text": OPEN_LABEL_TEXT, "answer": "不知道", "subject": OPEN_LABEL},
        checks=(
            _eq("创建成功", "status", 201),
            _eq("领域名保留原标签", "domain_name", OPEN_LABEL),
            _eq("领域展示名保留原标签", "domain_label", OPEN_LABEL),
            _true("标记为通用领域", "generic"),
            _true("带通用入口", "has_intake"),
        ),
    ),
    Case(
        id="O04",
        category="开放领域入口",
        intent="一次澄清可以改变展示领域，但不产生诊断",
        contract="领域改按 decision；clarifier 用尽；notice 说明改按；无 answer 键",
        scenario="clarifier_flow",
        params={
            "text": UNKNOWN_TEXT,
            "answer": "不知道",
            "clarifier_answer": UNKNOWN_CLARIFIER,
            "second_answer": "再补充一句。",
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("澄清返回 200", "status", 200),
            _eq("改按决策问题处理", "domain_name", "decision"),
            _eq("展示名为生活决策", "domain_label", "生活决策"),
            _false("澄清机会已用尽", "clarifier_after_first"),
            Check("notice 说明改按新领域", "notice", "contains", "改按"),
            _false("不含 answer 键", "has_answer_key"),
        ),
    ),
    Case(
        id="O05",
        category="开放领域入口",
        intent="第二次澄清不会被追加，返回当前视图",
        contract="200；notice 说明只接受一次；gaps 不变；clarifier 仍为空",
        scenario="clarifier_flow",
        params={
            "text": UNKNOWN_TEXT,
            "answer": "不知道",
            "clarifier_answer": UNKNOWN_CLARIFIER,
            "second_answer": "再补充一句。",
        },
        checks=(
            _eq("第二次仍返回 200", "second_status", 200),
            Check("notice 说明只接受一次", "second_notice", "contains", "只接受一次"),
            _true("gaps 没有被改写", "gaps_equal"),
            _false("没有新的澄清问题", "second_clarifier"),
        ),
    ),
    Case(
        id="O06",
        category="开放领域入口",
        intent="澄清内容没有领域线索时保持通用标签",
        contract="200；domain 仍为 generic；clarifier 用尽；没有诊断",
        scenario="intake_answer",
        params={
            "text": UNKNOWN_TEXT,
            "answer": "不知道",
            "endpoint": "intake",
            "post": UNKNOWN_NO_CUE,
        },
        checks=(
            _eq("澄清返回 200", "status", 200),
            _eq("仍为通用领域", "domain_name", "generic"),
            _false("澄清机会已用尽", "clarifier_after_post"),
            _false("没有生成诊断", "has_diagnosis"),
        ),
    ),
    Case(
        id="O07",
        category="开放领域入口",
        intent="有把握的入口拒绝澄清请求",
        contract="代码入口 clarifier=None；POST /intake -> 409",
        scenario="intake_answer",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "endpoint": "intake",
            "post": "补充一句。",
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _eq("没有待澄清问题返回 409", "status", 409),
        ),
    ),
    Case(
        id="O08",
        category="开放领域入口",
        intent="超长澄清补充被拒绝",
        contract="500 字以上 -> 422",
        scenario="intake_answer",
        params={
            "text": UNKNOWN_TEXT,
            "answer": "不知道",
            "endpoint": "intake",
            "post": "补" * 501,
        },
        checks=(_eq("超长补充返回 422", "status", 422),),
    ),
    # --- Known domain with no annotated graph --------------------------------
    Case(
        id="K01",
        category="已知领域下限",
        intent="识别为数学但没有标注图/生成器时显式 422",
        contract="422；detail 指出现行环境不能建图，不静默降级成假诊断",
        scenario="start",
        params={"text": MATH_UNSEEN, "answer": "x=2 或 x=3"},
        checks=(
            _eq("显式拒绝", "status", 422),
            Check("detail 说明不能建图", "detail", "contains", "SYNAPSE_LLM_MODE=off"),
        ),
        subset=True,
    ),
    Case(
        id="K02",
        category="已知领域下限",
        intent="识别为物理但没有标注图/生成器时显式 422",
        contract="422；detail 说明不能建图",
        scenario="start",
        params={"text": PHYSICS_UNSEEN, "answer": "a=5 m/s^2"},
        checks=(
            _eq("显式拒绝", "status", 422),
            Check("detail 说明不能建图", "detail", "contains", "不能建图"),
        ),
    ),
    Case(
        id="K03",
        category="已知领域下限",
        intent="显式声明已知领域也不能绕过“没有图”的下限",
        contract="subject=physics + 物理题 -> 422（标签不是绕过方式）",
        scenario="start",
        params={"text": PHYSICS_UNSEEN, "answer": "a=5 m/s^2", "subject": "physics"},
        checks=(
            _eq("显式拒绝", "status", 422),
            Check("detail 说明不能建图", "detail", "contains", "不能建图"),
        ),
    ),
    Case(
        id="K04",
        category="已知领域下限",
        intent="唯一标注题仍然走探针链路，不退化成通用入口",
        contract="201/PROBE；prompt 非空；intake=None；domain=math/formal",
        scenario="start",
        params={
            "text": MATH_SEED_TEXT,
            "answer": "a≥1/e",
            "work": MATH_WORK,
        },
        checks=(
            _eq("创建成功", "status", 201),
            _eq("进入探针状态", "state", "PROBE"),
            _true("有第一个探针", "prompt"),
            _false("不是通用入口", "has_intake"),
            _eq("领域为数学", "domain_name", "math"),
            _eq("验证方式为形式验证", "verification", "formal"),
        ),
    ),
    # --- CHC attribution (problem-side demand tags) --------------------------
    Case(
        id="H01",
        category="CHC 归因",
        intent="打开 CHC 后，卡面携带 7 维题目需求标签",
        contract=(
            "diagnosis v0.2；dimensions 为 Gf/WM；all_dimensions 恰好 7 维；"
            "note 写明是题目需求标签、不是能力测评；卡面无 ability/score 字段"
        ),
        scenario="chc_card",
        params={
            "config": "chc_on",
            "text": MATH_SEED_TEXT,
            "answer": "a≥1/e",
            "work": MATH_WORK,
        },
        checks=(
            _eq("创建成功", "start_status", 201),
            _true("生成诊断卡", "has_diagnosis"),
            _eq("卡版本为 0.2", "diagnosis_version", "0.2"),
            _true("携带 attribution", "has_attribution"),
            _eq("焦点维度为 Gf/WM", "dims", ["Gf", "WM"]),
            _eq("七个维度都在", "all_dim_count", 7),
            _eq("维度顺序固定", "all_dims", CHC_KEYS),
            Check("note 说明是题目需求", "note", "contains", "题目需求标签"),
            Check("note 说明不是能力测评", "note", "contains", "不是能力测评"),
            _eq("卡面没有 ability/score 字段", "card_ability_keys", []),
            _false("不含 answer 键", "has_answer_key"),
        ),
        subset=True,
    ),
    Case(
        id="H02",
        category="CHC 归因",
        intent="关闭 CHC 时卡面不携带 attribution，版本仍是 0.1",
        contract="diagnosis v0.1；card 中没有 attribution 字段",
        scenario="chc_card",
        params={"config": "off", "text": MATH_SEED_TEXT, "answer": "a≥1/e", "work": MATH_WORK},
        checks=(
            _true("生成诊断卡", "has_diagnosis"),
            _eq("卡版本为 0.1", "diagnosis_version", "0.1"),
            _false("没有 attribution", "has_attribution"),
        ),
    ),
    # --- Answer isolation ----------------------------------------------------
    Case(
        id="A01",
        category="答案隔离",
        intent="标注题的学习态响应与重新读取都不携带答案",
        contract="创建与 GET 都没有 answer/solution 键",
        scenario="start_reload",
        params={
            "text": MATH_SEED_TEXT,
            "answer": "a≥1/e",
            "work": MATH_WORK,
        },
        checks=(
            _eq("创建成功", "status", 201),
            _eq("重新读取成功", "get_status", 200),
            _false("创建响应不含 answer 键", "has_answer_key"),
            _false("创建响应不含 solution 键", "has_solution_key"),
            _false("GET 响应不含 answer 键", "get_has_answer_key"),
            _false("GET 响应不含 solution 键", "get_has_solution_key"),
        ),
    ),
    Case(
        id="A02",
        category="答案隔离",
        intent="普通退出不展示答案",
        contract="exit 后 state=CLOSED；没有 answer/solution 键；notice 说明不展示",
        scenario="exit_flow",
        params={"text": MATH_SEED_TEXT, "answer": "a≥1/e", "work": MATH_WORK, "reveal": False},
        checks=(
            _eq("退出返回 200", "status", 200),
            _eq("停在 CLOSED", "state", "CLOSED"),
            _false("不含 answer 键", "has_answer_key"),
            _false("不含 solution 键", "has_solution_key"),
            Check("notice 说明不展示最终答案", "notice", "contains", "不展示最终答案"),
        ),
        subset=True,
    ),
    Case(
        id="A03",
        category="答案隔离",
        intent="只有显式 reveal 才读取答案库",
        contract="exit {reveal:true} 返回标注答案与解法",
        scenario="exit_flow",
        params={"text": MATH_SEED_TEXT, "answer": "a≥1/e", "work": MATH_WORK, "reveal": True},
        checks=(
            _eq("退出返回 200", "status", 200),
            _true("返回 answer 键", "has_answer_key"),
            _eq("返回标注答案", "answer", MATH_SEED_ANSWER),
            _true("返回 solution 键", "has_solution_key"),
            _true("解法非空", "solution_has_text"),
        ),
    ),
    Case(
        id="A04",
        category="答案隔离",
        intent="生成题/通用题没有存储解法，reveal 也不编造",
        contract="通用入口 exit+reveal 仍无 answer/solution；notice 说明没有存储解法",
        scenario="exit_flow",
        params={"text": CODE_TEXT, "answer": "不知道", "reveal": True},
        checks=(
            _eq("退出返回 200", "status", 200),
            _false("不含 answer 键", "has_answer_key"),
            _false("不含 solution 键", "has_solution_key"),
            Check("notice 说明没有存储解法", "notice", "contains", "没有存储解法"),
        ),
    ),
    # --- Published contract shape -------------------------------------------
    Case(
        id="S01",
        category="契约形状",
        intent="intake 内嵌 review 按发布 schema 校验",
        contract="原始响应与去掉 null 后都应按发布 schema 零错误",
        scenario="start",
        params={
            "text": WRITING_TEXT,
            "answer": WRITING_ANSWER,
            "work": WRITING_WORK,
            "subject": "写作",
        },
        checks=(
            _eq("创建成功", "status", 201),
            _eq(
                "原始响应符合发布 schema",
                "review_published_schema_errors_count",
                0,
            ),
            _eq(
                "去掉 null 后内容符合 schema",
                "review_clean_schema_errors_count",
                0,
            ),
        ),
        expected="pass",
        reason=(
            "SessionOut 的 GenericReviewOut 现在对 options/tradeoff_question/execution 使用 "
            "exclude_if=value is None，intake 内嵌 review 不再输出 null 占位。"
        ),
    ),
    Case(
        id="S02",
        category="契约形状",
        intent="review/run 响应符合已发布的 generic-review v0.1 schema",
        contract="直接按 specs/generic-review.schema.json 校验零错误",
        scenario="review_run",
        params={
            "text": CODE_TEXT,
            "answer": "不知道",
            "code": CODE_SNIPPET,
            "tests": CODE_TESTS,
        },
        checks=(
            _eq("复盘接口返回 200", "status", 200),
            _eq("schema 校验零错误", "schema_errors_count", 0),
        ),
        subset=True,
    ),
)


SUBSET_IDS: tuple[str, ...] = tuple(case.id for case in CASES if case.subset)
