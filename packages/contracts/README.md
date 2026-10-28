# packages/contracts

跨应用契约的单一来源。

## 放什么

- OpenAPI 3.1：`diagnose.openapi.yaml`
- JSON Schema：题目输入、解法图、诊断卡、追问输出
- 事件契约：`session.created`、`turn.completed`、`card.issued`
- 生成的 TypeScript 类型/客户端（后续由脚本生成，不手改）

## 不放什么

- 业务实现
- Prompt 正文（在 `apps/api` 或 `specs/`）
- 知识库数据（在 `apps/worker` / 内容库）

## 约定

1. **Pydantic 是唯一真源**：`apps/api` 的模型生成 OpenAPI/JSON Schema，再生成 TS 类型；不要手写两份。
2. 先改 `specs/` 与模型，再生成代码；CI 用 `git diff --exit-code` 防止生成物漂移。
3. 破坏性变更必须升版本号，并在 `CHANGELOG.md` 写迁移说明。
4. 生成代码放 `generated/`，明确标注“勿手改”；不提交 Java DTO（MVP 无 JVM 服务）。

> 当前为空，等 M1 的接口定稿后创建 `diagnose.openapi.yaml`。