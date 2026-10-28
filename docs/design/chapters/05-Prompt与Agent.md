## 5. Prompt 与 Agent：让“追问”可测试

### 5.1 四个运行时角色

| 角色 | 职责 | 输入 | 输出 | 是否用 LLM |
|---|---|---|---|---|
| **Parser** | OCR 纠错、LaTeX 归一化、题目/答案分离 | 图片/文本 | 结构化题目、用户步骤 | 是（多模态） |
| **Diagnostician** | 生成/读取解法图、对齐步骤、维护假设后验 | 题目图 + 用户步骤 | `candidates[]`、`first_divergence` | 是 + 规则 |
| **Socratic Coach** | 选探针、生成一次一问的追问、降级提示 | 假设集 + 探针库 | 下一句话 + JSON | 是 |
| **Verifier** | SymPy 校验、答案泄漏检测、前后一致性 | 候选回答/诊断 | pass/fail + 修正建议 | 规则 + 小模型 |

内容侧还有一个离线角色 **Curator**：把教材、课标、错因库、提示库整理成可检索的 chunk；它不在用户对话链路里。

### 5.2 状态机：不是“多 Agent 聊天”

```text
INGEST
  → PARSE
  → GRAPH
  → ALIGN
  → HYPOTHESIZE
  → PROBE ──┐
  ↑         │ (最多 6 轮)
  └─────────┘
  → CONFIRM
  → INTERVENE
  → VERIFY
  → CLOSE
```

规则：

- 状态转移由代码控制，LLM 只能在 `PROBE` 内选择“问什么/怎么问”；
- 每次 handoff 写 `from/to/reason/state_version`；
- `PROBE` 每轮必须更新 `candidates[].posterior`；
- 达到停止条件才能进 `CONFIRM`；
- `CONFIRM` 必须让用户评分“像不像你”，低分回到 `HYPOTHESIZE`；
- 任何状态失败，降级到“模板卡 + 人工复核”，不静默重试。

### 5.3 系统提示词（核心版）

```text
你是 SynapseMind 的单题诊断教练。你的任务不是讲完这道题，而是在最多 6 轮内，
找到学生“最早断掉的那个认知动作”，并让他自己确认。

【硬约束】
1. 一次只问一个问题。不要在一句话里问两个“为什么”。
2. 前 3 轮不出现最终答案、完整解法、关键结论。
3. 先引用学生的原话/原步骤，再提问；不要凭空判断。
4. 学生说“不知道”时，降一级：二选一 → 具体数值 → 半成品填空。
5. 不贴标签：不说“你粗心/笨/懒/基础差/不认真”。
6. 不做医学/智商判断；不承诺分数。
7. 每轮输出必须是 JSON，字段见 schema；不要输出 JSON 以外的字。
8. 如果你不确定，action=ask，并在 evidence 里写“待验证”，不要硬下结论。

【当前状态】
problem_graph: {{graph}}
attempt_steps: {{steps}}
candidates: {{candidates}}
turn: {{turn}}
max_turns: 6

【本轮任务】
选择最能区分 top-2 假设的一个探针；生成一句学生能回答的问题。
如果最高后验 ≥0.80 且领先 ≥0.25，action=diagnose。
如果已到第 6 轮，action=diagnose 或 stop。
```

### 5.4 输出 Schema

```json
{
  "type": "object",
  "required": ["turn", "action", "question", "target_hypothesis", "confidence"],
  "properties": {
    "turn": {"type": "integer", "minimum": 1, "maximum": 6},
    "action": {"enum": ["ask", "hint", "confirm", "diagnose", "intervene", "stop"]},
    "question": {"type": "string", "maxLength": 120},
    "options": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    "target_hypothesis": {"type": "string"},
    "probe_id": {"type": "string"},
    "hint_level": {"type": "integer", "minimum": 0, "maximum": 3},
    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "should_end": {"type": "boolean"}
  },
  "additionalProperties": false
}
```

**为什么用 schema**：

- 追问可以被单测：给定假设集，断言输出必须包含某个 `probe_id`；
- 前端可以稳定渲染选项；
- 答案泄漏可以在 schema 层拦截（没有 `solution` 字段）；
- 模型升级时，回归测试有契约。

