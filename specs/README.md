# specs

**契约先于代码。** 这里的文件是运行时 JSON、状态机与数据结构的单一来源；`apps/` 的实现必须与它们一致。

| 文件 | 用途 | 消费者 |
|---|---|---|
| [`problem-input.schema.json`](problem-input.schema.json) | 交题入口 | Web、API |
| [`solution-graph.schema.json`](solution-graph.schema.json) | 题目解法图 | API（生成物运行时严格校验）、内容后台 |
| [`diagnosis.schema.json`](diagnosis.schema.json) | 卡点卡输出 | API、Web、评测 |
| [`structure-hint.schema.json`](structure-hint.schema.json) | 结构提示输出（NONE 档学科） | API、Web、评测 |
| [`step-verification.schema.json`](step-verification.schema.json) | 单步验证输出（`POST /sessions/{id}/steps`） | API、Web |
| [`dialogue-state.md`](dialogue-state.md) | 追问状态机与事件 | API、AI 编排、评测 |

## 约定

1. 先改 spec，再改代码；破坏性变更升 `version`。
2. JSON 使用 UTF-8、`snake_case`、时间为 ISO 8601 UTC。
3. 学习模式的响应中**不允许有 `solution` 字段**；这是硬约束，不是建议。
4. `confidence < 0.55` 时只能输出“可能卡点”，不能下确定结论。
5. 所有 `id` 用稳定字符串，不用自增整数做外部契约。

## 校验

`specs/*.json` 必须能被标准 JSON 解析器读取；CI 不再做仓库级文档完整性检查。运行时校验以 `solution-graph.schema.json` 和 `structure-hint.schema.json` 为准。

解法图生成物是例外：`infrastructure/llm/graph.py` 在运行时用 `jsonschema` 直接加载本目录的 `solution-graph.schema.json` 做严格校验（M2.5 S4）。契约只有这一份，代码不另抄一套字段。

`solution-graph.schema.json` 的 `probe.evidence` 是可选字段：生成图必须为每个选项给出 log-odds 权重（结构规则强制），手写种子图可省略并从 `EVIDENCE` 取权重；字段形状在 schema 里约束，跨字段一致性（选项覆盖、targets 对应、每个 target 至少被使用一次）在 `domain/problem/graph_structure.py` 里校验（M2.5 S5）。**键是选项字母**（`A`/`B`/`C`…，与 `SubmitAnswerCommand.option_id` 同一套编码），不是选项文本——`HypothesisSet.observe()` 按字母查表，写错键名不报错，只是那次作答不更新后验。

`structure-hint.schema.json` 是 NONE 档学科（语文/英语/历史）的唯一输出契约（M2.5 S7，v0.2 起为 S8）。它不是卡点卡的简化版，而是**另一种承诺**：`steps[].status`（`covered`/`partial`/`missing`）只描述“解法图里的这一步有没有被写到、是否只写到一部分”，由存在性对齐（线索词 + 分句重合）得出，不代表写得对错；`focus_node_id` 是“下一步先看哪里”（第一个没有完全写到的节点），不是卡点；`disclaimer` 必须写明该学科没有可自动验证的真值。NONE 档不进入 `PROBE`，也不生成卡点卡——`application/commitment.py` 是这条承诺的唯一开关。v0.2 只新增 `partial` 与 `version` 变化；`partial` 不是“写错”，也不改变卡点卡路径。

`step-verification.schema.json` 是「交一步」的响应契约（M2.5 S5 ⑥，v0.1）。`POST /api/v1/sessions/{id}/steps` 只把这一条步骤交给会话所属学科的 `SubjectPlugin.verify()`，**不推进状态、不生成卡点卡、不返回答案**。`fail` 必须带学生自己写的式子或两边数值（例如 `x→0 时左边极限 0.5、右边 2`）；`unknown` 表示开关未开、式子读不懂、没发现可机器证明的错误，或该学科没有可判的真值——`unknown` 不是“这步对了”。数学的等式链校验由 `SYNAPSE_EQUALITY_CHECK` 控制，默认 `off`。

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

含义是 `∀x∈variable_domain: expression <relation> 0 ⇔ parameter ∈ answer`；`answer` 的端点是 SymPy 表达式字符串，`null` 表示无穷，多个区间即并集。v1 只支持这一种形状（参数区间）；求一个值、解集、证明题没有 `claim`，验证结果为 `unknown`，不算失败。`kind`/`relation` 不在支持范围内时，结构规则会丢弃 claim 并记一条修复（`claim_dropped_unsupported`），图仍然可用。校验与反例由 `infrastructure/verification/` 执行（`pass|fail|unknown`）：`fail` 会带着具体反例让建图器**只重写区间**（`graph_claim_repair`，表达式/参数/定义域钉死），仍失败则丢弃 claim（`claim_dropped_refuted`）、保留图，反例留在 `GraphBuildResult.verification` 里。
