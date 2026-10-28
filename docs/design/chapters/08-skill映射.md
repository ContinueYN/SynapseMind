## 8. skill.txt 逐条映射：每个能力落在哪个文件、哪次演示

> **架构变更（2026-10-28）**：技术选型已由 [ADR-0001](../../adr/0001-language-and-code-architecture.md) 改为 **Next.js + TypeScript（Web）+ Python 3.12 + FastAPI（后端）+ PostgreSQL/pgvector + Redis**。下表把“MVP 已落”与“Phase 2/作品集分支”分开标注；Java/Spring/MySQL/Caffeine 不再冒充 MVP 主链路。
>
> 原则：**不堆名词。** 每一项都要回答：在本项目里，哪个模块用它？演示时看什么？怎么证明不是 PPT 工程？

### 8.1 开发技术 1–7

| # | 能力 | 本项目落点 | 可演示证据 | 验收指标 |
|---|---|---|---|---|
| **1** | AI 辅助编程；Java/Python/Go；Hutool、Lombok；代码规范 | **Python 主栈**（FastAPI/Pydantic/SQLAlchemy）；Python worker 做 OCR 后处理、ETL、评测；Go/Java **不进 MVP**；Hutool/Lombok 不适用；`ruff` + `mypy` + `import-linter` + `pytest` 守规范 | `apps/api/`、`apps/worker/`、`eval/`；CI 报告；AI 生成单测的 commit；Code Review 记录 | 单测覆盖率 ≥60%；`ruff`/`mypy` 0 error；核心规则手写率 100% |
| **2** | 微服务、Spring Cloud、MyBatis、单体拆微服务治理 | MVP **不引** Spring Cloud/MyBatis；`apps/api` 是 Python 模块化单体，按包边界拆；拆分触发条件写进 [ADR](../../adr/0001-language-and-code-architecture.md) 与 `apps/api/README.md`；网关由 Nginx + FastAPI 中间件承担 | `apps/api/src/synapse/` 包边界；import-linter 报告；拆分 ADR；Compose 一键起 | 3 容器一键起；跨层依赖 0 违规；拆分触发条件有数据 |
| **3** | MySQL 设计、SQL 调优、分库分表、索引优化、Druid | MVP 用 **PostgreSQL 16 + pgvector**：14 张逻辑表、联合/覆盖索引、月分区、慢查询日志；**不用 MySQL/Druid**；分库分表留到 Phase 2，MVP 单库 | `schema.sql`；EXPLAIN 前后对比；慢查询 Top20；pgvector HNSW 索引 | 诊断会话查询 P95 <50ms；慢 SQL <10 条/天 |
| **4** | Redis、Caffeine 多级缓存、分布式锁、雪崩/穿透/击穿、哨兵 | Redis 7：会话/提示卡/幂等/限流/SSE 重放；本地缓存用 `cachetools`（Caffeine 等价物）；锁用 Redis Lua 原子命令；布隆/空值缓存防穿透；随机 TTL + 逻辑过期；**Caffeine/Redisson 不适用** | 缓存命中率；锁/幂等测试；故障演练：Redis 挂 30s 仍可出诊断卡 | 缓存命中率 ≥85%；故障演练通过 |
| **5** | Docker、Nginx、Dockerfile、Serverless | 3 容器 Compose（web/api/worker）；Nginx SSE 关闭缓冲 + 限流；OCR/PDF 导出可选 FC | `Dockerfile`；`nginx.conf`；FC 日志；镜像大小对比 | 镜像 <250MB；SSE 不中断；冷启动 <3s（若用 FC） |
| **6** | Prometheus + Grafana + ARMS、全链路追踪、JVM 诊断大盘 | OpenTelemetry + Prometheus/Grafana；每次对话一个 trace，含 LLM span；三张大盘与 5 条 SLO；**不做 JVM/ARMS 大盘**，做 Python/Node runtime 大盘 | 大盘 JSON；告警规则；Trace 截图（含 LLM span）；一次慢请求复盘 | 首问 P95 <8s；告警 5min 内触发 |
| **7** | SEO 与 GEO、结构化内容、TDK、收录与 AI 推荐排名 | Next.js ISR/SSG 公开“题目卡点库”：`/q/{id}`、`/concept/{slug}`；TDK 模板；JSON-LD `LearningResource`/`FAQPage`；`llms.txt`；sitemap；收录监测；AI 引用监测 | 页面 URL；Rich Results 校验；Search Console；llms.txt；AI 搜索引用截图 | 100 页被收录；20 个概念页被 AI 引用/提及 |

### 8.2 AI 应用开发 1–4

| # | 能力 | 本项目落点 | 可演示证据 | 验收指标 |
|---|---|---|---|---|
| **8** | Spring AI、LangChain4j；RAG、工具调用、MCP、多 Agent | **MVP 不用 Spring AI/LangChain4j**；Python `infrastructure/llm` 做模型路由 + Pydantic/JSON Schema + 重试；Parser/Diagnostician/Coach/Verifier 四角色由状态机编排，不是自由多 Agent；MCP 工具 Phase 2 | 一次完整诊断 trace；状态转移图；`handoff` 日志；MCP Inspector（Phase 2） | 追问 JSON 合法率 ≥99%；状态机回放一致 |
| **9** | Prompt 工程；PGvector；ETL；检索；查询增强 | 系统提示 + JSON Schema；pgvector HNSW + pg_trgm + RRF；文档 ETL（PaddleOCR/Tika）；结构感知切分；查询改写；引用校验；rerank 可选 | `kb_chunk` 表；加/不加 rerank 对比；引用日志；prompt 版本记录；100 条 golden | recall@8 ≥0.85；引用可追溯 100% |
| **10** | Cursor / Claude Code / GitHub Copilot 全栈开发；MCP Server / Agent Skills | 自建 MCP Server；`diagnostic-review`、`hint-policy` 两个 Skill；CI 回归；canary 发布 | Cursor/Claude Code 里经 MCP 取解法图、校对一个节点；`skills/` 目录；canary 记录 | Skill 在 CI 跑通；MCP 工具 6/6 可用 |
| **11** | Vibe Coding、SDD、Harness、Spec-Kit/OpenSpec | spec 先行：`specs/dialogue-state.md`、`specs/diagnosis.schema.json` 为唯一真源；ADR 记录决策；golden 回归；回滚演练 | spec 目录；ADR；回归报告；回滚记录 | 需求变更 100% 有 spec；回滚 <10min |

