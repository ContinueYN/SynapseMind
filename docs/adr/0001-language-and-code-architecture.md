# ADR-0001: 语言与代码架构选择

- **状态**：accepted
- **日期**：2026-10-28
- **决策者**：产品/架构（5 个无共享记忆子 Agent 独立评审 + 主 Agent 综合）
- **相关**：[状态机](../../specs/dialogue-state.md)、[诊断卡 schema](../../specs/diagnosis.schema.json)、[仓库结构](../../README.md)

## 1. 背景

SynapseMind 不是“聊天机器人”，而是一个**确定性状态机 + 受控 LLM 输出 + 证据链**的单题诊断产品：

- 输入：一道题 + 学生自己的答案/过程，或“完全不会”；
- 在线：2–6 轮追问，SSE 流式，首问 P95 <8s；
- 核心：步骤对齐、假设后验、卡点判定、答案不泄漏；
- 离线：OCR 后处理、知识 ETL、100 条 golden 评测、50 条红队；
- MVP：100 道题、30 道深标、40–60 beta。

原方案默认 **Java 21 + Spring Boot 3/Spring Cloud + Next.js + Python 离线**。本次要求是：
**语言按工作负载选最合适的，不因难度或现有技能栈迁就。**

## 2. 目标函数

“最优”不是“性能最强”或“最先进”，而是对这个产品加权最高：

| 维度 | 权重 | 说明 |
|---|---:|---|
| 契约一致性 | 25% | 状态迁移、LLM JSON、证据引用、零泄漏判定、golden 回放必须一致 |
| 认知负担 | 20% | 3 个人要同时维护几种语言、几套类型、几套测试 |
| AI/数学生态 | 20% | SymPy/CAS、OCR、RAG、embedding、评测 |
| 可靠性与可定位性 | 20% | 状态机并发、幂等、SSE 断线、模型超时、审计 |
| 运维面 | 15% | 部署单元、依赖、排障、成本 |

**性能不进表**：首问 8s 里九成是模型首 token；应用层预算 <300ms；40–60 beta 的 SSE 是几十到几百条，四个候选都过剩一个数量级。成本 ¥0.8/次由 token 路由决定，与语言无关。

## 3. 五个独立评审（无共享记忆）

每个 Agent 拿到同一份事实包，但看不到彼此输出；下面是原始结论，不改写。

| 评审 | 结论 | 置信度 | 关键理由 |
|---|---|---|---|
| 分层选型 | **TS 只做 Web，Python 做后端内核**；否决 Java 核心 | 高 | golden 回放要 in-process 跑生产状态机；SymPy 在首 token 前，状态机放 TS 会变成两套表示 |
| TypeScript 优先 | TS 主栈（Next.js + Fastify）+ Python 边车 | 0.75 | zod 单一真源、SSE/流式最短路径、一套 CI；符号计算/OCR 必须 Python |
| Python 优先 | FastAPI + Next.js | 0.80 | CAS、Pydantic、评测闭环三者都在 Python；2 种语言、2 个进程 |
| JVM 核心 | Java 21 + Spring Boot 3.5（MVC+Loom）+ Next + Python 三旁路 | 0.70 | 状态机/事务/审计最强；但 AI 生态弱、三语言对 MVP 是透支 |
| 可靠性/运维 | Python 全栈 4.60 > TS 4.00 > JVM 3.63 = Go 3.63 | 0.75 | 契约权重最高；MVP 故障来自 LLM 不可控与跨进程契约，不是 JVM 吞吐 |

**收敛**：3/5 明确选 Python 后端；TS 是唯一有实力的备选；JVM 只在“机构采购 + 强审计 + Java 团队”时成立。

## 4. 选项与评分

1–5 分，按 §2 权重加权。

| 维度 | A：TS 全栈 + Py AI | B：Python 全栈 | C：JVM + TS + Py | D：Go + TS + Py |
|---|---:|---:|---:|---:|
| 契约 25% | 4 | **4.5** | 4 | 3.5 |
| 认知 20% | 4 | **5** | 2.5 | 3 |
| AI/数学 20% | 4 | **5** | 3 | 3 |
| 可靠性 20% | 4 | 4 | **5** | 4 |
| 运维 15% | 4 | **4.5** | 3.5 | 5 |
| **加权** | **4.00** | **4.60** | **3.63** | **3.63** |

