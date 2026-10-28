# packages/contracts

跨应用契约的单一来源。

## 放什么

- OpenAPI 3.1：`diagnose.openapi.yaml`
- JSON Schema：题目输入、解法图、诊断卡、追问输出
- 事件契约：`session.created`、`turn.completed`、`card.issued`
- 生成的 TypeScript / Java DTO（后续由脚本生成，不手改）

## 不放什么

- 业务实现
- Prompt 正文（在 `apps/api` 或 `specs/`）
- 知识库数据（在 `apps/ai-worker` / 内容库）

## 约定

1. 先改 `specs/` 与 OpenAPI，再改代码。
2. 破坏性变更必须升版本号，并在 `CHANGELOG.md` 写迁移说明。
3. 生成代码放 `generated/`，加入 `.gitignore` 或明确标注“勿手改”。

> 当前为空，等 M1 的接口定稿后创建 `diagnose.openapi.yaml`。