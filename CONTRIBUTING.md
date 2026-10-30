# 贡献指南

## 先读什么

1. [`README.md`](README.md) —— 产品是什么、不是什么；
2. [`STRUCTURE.md`](STRUCTURE.md) —— 每个目录放什么、不放什么；
3. [`docs/design/chapters/00-一页纸.md`](docs/design/chapters/00-一页纸.md) —— 一页纸；
4. [`specs/dialogue-state.md`](specs/dialogue-state.md) —— 状态机与硬约束；
5. [`docs/design/chapters/08-skill映射.md`](docs/design/chapters/08-skill映射.md) —— 能力与落点。

## 工作方式

- **spec 先行**：改接口/状态机/数据契约，先改 `specs/`，再改代码。
- **小 PR**：一个 PR 只做一件事；文档 PR 与代码 PR 分开。
- **可回滚**：数据库只做向前兼容迁移；破坏性变更写迁移说明。
- **不提交密钥**：`.env`、模型 key、学生原图都不进仓库。

## 分支与提交

```text
feat/<scope>-<short>     新功能
fix/<scope>-<short>      修复
docs/<scope>-<short>     文档
chore/<scope>-<short>    工程
```

提交信息用祈使句：

```text
feat(diagnosis): add param-case probe for a<=0
fix(web): keep one question per turn on mobile
docs(design): clarify answer-leak gates
```

## 文档改动

改 `docs/design/chapters/` 下的源文件；`docs/design/release/` 是本地生成物，不提交，也不直接改。

```bash
python -m pip install -r tools/requirements.txt
python tools/diagrams.py
python tools/merge_markdown.py
python tools/generate_docx.py
pwsh tools/update_toc_and_export.ps1   # Windows + Word
```

## PR 检查清单

- [ ] 后端：`cd apps/api && ruff check src tests && ruff format --check src tests && mypy src && lint-imports && pytest`
- [ ] 前端：`cd apps/web && npm run typecheck && npm run lint && npm test && npm run build`
- [ ] 新增/修改的接口有 spec 或 JSON Schema
- [ ] 学习模式响应没有 `solution` 字段
- [ ] 新增 Prompt 有对应的红队用例
- [ ] 没有把学生原文/密钥/大文件临时文件提交进来

## 评审重点

1. **是否偏离单题诊断**：不要又做成题库、课程平台、12 分钟测评。
2. **是否可验证**：卡点有没有证据、排除项、置信度。
3. **是否可降级**：模型挂了/用户不答/题目建不了图，是否有出口。
4. **是否保护未成年人**：数据最小化、7 天删除、不做广告画像。

## License

原创代码使用 [MIT](LICENSE)。提交第三方代码前先确认许可兼容。