# Changelog

## 0.4.0 — 2026-10-28

**M1 walking skeleton：单题文本闭环可本地运行。**

- `apps/api`：FastAPI + Pydantic v2 + 分层包（domain/application/infrastructure/api），内存仓储；
- 显式状态转移表（10 状态）、规则版步骤对齐、3 假设后验、2–6 轮探针、L2 卡点卡；
- 证据链 `Evidence`/`EvidenceChain`：记录来源、主张、支持假设与轮次，卡点卡从链上取证据；
- 答案泄漏防护：禁用词 + 5-gram 出口装饰器；学习模式 DTO 无 `solution`/`final_answer`；
- `apps/web`：Next.js 15 App Router 三个页面（交题 / 追问 / 卡点卡）、可复用组件、typed API client；
- 契约生成：`scripts/contracts.py` 从 FastAPI OpenAPI 生成 `generated.ts`，Web 响应类型不再手抄；
- 一键启动：`python scripts/dev.py` 自动建 venv/装依赖/起两个进程，`--check` 只检查，`--smoke` 启动后自动停；
- 26 个后端测试、ruff/mypy/import-linter 通过；前端 typecheck/lint/build 通过；
- CI 增加 API 与 Web 两组检查；`scripts/check_repo.py` 跳过 `node_modules`/`.next` 等生成目录；
- 明确边界：仅一道种子题、无数据库/LLM/OCR/鉴权；换题返回 422，不静默套用示例图。

## 0.3.0 — 2026-10-28

**技术选型重做：从 Java/Spring 主栈改为 TypeScript Web + Python 后端。**

- 新增 [ADR-0001](docs/adr/0001-language-and-code-architecture.md)：5 个无共享记忆子 Agent 独立评审、评分、冲突裁决、迁移与改选条件；
- 选定 Next.js + TypeScript（Web/SEO/SSE 外壳）+ Python 3.12 + FastAPI（状态机/诊断/AI/评测）+ PostgreSQL/pgvector + Redis；
- 明确不用 Java/Spring/MySQL、4 部署单元/7 服务边界、K8s、多 Agent 框架；
- `apps/api` 从 Java 改为 Python 脚手架；`apps/ai-worker` 重命名为 `apps/worker`；
- 更新 apps/infra/eval 的 README 与目标命令；删除未落地的 `services/`、`packages/` 空脚手架；
- 记录代价：skill.txt 的 Java/Spring/MySQL/Caffeine 在 MVP 主链路失去落点，保留为 Phase 2 企业适配器/作品集分支；
- 第 7/8 章已按 ADR 重写；本地 DOCX/PDF 重生成（56 页、49 表、3 图），但生成物不入库，发布时作为 Release 附件；第 11 章保留旧 Java 设计过程作为方法记录。

## 0.2.0 — 2026-10-28

**重做为“单题诊断引导”。**

- 删除“12 分钟标准化测评 / 学习 OS / 10 周商业计划”的主线定位；
- 新增单题闭环：交题 → 拆解法图 → 步骤对齐 → 2–6 轮追问 → 卡点卡 → 3 分钟微干预 → 迁移验证；
- 新增 L0–L6 卡点分类、解法图 schema、假设后验与停止条件；
- 新增 Prompt/Agent 状态机、答案四道闸、50 条红队门槛；
- 新增 RAG 五类知识卡、pgvector + BM25 + RRF + rerank；
- 新增 4 个部署单元 / 7 个服务边界、14 张核心表；
- 新增 `skill.txt` 11 项逐条映射；
- 新增 8 周 MVP、评测指标、成本、风险与 kill criteria；
- 文档产物：56 页 DOCX / PDF、49 张表、3 张图。

## 0.1.0 — 2026-10

- 初版“基于脑可塑性与智商核心构成能力的学习引导系统”；
- 偏“测评 + 学习 OS + 增长”，已移到本地 `_local/archive/v0-broad-os/`，不入库、不再维护。