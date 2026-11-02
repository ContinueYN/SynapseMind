# SynapseMind 突触智学

> **确定性诊断内核 · 概率性语言外壳**

`SynapseMind` 将诊断定义为：在可验证承诺内，定位问题解决链路上最早失效的认知动作，并给出可反驳的证据约束。

用户提交问题、工作过程与目标。系统在 2–6 轮单问对话中完成结构对齐、探针与收敛，输出卡点卡：失效层位、支持证据、竞争假设、后验置信度、下一步练习或实验。诊断对象是本次问题解决过程。

覆盖数学、代码、写作、科研、决策、工作与开放学习场景；凡具备可观察过程与明确承诺的领域，均进入同一诊断链路。领域标签开放，承诺强度由验证方式决定。

---

## 设计公理

| 公理 | 工程机制 |
|---|---|
| **模型提议，代码裁决** | LLM 输出动作候选与措辞；显式转移表推进状态 |
| **证据门禁** | 结论绑定对齐证据、探针证据或检索引用 |
| **验证分级** | `FORMAL` / `EXECUTABLE` / `EMPIRICAL` / `ARGUMENTATIVE` 四档承诺 |
| **答案隔离** | `AnswerStore` 与 `ProbeComposer` 物理分离；学习态 DTO 无 `solution` |

---

## 一、认知内核

### 1.1 认知动作图

卡点定义为问题解决链上首个失效节点。问题被映射为 7 类动作节点——`READ` / `CONCEPT` / `CONDITION` / `STRATEGY` / `TRANSFORM` / `COMPUTE` / `CHECK`——依赖边构成求解图（DAG）。

| 层位 | 断点性质 | 可观测证据 |
|---|---|---|
| `L0` | 读题 | 漏条件、误读“任意 / 存在” |
| `L1` | 概念 | 未识别“恒成立”与最值的等价 |
| `L2` | 条件转译 | 参数分类缺支、边界未检 |
| `L3` | 策略 | 方法错配，或使用未验证前提 |
| `L4` | 执行 | 变形、求导、解不等式出错 |
| `L5` | 校验 | 未检验充分性、未回代 |
| `L6` | 元认知 | 自信度与正确率背离 |

判定依据落在具体反例或缺失证据；模型自评不进入判定链。

### 1.2 显式状态机

11 个状态，事件驱动；转移表在代码中，提示词只承载措辞。

```text
INGEST → PARSE ⇄ NEED_INPUT
            │
          ALIGN → PROBE ⇄ PROBE
                    ├─→ SCAFFOLD → PROBE
                    ├─→ DIAGNOSE → INTERVENE → VERIFY → CLOSED
                    └─→ STOP → CLOSED
```

| 不变量 | 实现 |
|---|---|
| 一次一问，选项 ≤ 4 | Schema 校验 |
| 前 3 轮无最终答案 | 类型系统 + 输出结构 |
| LLM 不决定状态 | 转移表 + 守卫 |
| 低置信不硬判 | `posterior < 0.55` 继续问或收束 |
| 诊断需充分证据 | `posterior ≥ 0.80` 且 `margin ≥ 0.25` |
| 轮次上限 6 | 到顶收束为“可能卡点 + 缺失证据” |

后验按 log-odds 累加、softmax 归一；似然权重为领域常量，由代码维护。

### 1.3 认知需求向量

解法图节点携带 CHC（Cattell–Horn–Carroll）七维 `demand`，构成节点需求的语义坐标系：

| 维度 | 认知功能 | 问题解决中的可观察信号 |
|---|---|---|
| `V` 言语理解 | 术语、量词与条件的语义解码 | 漏读限定语、误读“任意 / 存在” |
| `Gf` 流体推理 | 新结构下的规则归纳与迁移 | 换定义后无法重建关系 |
| `Gv` 视觉空间 | 图形与结构关系的心理表征 | 不画图，或图形关系读错 |
| `WM` 工作记忆 | 多约束并行保持与更新 | 条件一多就丢失前提 |
| `Gs` 加工速度 | 限时条件下的检索与执行效率 | 会做但检索慢、执行断档 |
| `LTS` 长时存取 | 概念、公式与模式的提取 | 公式想不起，提示后即懂 |
| `M` 元认知 | 置信度校准与策略监控 | 高置信错误，或无法定位不会之处 |

`demand` 取值 0–1。当前用于节点标注；卡面默认隐藏，`SYNAPSE_CHC_ATTRIBUTION=on` 时默认展示节点需求最高的两维，展开可看完整七维向量。后验与探针规划独立计算；对外输出限定为节点需求，能力分不进入结果。

---

## 二、验证分级

`subject` 为开放标签；是否追问、是否出卡点卡，由验证方式决定。

| 模式 | 承诺 | 当前实现 |
|---|---|---|
| `FORMAL` | 可形式化、可反例搜索 | SymPy 等号 / 极限检查；返回值域 `fail` / `unknown` |
| `EXECUTABLE` | 显式提交代码可执行 | 默认关；只跑用户粘贴的 Python 与测试；`pass` = 退出码 0 或提交测试通过 |
| `EMPIRICAL` | 结构化物理量可回代 | 量纲、单位、数值回代；输入限定结构化 `data` |
| `ARGUMENTATIVE` | 结构、取舍与风险 | 目标 / 约束 / 选项 / 风险 / 可逆实验 |

未知领域进入通用入口：`intake` + 空图 + 线索匹配，输出结构缺口与下一步补充。

---

## 三、证据与检索

诊断结论回溯到三类证据：对齐证据（步骤偏离）、探针证据（回答支持的假设）、检索证据（知识卡引用）。

