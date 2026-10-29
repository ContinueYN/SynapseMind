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

`solution-graph.schema.json` 的 `probe.evidence` 是可选字段：生成图必须为每个选项给出 log-odds 权重（结构规则强制），手写种子图可省略并从 `EVIDENCE` 取权重；字段形状在 schema 里约束，跨字段一致性（选项覆盖、targets 对应、每个 target 至少被使用一次）在 `domain/problem/graph_structure.py` 里校验（M2.5 S5）。