- **A 的问题**：状态机/JSON/SSE 在 TS，SymPy/OCR/评测在 Python；同一状态两套表示，契约漂移是静默的——诊断卡指错卡点但不报错。
- **B 的问题**：Python 无编译期穷尽检查；一个漏 `await` 的同步调用会毒化整个事件循环。用显式转移表 + `state × event` 穷举测试 + 全链路 async + CPU 出进程对冲。
- **C 的问题**：JVM 的可靠性优势在 MVP 兑现不了，因为故障来自 LLM 输出和跨进程契约；三语言两运行时对 MVP 是结构性透支。
- **D 的问题**：Go 没有 sum type，产品心脏（状态机/判别联合）用最弱表达力写；AI/数学仍要 Python，多一种语言没有回报。

## 5. 决策

**采用 B：TypeScript 只做 Web，Python 做唯一后端内核。**

| 层 | 选型 | 说明 |
|---|---|---|
| Web | **Next.js 15 App Router + TypeScript** | RSC/ISR 做 SEO 公开页；客户端组件做 SSE；BFF Route Handler 只做鉴权/上传签名/透传 |
| API | **Python 3.12 + FastAPI + Pydantic v2** | 状态机、诊断、会话、证据、鉴权、SSE 同进程 |
| 数据访问 | **SQLAlchemy 2.0 async + Alembic** | 显式 SQL；pgvector 列手写迁移 |
| 数据库 | **PostgreSQL 16 + pgvector + pg_trgm** | 一个主库；JSONB、部分索引、HNSW；**不引 MySQL** |
| 缓存/队列 | **Redis 7 + Arq** | 会话/幂等/限流/SSE 重放；Arq 只跑离线任务 |
| AI 编排 | **进程内 `brain/`** | LiteLLM/供应商 SDK；Pydantic/JSON Schema；重试/降级/回放；不引 LangChain/LangGraph 控制流 |
| 数学/OCR | **SymPy 子进程 + PaddleOCR/Mathpix/VLM** | SymPy 2s 超时、三态；OCR 必须学生确认 |
| 部署 | **3 个容器：web / api / worker** | Nginx；Compose；**不引 K8s、Spring Cloud、MQ、7 服务** |
| 契约 | **Pydantic → OpenAPI → TS 类型** | JSON Schema 同时约束 LLM 输出；`specs/` 是人类可读源 |

**明确不选**：Java/Spring 核心、Go 核心、MySQL、4 部署单元/7 服务边界、多 Agent 框架、K8s。

## 6. 目录与代码架构

### 6.1 目录：按“可部署单元 + 领域”分，不按语言/文件类型分

```text
apps/
  web/                 # Next.js + TS：学生端、教师后台、SEO
  api/                 # FastAPI：状态机、诊断、AI 编排、SSE
  worker/              # Arq：OCR 后处理、ETL、评测、红队（与 api 同镜像）
specs/                 # 状态机、输入/解法图/诊断卡契约
eval/                  # golden / redteam / reports
infra/                 # docker / nginx / observability
docs/
  adr/                 # 本文件与后续决策
  design/              # 产品设计源与产物
```

- `apps/` 是**能独立构建/部署**的单元；`services/` 等真正要拆时再建，不预建空目录。
- 不按 `frontend/`、`backend/`、`java/`、`python/` 分；这些名字不表达领域边界。
- `specs/` 放机器可验证契约；生成的 TS 类型/客户端在 M1 放到 `apps/web/src/lib/api/`，不单独建空 `packages/`；生成物不手改。
- `eval/` 与 `docs/` 平级：诊断质量是产品核心，不是 `tests/` 的附属。

### 6.2 `apps/api` 分层

```text
apps/api/src/synapse/
  domain/          # 纯函数：状态转移、后验、证据、泄漏规则；零 I/O
  application/     # 用例 + ports（Protocol：LLM/Repo/Retriever/CAS/Clock）
  infrastructure/  # llm/ rag/ cas/ db/ ocr/ cache 实现
  api/             # FastAPI 路由、SSE、鉴权、幂等；只做协议转换
  workers/         # Arq 任务入口
```

依赖方向：`api → application → domain`；`infrastructure` 实现 `application.ports`；`domain` 不 import FastAPI/SQLAlchemy/OpenAI。用 `import-linter` 在 CI 强制。

### 6.3 五条硬不变量

1. **状态机是纯函数**：`transition(state, event) -> Result<next, commands>`，转移表显式；LLM 只能填槽位/给动作候选，**不决定下一状态**。
2. **LLM 单一咽喉**：所有调用走 `infrastructure/llm/gateway.py`，统一 schema 校验、重试、路由、token/成本、prompt 哈希落库；评测用录制回放，零成本零抖动。
3. **答案物理隔离**：答案独立表 + 独立仓储；prompt 构建器读不到答案；输出 schema 无 `final_answer`；`guard/leak.py` fail-closed；红队 0 泄漏才发布。
4. **契约单一真源**：Pydantic 模型生成 OpenAPI/JSON Schema/TS 类型；CI `git diff --exit-code` 禁止手改生成物。
5. **评测在生产状态机上跑**：100 条 golden 直接调 `domain`/`application`，不绕 HTTP；`session_events` append-only 支持回放与审计。

