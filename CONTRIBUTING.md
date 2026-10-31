# 贡献指南

## 先读什么

1. [`README.md`](README.md)：产品范围、诊断链路与当前实现边界。
2. [`specs/dialogue-state.md`](specs/dialogue-state.md)：状态机与硬约束。
3. [`docs/design/chapters/00-一页纸.md`](docs/design/chapters/00-一页纸.md)：产品定义与示例。
4. [`docs/design/chapters/04-诊断引擎.md`](docs/design/chapters/04-诊断引擎.md)：解法图、对齐与卡点判定。
5. [`docs/adr/0001-language-and-code-architecture.md`](docs/adr/0001-language-and-code-architecture.md)：技术选型与改选条件。

## 工作方式

- **契约先行**：改接口、状态机或数据结构，先改 `specs/`，再改实现。
- **单一改动**：一个 PR 只做一件事；文档与代码分开提交。
- **可回滚**：数据库迁移只做向前兼容；破坏性变更附迁移说明。
- **不提交密钥**：`.env`、模型 key 与学生原图不进入仓库。

## 分支与提交

```text
feat/<scope>-<short>
fix/<scope>-<short>
docs/<scope>-<short>
chore/<scope>-<short>
```

提交信息使用祈使句：

```text
feat(diagnosis): add param-case probe for a<=0
fix(web): keep one question per turn on mobile
docs(design): clarify answer-leak gates
```

## 文档改动

公开文档只保留产品定义、诊断引擎与 ADR。改文档时直接修改对应的 Markdown；DOCX/PDF 构建脚本与产物属于本地工作流，不进入仓库。

## PR 检查

- [ ] 后端：`ruff check src tests`、`ruff format --check src tests`、`mypy src`、`lint-imports`、`pytest`
- [ ] 前端：`npm run typecheck`、`npm run lint`、`npm test`、`npm run build`
- [ ] 新增或修改的接口有 JSON Schema 或契约测试
- [ ] 学习模式响应不含 `solution` 字段
- [ ] 新增追问有对应的红队用例
- [ ] 没有提交学生原文、密钥或临时大文件

## 评审重点

1. 是否仍围绕单题诊断，而没有扩张为题库或课程平台。
2. 卡点是否有证据、排除项与置信度。
3. 模型不可用、题目无法建图、用户拒绝回答时是否有明确出口。
4. 是否遵守数据最小化与未成年人保护要求。

## License

原创代码使用 [MIT](LICENSE)。提交第三方代码前确认许可兼容。