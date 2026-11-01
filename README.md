# SynapseMind 突触智学

> **确定性诊断内核 · 概率性语言外壳**

学生提交题目与作答过程，系统以 2–6 轮单问追问，定位解题链上**最早失效的认知动作**，输出带证据的卡点卡：层位、支持证据、被排除的竞争假设、后验置信度、下一练。不评分、不排名、不直接给答案。

`SynapseMind` 是通用问题诊断器，不是聊天机器人，也不是学科辅导器。领域是开放标签；真正约束措辞硬度的是**验证方式**，不是学科白名单。

---

## 设计公理

| 公理 | 工程约束 |
|---|---|
| **模型提议，代码裁决** | LLM 只输出动作候选与措辞；状态转移由显式转移表推进 |
| **没有证据，不下结论** | 结论必须能回溯到对齐证据、探针证据或检索引用 |
| **验证方式决定承诺** | `FORMAL` / `EXECUTABLE` / `EMPIRICAL` / `ARGUMENTATIVE` 四档，各自有硬边界 |
| **答案与学习态物理隔离** | `AnswerStore` 与 `ProbeComposer` 分离；学习态 DTO 不含 `solution` |

---

## 一、认知内核

### 1.1 可枚举的认知动作空间

卡点不是“这题不会”，而是解题链上第一个断掉的环节。题目被拆成 7 类动作节点——`READ` / `CONCEPT` / `CONDITION` / `STRATEGY` / `TRANSFORM` / `COMPUTE` / `CHECK`——节点间以依赖边构成解法图（DAG）。

| 层位 | 断点性质 | 可观测证据 |
|---|---|---|
| `L0` | 读题 | 漏条件、误读“任意 / 存在” |
| `L1` | 概念 | 不识别“恒成立”与最值的等价 |
| `L2` | 条件转译 | 参数分类缺支、边界未检 |
| `L3` | 策略 | 选错方法，或使用未验证前提 |
| `L4` | 执行 | 变形、求导、解不等式出错 |
| `L5` | 校验 | 未检验充分性、未回代 |
| `L6` | 元认知 | 自信度与正确率背离 |

判据是**可证伪性**：卡点必须能落到一个具体反例或缺失证据上，不接受模型自评。

### 1.2 显式状态机

11 个状态，事件驱动；转移表在代码里，不在提示词里。

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
| 前 3 轮不出现最终答案 | 类型系统 + 输出结构 |
| LLM 不决定状态 | 显式转移表 + 守卫 |
| 低置信不硬判 | `posterior < 0.55` 继续问或收束 |
| 诊断需充分证据 | `posterior ≥ 0.80` 且 `margin ≥ 0.25` |
| 轮次上限 6 | 到顶收束为“可能卡点 + 缺什么证据” |

后验按 log-odds 累加、softmax 归一；似然权重是领域常量，不由模型生成。

### 1.3 认知需求向量

每个解法图节点携带 CHC 七维 `demand` 向量：`V` / `Gf` / `Gv` / `WM` / `Gs` / `LTS` / `M`，取值 0–1。当前仅作节点标注，默认不进入用户视图；不更新后验、不选择探针、不输出能力分。

---

## 二、验证分级

`subject` 是开放标签；是否追问、是否出卡点卡，由验证方式决定。

| 模式 | 承诺 | 当前实现 |
|---|---|---|
| `FORMAL` | 可形式化、可反例搜索 | SymPy 等号 / 极限检查；只返回 `fail` / `unknown`，永不返回 `pass` |
| `EXECUTABLE` | 显式提交代码可执行 | 默认关；只跑用户粘贴的 Python 与测试；`pass` 仅表示退出码 0 或提交测试通过 |
| `EMPIRICAL` | 结构化物理量可回代 | 量纲、单位、数值回代；只读结构化 `data`，不抽取自然语言公式 |
| `ARGUMENTATIVE` | 只承诺结构、取舍与风险 | 目标 / 约束 / 选项 / 风险 / 可逆实验；不给唯一答案 |

识别不出或未注册的领域进入通用入口（`intake` + 空图 + 线索匹配），不返回 422，也不假装诊断。

---

## 三、证据链与检索

诊断结论回溯到三类证据：**对齐证据**（步骤偏离）、**探针证据**（回答支持的假设）、**检索证据**（知识卡引用）。

当前 RAG 是只读旁路，默认 `SYNAPSE_RAG=off`：