## 7. 后果

### 正面

- 2 种语言（TS + Python）、3 个容器；没有 JVM/Spring/MySQL 的额外运行时。
- SymPy、Pydantic、RAG、评测同进程，减少跨进程 fail-open。
- 状态机、诊断卡、SSE、评测共用一套类型/契约；改一个字段，CI 能发现前端/后端/评测不一致。
- MVP 的范围更可控：先把文本闭环跑通，再补 OCR。

### 负面（必须承认）

- **skill.txt 的 Java/Spring/MyBatis/MySQL/Caffeine 在 MVP 主链路失去落点**。这不是疏忽，是“产品最优”对“技能展示”的代价。
- Python 没有编译期穷尽检查；状态机靠转移表 + 穷举测试，不靠类型系统。
- Python 事件循环对同步阻塞敏感；必须全链路 async，SymPy/OCR 全部出进程。
- 若目标是 Java/Spring 岗位作品集，**应选方案 C**，或单独维护 `extensions/enterprise-java`；不要为了简历把主产品做成三语言。

### 对 skill.txt 的处理

- 保留 11 项映射表，但把 Java/Spring/MySQL/Caffeine 标为 **Phase 2 企业适配器 / 作品集分支**，不冒充 MVP 已实现。
- Python/TS 可覆盖：Python、RAG、Prompt、PGvector、ETL、MCP、多 Agent、Docker/Nginx、可观测性、SEO/GEO、SDD、Cursor/Claude Code。
- Go 仅在“SSE 采集 sidecar”保留为可选实验，不进主链路。

## 8. 迁移计划

1. **重命名**：`apps/ai-worker` → `apps/worker`；`apps/api` 从 Java 改为 Python（README/脚手架先改，代码在 M1 落）。
2. **契约**：把 `specs/dialogue-state.md` 的转移表落成 `apps/api/src/synapse/domain/dialogue/table.py`；Pydantic 模型生成 JSON Schema。
3. **数据**：MySQL 设计改为 PostgreSQL；保留 14 张逻辑表，去掉 16 片分库，MVP 单库 + 月分区。
4. **部署**：Compose 从 MySQL 改 Postgres；Nginx 保持 SSE 关闭缓冲；3 个容器。
5. **文档**：`docs/design/chapters/07-技术架构.md`、`08-skill映射.md` 已按本 ADR 重写，本地 DOCX/PDF 已重生成（v0.3，不入库）；第 11 章保留旧 Java 设计过程作为方法记录。
6. **验证**：`python scripts/checks/check_repo.py`、`uv run pytest`、契约生成 diff、500 并发 SSE 压测、100 条 golden 回放。

## 9. 验证实验

| 实验 | 通过标准 | 失败动作 |
|---|---|---|
| 状态机穷举 | `state × event` 全矩阵，非法转移必抛 | 补转移表，不加 `else` 兜底 |
| 契约漂移 | 生成 TS 类型后 `git diff --exit-code` | 禁止手改生成物，修 Pydantic |
| 泄漏 | 50 条红队 + 200 条等价变形，泄漏 0、误杀 ≤2% | 收紧 guard，不靠 prompt |
| 首问 P95 | 文本题 <8s；OCR 并行预热 | 首问不等 OCR；检索并行；限 max_tokens |
| golden 一致 | 30 条深标，卡点一致率 ≥75% | 缩题型/假设空间，不扩功能 |
| SSE 稳定性 | 500 并发 10min，断线可 Last-Event-ID 续播 | 修心跳/重放，不上 WebSocket |

## 10. 改选条件

出现任一，回到本 ADR 改选：

- 后端 Python 生产经验不足，且统一语言带来的收益大于 Python AI 生态的收益 → 切 A（TS 全栈 + Python AI）。
- 出现机构采购级多租户 + 强审计 + 跨系统事务补偿 → 切 C（JVM 核心 + Python AI），不是“为了 Spring 而 Spring”。
- SymPy 校验稳定 >800ms 且落在流式热路径 → 移到 worker 出卡前校验，语言不再被 SymPy 绑定。
- 稳态 SSE >5k 且单实例内存成瓶颈 → 只让 Go 做网关层，AI 仍 Python。

---

**一句话**：这个产品的最优解不是“一种语言打天下”，而是**TypeScript 守住 Web/SEO/SSE 外壳，Python 守住状态机/诊断/AI/评测内核**；Java 留给需要强审计的企业版，不进 MVP。