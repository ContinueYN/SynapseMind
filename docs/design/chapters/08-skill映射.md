## 8. skill.txt 逐条映射：每个能力落在哪个文件、哪次演示

> 原则：**不堆名词。** 每一项都要回答：在本项目里，哪个模块用它？演示时看什么？怎么证明不是 PPT 工程？

### 8.1 开发技术 1–7

| # | 能力 | 本项目落点 | 可演示证据 | 验收指标 |
|---|---|---|---|---|
| **1** | AI 辅助编程；Java/Python/Go；Hutool、Lombok；代码规范 | Java 21 主栈（gateway/core/content）；Python 做 OCR 后处理、离线评测、标注 ETL；Go 写 SSE 事件采集 sidecar（可选）；Hutool 做 LaTeX 清洗、JSON 树、周区间；Lombok 全量；Spotless + Checkstyle + ArchUnit | `collector/`、`eval/`、`etl/` 目录；CI 报告；AI 生成单测的 commit；Code Review 记录 | 单测覆盖率 ≥60%；Checkstyle 0 error；核心规则手写率 100% |
| **2** | 微服务、Spring Cloud、MyBatis、单体拆微服务治理 | Gateway + Nacos + OpenFeign + Sentinel；4 单元 → 7 服务边界；MyBatis-Plus 分页/逻辑删除；ArchUnit 禁止跨层依赖；拆分 ADR | `docker-compose.yml`；Feign 契约；Nacos 快照；ADR-001；灰度发布记录 | 4 单元一键起；服务边界依赖 0 违规；拆分触发条件有数据 |
| **3** | MySQL 设计、SQL 调优、分库分表、索引优化、Druid | 14 张核心表；`user_id` 16 片；联合索引/覆盖索引；3 条关键 SQL 优化；Druid StatFilter 慢 SQL 日报；月分区 | `schema.sql`；`sharding-config.yaml`；EXPLAIN 前后对比；慢 SQL Top20 | 诊断会话查询 P95 <50ms；慢 SQL <10 条/天 |
| **4** | Redis、Caffeine 多级缓存、分布式锁、雪崩/穿透/击穿、哨兵 | Caffeine 解法图；Redis 会话/提示卡/幂等；Redisson 会话锁；布隆过滤器；逻辑过期 + 随机 TTL；Redis Sentinel 哨兵集群 | Grafana 命中率；Redisson 配置；故障演练：Redis 挂 30s 仍可出诊断卡 | 缓存命中率 ≥85%；故障演练通过 |
| **5** | Docker、Nginx、Dockerfile、Serverless | 多阶段镜像；Compose 一键起；Nginx SSE 关闭缓冲 + 限流；OCR/PDF 导出跑 FC | `Dockerfile`；`nginx.conf`；FC 日志；镜像大小对比 | 镜像 <250MB；SSE 不中断；冷启动 <3s |
| **6** | Prometheus + Grafana + ARMS、全链路追踪、JVM 诊断大盘 | 每次对话一个 trace；LLM span；三张大盘；5 条 SLO；ARMS Agent；一次 OOM/GC 复盘 | 大盘 JSON；告警规则；Trace 截图（含 LLM span）；OOM 复盘 | 首问 P95 <8s；告警 5min 内触发 |
| **7** | SEO 与 GEO、结构化内容、TDK、收录与 AI 推荐排名 | 公开“题目卡点库”：`/q/{id}/breakpoints`、`/concept/{slug}`；SSR；TDK 模板；JSON-LD `LearningResource`/`FAQPage`；`llms.txt`；sitemap 分片；收录监测；AI 引用监测 | 页面 URL；Rich Results 校验；Search Console；llms.txt；AI 搜索引用截图 | 100 页被收录；20 个概念页被 AI 引用/提及 |

### 8.2 AI 应用开发 1–4

