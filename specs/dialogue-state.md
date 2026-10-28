# 追问状态机 v0.1

> 目标：LLM 只能在允许的状态里做允许的动作；状态转移由代码决定，不由模型自由发挥。

## 状态

| 状态 | 进入条件 | 允许动作 | 退出 |
|---|---|---|---|
| `INGEST` | 收到题目/图片 | 校验、脱敏、去重 | `PARSE` |
| `PARSE` | 输入合法 | OCR、LaTeX 归一化、题型识别 | `ALIGN` 或 `NEED_INPUT` |
| `NEED_INPUT` | 题目不清/缺答案 | 请用户确认题目、补一步过程 | `PARSE` |
| `ALIGN` | 有解法图 + 学生步骤 | 步骤对齐、找第一处偏离 | `PROBE` / `DIAGNOSE` |
| `PROBE` | 有 ≥2 个候选假设 | `ask` / `hint` / `confirm` | `PROBE` / `DIAGNOSE` |
| `DIAGNOSE` | 后验 ≥0.80 且 margin ≥0.25，或轮次=6 | `diagnose` | `INTERVENE` / `STOP` |
| `INTERVENE` | 已出卡点卡 | 3 分钟讲解 + 同构题 | `VERIFY` |
| `VERIFY` | 用户完成同构题 | 预约 24h/7d 迁移 | `CLOSED` |
| `STOP` | 用户退出/超界/低置信 | 给出口或“暂不能确定” | `CLOSED` |
| `CLOSED` | 会话结束 | 只读、可复核 | — |

## 转移

```text
INGEST → PARSE → ALIGN → PROBE ⇄ PROBE
                         ├─→ DIAGNOSE → INTERVENE → VERIFY → CLOSED
                         └─→ STOP → CLOSED
PARSE → NEED_INPUT → PARSE
ALIGN → DIAGNOSE（只有 1 个明显断点，且证据充分）
ALIGN → STOP（题目超纲/无法建图）
```

## 每轮输入

```json
{
  "session_id": "S_9001",
  "turn": 3,
  "state": "PROBE",
  "problem_id": "P_FUNC_001",
  "graph_version": "g1",
  "student_last_answer": "1/x，没有零点",
  "hypotheses": [
    {"id": "H_L2", "label": "条件转译/参数分类", "posterior": 0.72},
    {"id": "H_L1", "label": "概念不清", "posterior": 0.18},
    {"id": "H_L4", "label": "计算错误", "posterior": 0.10}
  ],
  "asked_probes": ["p_a0_derivative"],
  "max_turns": 6
}
```

## 每轮输出

```json
{
  "action": "ask",
  "question": "a=0 时，f'(x) 是什么？在 x>0 上有零点吗？",
  "options": ["1/x，没有零点", "1/x - 0，有零点", "不确定"],
  "target_hypotheses": ["H_L2", "H_L1"],
  "hint_level": 0,
  "reason_code": "DISCRIMINATE_PARAM_CASE",
  "confidence": 0.62
}
```

`action` 只能是：`ask`、`hint`、`confirm`、`diagnose`、`intervene`、`stop`、`offer_answer_exit`。

## 硬约束

1. **一次一问**：`question` 只允许一个问号；选项 ≤4。
2. **前 3 轮不给最终答案**；`solution` 字段不存在。
3. **LLM 不决定状态**：只输出动作候选，状态由代码按守卫推进。
4. **不重复探针**：`asked_probes` 命中则换探针。
5. **不知道就降级**：用户答“不知道” → 二选一/具体数值/半成品，不重复原题。
6. **低置信不硬判**：`posterior < 0.55` → `stop` 或继续问；不得输出确定卡点。
7. **轮次上限 6**：到 6 轮无论置信度，必须收束为“可能卡点 + 还缺什么证据”。
8. **用户可退出**：`offer_answer_exit` 是合法动作；退出后不生成卡点卡。

## 答案泄漏防线

| 层 | 做法 |
|---|---|
| 检索 | `chunk_type != solution` 硬过滤 |
| Prompt | 系统提示禁止给最终答案/完整步骤 |
| Schema | 输出无 `solution` 字段；`question` 长度/问号数校验 |
| 出口 | 5-gram 重叠 + SymPy 等价检测；命中则替换为追问 |
| 回归 | 50 条红队；泄漏 0 才发布 |

## 失败与降级

| 失败 | 降级 |
|---|---|
| 模型超时 | 模板追问 + “稍后继续” |
| JSON 不合法 | 重试 1 次；仍失败用规则探针 |
| 解法图缺失 | 只做“步骤级提示”，不声称诊断 |
| 用户拒绝回答 | 给“直接看答案”出口，退出学习模式 |
| 多卡点 | 只处理最早一个；其余记入“待确认” |