### 8.3 覆盖度自检

| 能力域 | 覆盖 | 说明 |
|---|---|---|
| Java/Python/Go | ◐ | **Python 主栈**；Java/Go 不在 MVP；不假装三语言 |
| Hutool/Lombok | ✗ | 不适用；用 Python 标准库/Pydantic |
| Spring Cloud | ✗ | MVP 不引；Phase 2 企业适配器可选，不是主链路 |
| MySQL/分表/Druid | ✗ | 改用 PostgreSQL + pgvector；MySQL 仅作 Phase 2 备选 |
| Redis/Caffeine/锁/三防 | ◐ | Redis + cachetools + Lua 锁；无 Caffeine/Redisson |
| Docker/Nginx/Serverless | ✅ | 3 容器、SSE、FC 可选 |
| 监控/追踪/JVM | ◐ | OTel + Grafana；无 JVM/ARMS |
| SEO/GEO | ✅ | Next.js ISR、JSON-LD、llms.txt |
| Spring AI/LangChain4j/RAG/MCP/多 Agent | ◐ | Python RAG + 状态机；无 Spring AI/LangChain4j；MCP Phase 2 |
| Prompt/PGvector/ETL | ✅ | Pydantic、HNSW、切分、改写、引用 |
| Cursor/Claude Code/MCP/Skills | ✅ | 自建 MCP Server + 两个 Skill |
| SDD/Harness/Spec-Kit | ✅ | spec 先行、ADR、golden、回滚 |

**诚实标注**：

- **这是“产品最优”对“技能清单”的代价**：Java/Spring/MySQL/Caffeine 四项在 MVP 主链路没有落点。如果目标是 Java 岗作品集，见 [ADR §4 方案 C 与 §10 改选条件](../../adr/0001-language-and-code-architecture.md)；不要为了简历把主产品做成三语言。
- Go sidecar、K8s、真实分库、ARMS 全量接入属于 **Phase 2**；MVP 有配置/脚本/演练，但不假装已跑过大规模流量。
- SEO/GEO 在 MVP 只做 100 页公开卡点库，不追求全站内容矩阵。
- MCP 的写工具（`record_evidence`）需要双人复核，MVP 只对教研开放。

### 8.4 面试时怎么讲

> “这个项目不是‘我用了 FastAPI 和 RAG’，而是：
>
> 为了让学生一次只回答一个问题，我把追问做成状态机，LLM 只能在 `PROBE` 状态里选探针；
>
> 为了防止 AI 变成搜题，我把答案锁在检索、schema、出口、回归四道闸里；
>
> 为了让‘卡点’可追溯，每张诊断卡都带证据、排除项和置信度；
>
> 为了 3 个人 8 周能做出来，我只跑 3 个容器，但包边界按未来可拆的服务设计。
>
> 这些取舍，比堆中间件更能说明我会做工程。”

### 8.5 90 秒陈述

> “一个学生发来一道题和自己的答案。传统产品给答案，AI 家教讲整题，错题本只记‘错了’。
>
> 我们做的是：先拆解法图，再把他的步骤贴上去，找第一处偏离；然后用 2–6 个具体问题，让他自己发现‘我卡在参数分类，不是不会求导’；最后给一张卡点卡、3 分钟微干预、一道迁移题。
>
> 技术上，规则定骨架，LLM 只负责追问和措辞；RAG 只召回提示卡，不召回答案；多 Agent 是状态机，不是聊天室。
>
> MVP 只做高中数学函数与导数、100 道题、30 道深标；3 个人 8 周；先证明‘诊断与双教师一致率 ≥75%’，再谈规模。”

### 8.6 简历写法（标明设计/目标）

- **S**：学生遇到错题，只得到“对/错”或完整解答，不知道自己具体卡在哪个认知动作，导致重复无效刷题。
- **T**：设计一个单题诊断引导系统，输入题目 + 学生答案，输出可解释的卡点与下一步训练。
- **A**：定义 L0–L6 卡点分类与解法图；设计“规则/贝叶斯 + LLM 追问”的状态机；实现 RAG 五类卡片与答案四道闸；用 3 容器 Python 模块化单体控制 3 人 8 周范围；建立 100 条 golden 对话评测。
- **R（目标）**：诊断与双教师一致率 ≥75%；用户“说中了” ≥70%；平均 4–6 轮；答案泄漏 0；单次成本 ≤¥0.8。

**技术关键词**（按 JD 取舍）：Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、PostgreSQL/pgvector、Redis、Arq、SymPy、RAG、MCP、多 Agent、Docker、Nginx、OpenTelemetry、Prometheus、Grafana、Next.js、TypeScript、SEO/GEO。Java 21/Spring Boot/Spring Cloud/MyBatis/MySQL 作为 Phase 2 企业适配器的备选，不列在 MVP 已实现项。