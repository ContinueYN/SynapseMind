# Changelog

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