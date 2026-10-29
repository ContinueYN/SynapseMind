# specs

**契约先于代码。** 这里的文件是运行时 JSON、状态机与数据结构的单一来源；`apps/` 的实现必须与它们一致。

| 文件 | 用途 | 消费者 |
|---|---|---|
| [`problem-input.schema.json`](problem-input.schema.json) | 交题入口 | Web、API |
| [`solution-graph.schema.json`](solution-graph.schema.json) | 题目解法图 | API（生成物运行时严格校验）、内容后台 |
| [`diagnosis.schema.json`](diagnosis.schema.json) | 卡点卡输出 | API、Web、评测 |
| [`dialogue-state.md`](dialogue-state.md) | 追问状态机与事件 | API、AI 编排、评测 |

## 约定

1. 先改 spec，再改代码；破坏性变更升 `version`。
2. JSON 使用 UTF-8、`snake_case`、时间为 ISO 8601 UTC。
3. 学习模式的响应中**不允许有 `solution` 字段**；这是硬约束，不是建议。
4. `confidence < 0.55` 时只能输出“可能卡点”，不能下确定结论。
5. 所有 `id` 用稳定字符串，不用自增整数做外部契约。

## 校验

```bash
python scripts/checks/check_repo.py
```

当前只校验 JSON 可解析与文件存在。

解法图生成物是例外：`infrastructure/llm/graph.py` 在运行时用 `jsonschema` 直接加载本目录的 `solution-graph.schema.json` 做严格校验（M2.5 S4）。契约只有这一份，代码不另抄一套字段。

`solution-graph.schema.json` 的 `probe.evidence` 是可选字段：生成图必须为每个选项给出 log-odds 权重（结构规则强制），手写种子图可省略并从 `EVIDENCE` 取权重；字段形状在 schema 里约束，跨字段一致性（选项覆盖、targets 对应、每个 target 至少被使用一次）在 `domain/problem/graph_structure.py` 里校验（M2.5 S5）。**键是选项字母**（`A`/`B`/`C`…，与 `SubmitAnswerCommand.option_id` 同一套编码），不是选项文本——`HypothesisSet.observe()` 按字母查表，写错键名不报错，只是那次作答不更新后验。

图顶层的 `claim` 也是可选字段（M2.5 S5），把答案写成机器可证伪的形式：

```json
"claim": {
  "kind": "parameter_range",
  "parameter": "a",
  "variable": "x",
  "variable_domain": "(0,+inf)",
  "constraint": {"expression": "log(x) - a*x", "relation": "<="},
  "answer": [{"lower": "1/E", "upper": null, "lower_inclusive": true, "upper_inclusive": false}]
}
```

含义是 `∀x∈variable_domain: expression <relation> 0 ⇔ parameter ∈ answer`；`answer` 的端点是 SymPy 表达式字符串，`null` 表示无穷，多个区间即并集。v1 只支持这一种形状（参数区间）；求一个值、解集、证明题没有 `claim`，验证结果为 `unknown`，不算失败。`kind`/`relation` 不在支持范围内时，结构规则会丢弃 claim 并记一条修复（`claim_dropped_unsupported`），图仍然可用。校验与反例由 `infrastructure/verification/` 执行（`pass|fail|unknown`）：`fail` 会带具体反例让建图器重试一次，仍失败则丢弃 claim（`claim_dropped_refuted`）、保留图，反例留在 `GraphBuildResult.verification` 里。