RAG 默认 `SYNAPSE_RAG=off`。开启后：

- `BAAI/bge-small-zh-v1.5`（FastEmbed，本地 CPU）+ 内存余弦；
- 92 张跨领域卡，五类：`concept` / `pattern` / `method` / `error` / `source`；
- 阈值 `0.55`，最多 3 条；引用必须带 `source`；
- 内部检索端口支持 `kind`，`search_sources` 只取 `source` 卡；公开 `/knowledge/search` 保留 `q` / `subject` / `verification` / `limit`。

**目标态：**

```text
query rewrite → hybrid recall → RRF(k=60) → rerank 50→8 → threshold → context
                    ├─ dense: pgvector HNSW
                    └─ sparse: PostgreSQL tsvector
```

固定查询集 107 条：top-1 **93/95**、top-3 **95/95**、过滤 **6/6**、无关拒答 **6/6**。查询集为作者构造的概念标签集；人工标注集用于后续校准。

---

## 四、Agent 轨迹

只读、白名单、最多 3 步；首末两步由规则固定，中间一步默认规则选择。

- 轨迹契约 **v0.3**；可选 LLM 规划器默认 `off`，候选为 `search_patterns` / `search_sources` / `compare_options`；
- 轨迹只访问白名单工具；答案库、会话状态、探针预算均在上下文之外；
- `run_code` / `run_tests` 不进入规划器候选；代码执行只接受显式提交；
- 超时、坏 JSON、非法工具、RAG 关闭、无 key 回退规则并记录 `fallback`；
- 工具状态与结论状态分离：`skipped` / `failed` 保留原始语义；
- `SYNAPSE_EXEC=on` 时执行用户提交的 Python；结果注入轨迹摘要，不注入诊断卡。

---

## 五、答案隔离

学习态下，最终答案在可达性上被切断：

| 边界 | 机制 |
|---|---|
| 存储 | `AnswerStore` 与 `ProbeComposer` 物理分离 |
| 装配 | 学习态 DTO 无 `solution` 字段 |
| 出口 | 禁用词 + 字符级 5-gram 重叠检测；命中即改写 |
| 显式退出 | `exit {"reveal": true}` 读取 `AnswerStore`；该会话退出诊断链 |

生成题不含持久化答案；显式退出返回「没有存储解法」。

---

## 六、工程形态

```text
Browser → Next.js → FastAPI
                       ├─ InMemory / SQLite（快照 v0.2，revision CAS，stale write → 409）
                       ├─ optional restricted Python executor
                       └─ optional RAG
```

| 能力 | 当前 | 目标态 |
|---|---|---|
| 会话 | InMemory / SQLite，CAS | PostgreSQL + Redis |
| 检索 | 内存余弦，92 卡 | pgvector + tsvector + RRF + rerank |
| 异步 | 同步链路 | Arq worker + 离线 ETL |
| 边缘 | Next.js / FastAPI 直连 | Nginx、SSE 缓冲、限流 |
| 身份 | 单用户本地演示 | 鉴权与租户隔离 |

分层契约：`api → infrastructure → application → domain`，由 import-linter 强制。Schema / OpenAPI 为源，破坏性变更升版本。SQLite 单写者；CAS 保证不丢更新。代码执行是受限本地进程，资源与静态闸门约束；`SYNAPSE_EXEC=off` 直接 403。

---

## 七、可复算评测

| 门禁 | 证据 |
|---|---|
| 后端契约 | **639 passed**；ruff / mypy（Windows + Linux）/ import-linter 全过 |
| 前端契约 | **102 tests / 16 files**；typecheck、lint、build 全过 |
| 浏览器接线 | **17/17 Playwright**（mock API，390/1280 布局） |
| 知识卡排序 | top-1 **93/95**、top-3 **95/95**、过滤 **6/6**、拒答 **6/6** |
| 公开树 | `check_repo.py` 通过；11 份 schema |

`python scripts/demo/walkthrough.py` 在进程内复算六段链路：标注错解、空白、物理、语文、决策、代码。站内 `/cases` 收录实跑记录；`/science` 列出设计机制与引用。工程链路复算与效果验证分属两条评估线。

---

## 八、架构决策与入口

| 否决 | 理由 |
|---|---|
| LangGraph 式图引擎 | 显式转移表可单测、可回放、可静态审查 |
| 自由编排的多 Agent | 一次一问、6 轮上限、低置信不硬判由工程强制 |
| 提前引入外部检索引擎 | 当前数据量级下内存索引足够；真实检索压力出现后再评估 |
| MySQL / Spring Cloud | 少一层分布式事务，多一层可验证性 |

| 文档 | 内容 |
|---|---|
| [状态机规格](specs/dialogue-state.md) | 11 状态、转移图、硬约束 |
| [诊断卡契约](specs/diagnosis.schema.json) | 输出结构 |
| [解法图契约](specs/solution-graph.schema.json) | 节点类型、七维需求、探针 |
| [Agent 轨迹契约](specs/agent-trace.schema.json) | v0.3，只读工具轨迹 |
| [知识卡检索契约](specs/knowledge-search.schema.json) | v0.2，引用与过滤 |
| [架构决策](docs/adr/README.md) | 语言与架构、模型供应商、证据校准、首问延迟 |
| [产品定义](docs/design/chapters/00-一页纸.md) | 三种入口、诊断流程与当前范围 |
| [诊断引擎](docs/design/chapters/04-诊断引擎.md) | 解法图、步骤对齐、卡点层级、假设与探针 |

---

## License

[MIT](LICENSE) © 2026 SynapseMind contributors。