- `BAAI/bge-small-zh-v1.5`（FastEmbed，本地 CPU）+ 内存余弦；
- 92 张跨领域卡，五类：`concept` / `pattern` / `method` / `error` / `source`；
- 阈值 `0.55`，最多返回 3 条；引用必须带 `source`；
- 内部检索端口支持 `kind`，`search_sources` 只取 `source` 卡；公开 `/knowledge/search` 不暴露该参数。

**目标检索管线（设计，尚未实现）：**

```text
query rewrite → hybrid recall → RRF(k=60) → rerank 50→8 → threshold → context
                    ├─ dense: pgvector HNSW
                    └─ sparse: PostgreSQL tsvector
```

当前没有 query 改写、混合召回、RRF、rerank、pgvector 或租户过滤。检索评测用 107 条固定查询：top-1 **93/95**、top-3 **95/95**、过滤 **6/6**、无关拒答 **6/6**；查询集为作者构造，不是教师标注，不能当学科准确率证据。

---

## 四、Agent 轨迹

只读、白名单、最多 3 步；首末两步固定由规则执行，中间一步默认也由规则选择。

- 轨迹契约 **v0.3**；可选 LLM 规划器默认 `off`，只能从 `search_patterns` / `search_sources` / `compare_options` 中选一个；
- 不读 `AnswerStore`、不写会话、不推进探针；`run_code` / `run_tests` 不可规划；
- 超时、坏 JSON、非法工具、RAG 关闭、无 key 一律回退规则并记录 `fallback`；
- `skipped` / `failed` 是工具状态，不是通过；轨迹不是诊断结论；
- 代码只在显式提交且 `SYNAPSE_EXEC=on` 时执行，执行结果不进诊断卡。

---

## 五、答案隔离

学习态下，最终答案在**可达性**上被切断，而不是靠提示词请求模型保密：

| 闸门 | 机制 |
|---|---|
| 存储 | `AnswerStore` 与 `ProbeComposer` 物理分离 |
| 装配 | 学习态 DTO 不包含 `solution` 字段 |
| 出口 | 禁用词 + 字符级 5-gram 重叠检测；命中即改写 |
| 显式退出 | 只有 `exit {"reveal": true}` 读取 `AnswerStore`；该次会话不出卡点卡 |

生成题没有存储答案；显式退出只返回「没有存储解法」。

---

## 六、工程契约

**当前本地演示：**

```text
Browser → Next.js → FastAPI
                       ├─ InMemory / SQLite（快照 v0.2，revision CAS，409 on stale write）
                       ├─ optional restricted Python executor（default off）
                       └─ optional RAG（FastEmbed + in-memory cosine）
```

**目标部署（设计，尚未实现）：**

```text
Nginx → web / api → worker · PostgreSQL 16 + pgvector · Redis 7 · object storage
```

- 分层强制：`api → infrastructure → application → domain`，由 import-linter 保证；
- 契约先行：JSON Schema / OpenAPI 是源，破坏性变更升版本；
- 会话默认内存，设置 `SYNAPSE_SESSION_DB` 后落本地 SQLite；SQLite 单写者，CAS 只保证不丢更新；
- 代码执行是受限本地进程，不是容器级安全沙箱；`SYNAPSE_EXEC=off` 时直接 403；
- 当前没有鉴权、多租户、OCR、实际 worker 任务、Redis、PostgreSQL 或对象存储。

---

## 七、可复算评测

| 门禁 | 当前证据 |
|---|---|
| 后端契约 | **639 passed**；`ruff` / `mypy`（Windows + Linux）/ import-linter 全过 |
| 前端契约 | **102 tests / 16 files**；typecheck、lint、build 全过 |
| 浏览器接线 | **17/17 Playwright**（mock API，含 390/1280 布局） |
| 知识卡排序 | top-1 **93/95**、top-3 **95/95**、过滤 **6/6**、拒答 **6/6** |
| 公开树 | `check_repo.py` 通过；schema 11 份 |

演示可复算：`python scripts/demo/walkthrough.py` 在进程内跑标注错解、空白、物理、语文、决策与代码六段；站内 `/cases` 收录实跑记录，`/science` 列出设计机制与引用。它们是链路记录，不是效果研究。

---

## 八、架构决策与入口

被否决的方案，比采纳的方案更能说明边界。

| 否决 | 理由 |
|---|---|
| LangGraph 式图引擎 | 显式转移表可单测、可回放、可静态审查 |
| 自由编排的多 Agent | 一次一问、6 轮上限、低置信不硬判必须是**禁止**而非**请求** |
| 提前引入外部检索引擎 | 题库量级下内存索引足够，等真实检索压力出现再评估 |
| 用 MySQL / Spring Cloud 拼企业味 | 少一层分布式事务，多一层可验证性 |

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