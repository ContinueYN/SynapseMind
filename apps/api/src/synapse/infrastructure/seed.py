"""M1 seed data: one fully annotated function-derivative problem."""

from __future__ import annotations

from synapse.domain.problem.models import (
    Probe,
    Problem,
    SolutionGraph,
    SolutionNode,
)

SAMPLE_PROBLEM_ID = "P_FUNC_001"
SAMPLE_SESSION_PREFIX = "S_"

SAMPLE_ANSWER = "a∈[1/e,+∞)"
SAMPLE_SOLUTION = (
    "定义域 x>0。题目要求 f(x)=ln x - a x ≤0 对所有 x>0 成立，即最大值≤0。"
    "分 a≤0 与 a>0：a≤0 时 f(x)→+∞，不满足，排除；"
    "a>0 时 f'(x)=1/x-a，最大值 f(1/a)=-ln a-1≤0，得 a≥1/e。"
    "所以 a∈[1/e,+∞)。"
)

SAMPLE_PROBLEM = Problem(
    id=SAMPLE_PROBLEM_ID,
    title="函数与导数：恒成立与参数分类",
    text=("已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"),
    graph=SolutionGraph(
        problem_id=SAMPLE_PROBLEM_ID,
        version="g1",
        stem="f(x)=ln x - a x，a∈R；f(x)≤0 对所有 x>0 成立。",
        nodes=(
            SolutionNode(
                id="n1",
                type="READ",
                text="确认定义域 x>0，并识别“对所有 x>0 成立”。",
                demand={"V": 0.2, "Gf": 0.2, "WM": 0.2},
                common_errors=("忽略定义域",),
            ),
            SolutionNode(
                id="n2",
                type="CONCEPT",
                text="恒成立转最值：f(x)≤0 对所有 x>0 成立 ⇔ 最大值≤0。",
                demand={"V": 0.5, "Gf": 0.4, "LTS": 0.4},
                common_errors=("把恒成立当成解方程",),
            ),
            SolutionNode(
                id="n3",
                type="CONDITION",
                text="按 a≤0 / a>0 分类；a=0 是边界，不能漏。",
                demand={"Gf": 0.7, "WM": 0.5, "M": 0.4},
                common_errors=("只讨论 a>0", "漏掉 a=0", "把参数当常数"),
                probes=(
                    Probe(
                        id="p_a0_derivative",
                        question="a=0 时，f'(x)=1/x。它在 x>0 上有零点吗？",
                        options=("没有零点", "有一个零点", "不确定"),
                        targets=("H_L2", "H_L1"),
                        correct_option="A",
                    ),
                    Probe(
                        id="p_boundary_check",
                        question="题目要求对所有 x>0 成立。a=0 这个边界要不要单独检查？",
                        options=(
                            "要，a=0 也在 a≤0 这一支里",
                            "不要，a>0 已经覆盖",
                            "不确定",
                        ),
                        targets=("H_L2", "H_L1"),
                        correct_option="A",
                    ),
                ),
            ),
            SolutionNode(
                id="n4",
                type="COMPUTE",
                text="a≤0 时，f(x)=ln x - a x → +∞，所以不满足恒成立。",
                demand={"Gf": 0.4, "WM": 0.3},
                common_errors=("认为 a≤0 自动满足",),
            ),
            SolutionNode(
                id="n5",
                type="COMPUTE",
                text="a>0 时，f'(x)=1/x-a；最大值 f(1/a)=-ln a-1≤0，得 a≥1/e。",
                demand={"Gf": 0.6, "WM": 0.6, "M": 0.5},
                common_errors=("解错 f(1/a)", "忘记等号", "把最大值当成最小值"),
                probes=(
                    Probe(
                        id="p_max_value",
                        question="a>0 时，f'(x)=1/x-a 的零点是哪个？",
                        options=("x=1/a", "x=a", "x=-1/a"),
                        targets=("H_L4", "H_L2"),
                        correct_option="A",
                    ),
                ),
            ),
            SolutionNode(
                id="n6",
                type="CHECK",
                text="a≤0 已排除；只保留 a>0 得到的 a≥1/e，写区间。",
                demand={"WM": 0.3, "M": 0.3},
                common_errors=("只写 a≥1/e", "把并集写成交集"),
                probes=(
                    Probe(
                        id="p_union",
                        question="a≤0 与 a>0 两支分别讨论完后，写最终范围时应该怎么处理？",
                        options=(
                            "取并集",
                            "取交集",
                            "只保留通过恒成立检验的那一支",
                        ),
                        targets=("H_L2",),
                        correct_option="C",
                    ),
                ),
            ),
        ),
        edges=(
            ("n1", "n2"),
            ("n2", "n3"),
            ("n3", "n4"),
            ("n3", "n5"),
            ("n4", "n6"),
            ("n5", "n6"),
        ),
    ),
)