| # | 能力 | 本项目落点 | 可演示证据 | 验收指标 |
|---|---|---|---|---|
| **8** | Spring AI、LangChain4j；RAG、工具调用、MCP、多 Agent | Spring AI 编排；LangChain4j 结构化输出；Parser/Diagnostician/Coach/Verifier 四角色状态机；RAG 五类卡片；6 个 MCP 工具 | 一次完整诊断 trace；MCP Inspector 录屏；Agent 状态转移图；`handoff` 日志 | 追问 JSON 合法率 ≥99%；状态机回放一致 |
| **9** | Prompt 工程；PGvector；ETL；检索；查询增强 | 系统提示 + JSON Schema；pgvector HNSW；文档 ETL（Tika/PaddleOCR）；BM25 + dense + RRF + rerank；结构感知切分；查询改写；引用校验 | `kb_chunk` 表；加/不加 rerank 对比；引用日志；prompt 版本记录；100 条 golden | recall@8 ≥0.85；引用可追溯 100% |
| **10** | Cursor / Claude Code / GitHub Copilot 全栈开发；MCP Server / Agent Skills | 自建 MCP Server；`diagnostic-review`、`hint-policy` 两个 Skill；CI 回归；canary 发布 | Cursor/Claude Code 里经 MCP 取解法图、校对一个节点；`skills/` 目录；canary 记录 | Skill 在 CI 跑通；MCP 工具 6/6 可用 |
| **11** | Vibe Coding、SDD、Harness、Spec-Kit/OpenSpec | spec 先行：`specs/dialogue-state.md`、`specs/diagnosis.schema.json` 为唯一真源；OpenSpec 变更单；golden 回归；回滚演练 | spec 目录；变更单；回归报告；回滚记录 | 需求变更 100% 有 spec；回滚 <10min |

### 8.3 覆盖度自检

| 能力域 | 覆盖 | 说明 |
|---|---|---|
| Java/Python/Go | ✅ | Java 主栈；Python ETL/评测；Go 采集 sidecar |
| Hutool/Lombok | ✅ | LaTeX 清洗、JSON 树、周区间；Lombok 全量 |
| Spring Cloud | ✅ | Gateway/Nacos/Feign/Sentinel；4→7 边界 |
| MySQL/分表/Druid | ✅ | 14 表、16 片、3 条 SQL、慢 SQL |
| Redis/Caffeine/锁/三防 | ✅ | 多级缓存、会话锁、布隆、逻辑过期 |
| Docker/Nginx/Serverless | ✅ | 多阶段、SSE、FC |
| 监控/追踪/JVM | ✅ | 三张大盘、5 条 SLO、一次复盘 |
| SEO/GEO | ✅ | 100 页卡点库、JSON-LD、llms.txt |
| Spring AI/LangChain4j/RAG/MCP/多 Agent | ✅ | 四角色状态机 + 五类卡片 + 6 工具 |
| Prompt/PGvector/ETL | ✅ | Schema、HNSW、切分、改写、引用 |
| Cursor/Claude Code/MCP/Skills | ✅ | 自建 Server + 两个 Skill |
| SDD/Harness/Spec-Kit | ✅ | spec 先行、golden、回滚 |

**诚实标注**：

- Go sidecar、K8s、16 片真实分库、ARMS 全量接入属于 **Phase 2**；MVP 有配置/脚本/演练，但不假装已跑过大规模流量。
- SEO/GEO 在 MVP 只做 100 页公开卡点库，不追求全站内容矩阵。
- MCP 的写工具（`record_evidence`）需要双人复核，MVP 只对教研开放。

### 8.4 面试时怎么讲

> “这个项目不是‘我用了 Spring Cloud 和 RAG’，而是：
>
> 为了让学生一次只回答一个问题，我把追问做成状态机，LLM 只能在 `PROBE` 状态里选探针；
>
> 为了防止 AI 变成搜题，我把答案锁在检索、schema、出口、回归四道闸里；
>
> 为了让‘卡点’可追溯，每张诊断卡都带证据、排除项和置信度；
>
> 为了 3 个人 8 周能做出来，我只跑 4 个部署单元，但边界按 7 个服务设计。
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
- **A**：定义 L0–L6 卡点分类与解法图；设计“规则/贝叶斯 + LLM 追问”的状态机；实现 RAG 五类卡片与答案四道闸；用 4 单元/7 服务边界控制 3 人 8 周范围；建立 100 条 golden 对话评测。
- **R（目标）**：诊断与双教师一致率 ≥75%；用户“说中了” ≥70%；平均 4–6 轮；答案泄漏 0；单次成本 ≤¥0.8。

**技术关键词**（按 JD 取舍）：Java 21、Spring Boot 3、Spring Cloud、Nacos、Gateway、Sentinel、OpenFeign、MyBatis-Plus、MySQL、Redis、Caffeine、Redisson、PostgreSQL/pgvector、Spring AI、LangChain4j、RAG、MCP、多 Agent、Docker、Nginx、Prometheus、Grafana、Next.js、SEO/GEO。