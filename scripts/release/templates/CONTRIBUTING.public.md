# 贡献指南

## 先读什么

1. [`README.md`](README.md)：产品是什么、不是什么；
2. [`docs/adr/0001-language-and-code-architecture.md`](docs/adr/0001-language-and-code-architecture.md)：技术选型与改选条件；
3. [`specs/dialogue-state.md`](specs/dialogue-state.md)：状态机与硬约束；
4. [`apps/README.md`](apps/README.md)：运行单元边界。

## 工作方式

- **spec 先行**：改接口、状态机或数据契约，先改 `specs/`，再改代码。
- **小 PR**：一个 PR 只做一件事；文档与代码尽量分开。
- **可回滚**：数据库迁移只做向前兼容；破坏性变更写说明。
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
```

## PR 检查清单

- [ ] `python scripts/checks/check_repo.py`
- [ ] 后端：`cd apps/api && ruff check src tests && ruff format --check src tests && mypy src && lint-imports && pytest`
- [ ] 前端：`cd apps/web && npm run typecheck && npm run lint && npm run build`
- [ ] 新增/修改的接口有 spec 或 JSON Schema
- [ ] 学习模式响应没有 `solution` 字段
- [ ] 没有把学生原文、密钥或大文件临时文件提交进来

## 评审重点

1. **是否偏离单题诊断**：不要又做成题库、课程平台或长测评。
2. **是否可验证**：卡点有没有证据、排除项、置信度。
3. **是否可降级**：模型不可用、用户不答、题目建不了图时，是否有出口。
4. **是否保护未成年人**：数据最小化、按需删除、不做广告画像。

## License

原创代码使用 [MIT](LICENSE)。React Bits 组件另有许可限制，见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。