### 5.5 好问题 / 坏问题

| 场景 | 坏问题 | 好问题 | 为什么 |
|---|---|---|---|
| 漏参数分类 | “你考虑 a<0 了吗？” | “a=-1 时，f'(x)=1/x+1 有零点吗？” | 让事实自己说话 |
| 概念不清 | “极值的必要条件是什么？” | “f'(x)=0 能保证是最大值吗？举个反例。” | 用反例检验 |
| 不会起步 | “你觉得该怎么做？” | “只允许走一步：求导、画图、还是分类？选一个。” | 降低选择负担 |
| 计算错 | “再算一遍。” | “只检查最后一步的符号，`ln(1/a)≤1` 推出什么？” | 定位到具体动作 |
| 元认知 | “你有把握吗？” | “这题你能对几成？为什么？” | 校准而非情绪 |

### 5.6 答案泄漏的四道闸

| 闸 | 位置 | 做法 |
|---|---|---|
| 1. 检索 | RAG | `chunk_type=solution` 在学习模式硬过滤；只召回 `hint/concept` |
| 2. Prompt | 生成 | schema 没有 `solution` 字段；系统提示禁止最终答案 |
| 3. 出口 | 输出 | 5-gram 与标准答案重合 >0.6 拦截；SymPy 等价检测 |
| 4. 回归 | 评测 | 100 条红队 prompt，答案泄漏率必须为 0 |

**注意**：只靠“提示词说不要给答案”一定会破。答案必须从数据、结构、出口三层一起锁。

### 5.7 MCP：把能力暴露给 IDE，而不是再写一套 API

MCP Server 暴露 6 个工具：

| 工具 | 作用 | 权限 |
|---|---|---|
| `get_problem_graph` | 按题目 ID 取解法图 | 读 |
| `align_attempt` | 对齐学生步骤 | 读 |
| `search_concept` | 检索概念卡/提示 | 读 |
| `verify_math` | SymPy 校验表达式/区间 | 读 |
| `next_probe` | 取候选探针 | 读 |
| `record_evidence` | 写诊断证据 | 写（双人复核） |

用途：

- 线上 Agent 调工具；
- 教研在 Cursor/Claude Code 里调同一套工具，批量校对解法图；
- 不需要维护第二套内部 API。

### 5.8 Agent Skills：把“怎么追问”变成可发布资产

目录：

```text
skills/
  diagnostic-review/
    SKILL.md
    skill.yaml
    scripts/check_evidence.py
    references/probe_patterns.md
    evals/golden.jsonl
  hint-policy/
    SKILL.md
    skill.yaml
    scripts/check_answer_leak.py
```

`diagnostic-review` 做两件事：

1. 检查诊断卡是否有证据、排除项、置信度；
2. 检查是否把“假设”写成了“结论”。

`hint-policy` 做两件事：

1. 检查提示层级是否逐级上升；
2. 检查是否在 3 轮内泄漏答案。

这两个 Skill 可以在 CI 里跑，也可以被 IDE 调用。

### 5.9 模型路由与成本

| 任务 | 模型档位 | 占比 | 原因 |
|---|---|---|---|
| OCR 纠错/格式归一 | 小模型/专用 OCR | 30% | 便宜、可批处理 |
| 步骤对齐/分类 | 7B–14B | 40% | 结构化、低创造性 |
| 追问生成 | 32B | 25% | 需要语言自然度 |
| 难题诊断/红队 | 旗舰 | 5% | 少数难例 |

单次诊断 4–6 轮，目标成本 ≤¥0.8；超出预算时，降级为“规则探针 + 模板话术”，不牺牲答案安全。

### 5.10 失败时的兜底

- LLM 超时：返回上一轮缓存 + “我先问一个更简单的问题”；
- JSON 解析失败：重试 1 次，仍失败用模板；
- 置信度 <0.55：不硬判，给 2–3 个可能；
- 用户情绪激烈：停止追问，输出“我们先停一下”，转人工/教师；
- 题目超纲：明确说“这道题当前版本只能做步骤级提示”，不假装能诊断。