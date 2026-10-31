# AGENTS.md — 开发交接

> 本文件面向**接手开发的人或新会话**。对外文档是 [README.md](README.md)（只讲架构，不标进度）；进度、未决项、环境陷阱都记在这里。

---

## 一、当前状态（2026-10-31）

> 下面各段里的 `pytest` 数字是**写成当时的快照**（307 → 308 → 327 → 334 → 339 → 340，随每轮新增测试递增），
> 不是互相矛盾的三个值；当前值以实跑为准。判断一条能力有没有落地，看它有没有自己的
> 报告和测试，不要看这里的数字。

**现在在哪**（逐段验收记录见 [docs/status/m2.5-log.md](docs/status/m2.5-log.md)）：

| 阶段 | 状态 | 一句话 |
|---|---|---|
| M1 walking skeleton | 落地 | 交题 → 对齐 → 2 轮探针 → L2 卡点卡；规则版，内存仓储 |
| M2 窄口径 | 落地 | LLM 追问 + 校验/重试/降级 + 10 条 golden；默认 `SYNAPSE_LLM_MODE=off` |
| M2.5 S4–S8 | 落地 | 生成图进主链路；物理 PARTIAL、语文 NONE；首问 p50 4.2s / p95 4.6s（预算 8s） |
| S5 ⑥ 等式链校验 | **落地（默认关）** | `start()` 查首问过程并进卡面；`POST /sessions/{id}/steps` 单步验证；数学诊断页有折叠式「交步骤」入口；契约 v0.2 的 `fail` 带结构化 `findings`（公式/反例分行），`SYNAPSE_EQUALITY_CHECK` 默认 `off` |
| 题集 / 复盘 / 探针 | 落地 | 100 题带 `expected_answer`、4 条真实学生原话、构造真值的缺口探针 |
| 包装层（门面、论文引用区） | **起步** | 新增 `/about`：突触类比、CHC 标签空间、验证边界、3 条 DOI 引用；首页页脚入口 |

下一步与优先级见第三节。

---

**未实现**（不要以为已经有）：

| 能力 | 状态 |
|---|---|
| LLM 追问 | **有**：`infrastructure/llm/`（DeepSeek，默认 `off`）；T5「LLM 辅助对齐」未做且默认不做 |
| `shadow` 真实对照 | **已跑（2026-10-29，真实 key）**：10/10 不变，24/24 JSON 合法，p95 1.10s，0 重试 0 降级；细节见 `eval/reports/m2-exit-v0.1-shadow.md` 与 ADR-0002 §5.1 |
| 学科插件 / 解法图生成 | `SubjectPlugin` + `MathPlugin` 包装种子图（S1–S3）；识别为严格匹配（不同题交给建图器，识别不了且建不出图才 422）。**S4/S5 有生成器且已接进主链路**：`LLMGraphGenerator`（prompt → JSON → 机械修复 → 结构规则 → schema → 验证 → 一次重试）生成图、逐选项证据权重与可证伪 `claim`；`ProblemResolver` 未命中标注库就现场建图并登记为 `annotated=False`，通用对齐与通用卡点卡按图工作。**S6 已接入物理**（`PhysicsPlugin`，PARTIAL，`graph-v9-physics`）；物理无标注题集，需显式声明 `subject="physics"`，`verify()` 对结构化 `StudentStep.data` 做量纲/数值回代、纯文本仍 `unknown`。**S7 已接入语文**（`ChinesePlugin`，NONE，`graph-v6-chinese`）：不追问、不出卡，只出结构提示（`specs/structure-hint.schema.json`）；同样必须显式声明 `subject="chinese"`。**S8 已把对齐策略收进插件端口**（`SubjectPlugin.aligner_for`）：数学/物理保持两态，语文用分句级 `ClauseCueAligner`；`CompositeAligner` 改按 `problem.annotated` 分发，`api/deps.py` 不再组装 |
| RAG / 向量检索 | 无 |
| PostgreSQL / Redis / Alembic | 无；`InMemorySessionRepository` |
| OCR | 无；`image_url` 仅在 DTO 预留 |
| 鉴权 / 多租户 | 无 |
| worker 实际任务 | 无；`apps/worker` 只有说明 |
| 24h 迁移验证 / 教师复核 | 无。教师复核的**工具**已就位（`scripts/eval/s5_review.py` + `student-answers-v0.1.jsonl` + 填表页 `tools/review-form.html`），也自己从公开问答页收了 4 条学生原话（`public-web`），但**还没有老师填过 `人工判断` 列**，也没有同一批题的真实学生作答 |

**已知硬边界**：入口的默认路径仍是「只有一道标注题」——`SYNAPSE_LLM_MODE=off`（默认）或缺少 key 时，非种子题依旧返回 **422**，这是显式设计，不是 bug。接上 key 后入口会现场建图（`ProblemResolver` + `MathPlugin.build_graph`），建图失败同样 422 并给出原因。**生成题的能力边界**：① 存在性对齐（数学/物理 `TypeCueAligner`，语文 `ClauseCueAligner`）只判断「这一步有没有被写到 / 是否只写到一部分」，写错了发现不了；② 生成题没有存储答案，泄漏守卫退化为通用短语检查；③ 卡点卡的 `HYPOTHESES[*].node_id` 仍是种子专用，生成题的卡面从「探针 → 节点」反推节点。证据表 `EVIDENCE` 覆盖种子题的四个探针，实测只有 `H_L2` 能越过 `0.80 + 0.25`；`L1`/`L4` 案例按「低置信不硬判」收束（见 `eval/reports/m2-exit-v0.1.md`）。

---

## 二、必读顺序

0. [docs/README.md](docs/README.md) — 文档总索引：三层文档（设想／主体／实现）、每份的职责与时效。不确定该看哪份时先看它。
1. [`specs/dialogue-state.md`](specs/dialogue-state.md) — 10 状态、转移、8 条硬约束。**任何改动先看它。**
2. [`README.md`](README.md) — 架构总览（九节，含决策记录）。
3. [`docs/design/chapters/12-M2交付计划.md`](docs/design/chapters/12-M2交付计划.md) — 下一步做什么、怎么验收。
4. [`docs/design/chapters/13-学科插件与可扩展架构.md`](docs/design/chapters/13-学科插件与可扩展架构.md) — 全学科怎么走。
5. [`docs/adr/0001-language-and-code-architecture.md`](docs/adr/0001-language-and-code-architecture.md) — 技术选型与改选条件。
6. [`docs/adr/0002-llm-provider-and-golden-scale.md`](docs/adr/0002-llm-provider-and-golden-scale.md) — 模型供应商与 golden 规模（已定：DeepSeek `deepseek-chat` / 10 条）。
7. [`docs/adr/0003-generated-graph-evidence-calibration.md`](docs/adr/0003-generated-graph-evidence-calibration.md) — 生成图证据权重的 0.90 校准与备选方案。
8. [`docs/adr/0004-first-question-latency-budget.md`](docs/adr/0004-first-question-latency-budget.md) — 首问 8s 预算：改哪一段、为什么、代价，以及被拒的方案（单独预算/异步/对冲/换模型）。

**本地详尽版**（未入库，仅本机存在）：

- `docs/design/plan/M2-开发说明.md` — 含未决项与取舍记录
- `docs/design/plan/M2.5-学科插件与可扩展架构.md` — 含 `SubjectPlugin` 草案与 S1–S7；S8 记录见第 13 章
- `.tmp/m2-digest-main.md`、`.tmp/m2-digest-small.md` — 历史会话的提取与逐行引用（可追溯需求来源）

---

## 三、下一步（按优先级）

1. **M2 收尾**（T1–T4 + T6–T7 已完成，真实 shadow 已跑）：
   - 实测口径：JSON 合法 24/24、p95 1.10s、0 降级（ADR-0002 §5.1）；
   - **首问整体门禁：已通过（2026-10-30 晚，ADR-0004）**。`scripts/eval/m2_first_question.py` 对 20 道未见题只测 `SessionService.start()`（含现场建图/对齐/探针规划），预算 8s。治理前两轮 FAIL（p50 6405/6391ms、p95 9304/11856ms，后一轮 2 题 `schema_invalid` 重试）；治理后按 `graph-v9` 连跑三轮：run5 **p50 4208ms / p95 4690ms**、run6 p50 4417ms / p95 8632ms（**FAIL**：2 题重试各 ≈4.4s）、run7 **p50 4252ms / p95 4619ms**。改的是「输出长度 + 装饰性调用 + 预热 + 预算内重试」，不是调门槛（细节与代价见本文件状态段和 ADR-0004）。**残留风险**：claim 修复样本 ≈5.3–6.3s（建图 4.3–4.5s + 区间重写 0.8–1.8s），20 题里 p95 容得下 2 个；schema 重试样本仍 ≈7.6s（最小图重试）。供应商 TTFT 若长期 >2s，p50 会跟着涨，届时再按 ADR-0004 的选项 A/D 重新评估。
   - **仍未做**：**真实学生作答**（`s5_review.py` 与 `student-answers-v0.1.jsonl` 已就位，但 `source=student` 是 0 条；只有 3 条 synthetic 走通了管线，出卡 3/3、期望卡点命中 1/3，三张卡都是 L1）。浏览器端到端已量过一轮（loopback + 4G 限速，见上段与 `eval/reports/m2-first-question-browser.md`），但还没有 RUM 与多设备样本。
   - 请求 `deepseek-chat` 实际服务 id 是 `deepseek-flash`，冻结基线看审计里的 `model` 字段。
2. **M2.5**：第 13 章 S1–S8。S1/S2/S3 已完成（枚举扩到 `math`/`physics` + 三学段；`SubjectPlugin` + `MathPlugin`；识别从关键字换成「归一化包含」严格匹配，不同题返回 422）。
   - **S4 已完成（2026-10-29）**：`application/graph.py`（端口）+ `domain/problem/graph_structure.py`（结构规则/机械修复）+ `infrastructure/llm/graph.py`（生成 + spec 校验 + 一次重试 + 进程内缓存 + 指纹审计）。20 道未见题结构 20/20、人工抽查 19/20（95%）；0 重试 0 修复；p50 3.65s / p95 4.54s。报告：`eval/reports/m2.5-s4-graph-build.md`、`eval/reports/m2.5-s4-graph-review.md`。
   - **S4 暴露的两件事**：① 抽查唯一失败是 P_DERIV_003 漏 `a=0` 边界——**prompt 守不住数学边界**，S5 的验证器/反例必须补；② `temperature=0` 仍不可重复（同题两次 7/8 节点、指纹不同），缓存只保进程内，回归比对记录指纹。
   - **S5 第一阶段已完成（2026-10-29）**：证据表改为会话级数据——`HypothesisSet.from_alignment(..., evidence=...)`，`SessionFactory` 调 `SubjectPlugin.evidence_model()`；`EVIDENCE` 只作无插件时的默认。补齐 `p_union` 四个选项的权重（原来答了也不更新后验），契约测试保证种子题每个探针每个选项都有权重。10 条 golden 仍 10/10、平均 2.40 轮。
   - **S5 第二阶段已完成（2026-10-29）**：生成图新增 `Probe.evidence`（`选项 → 假设 → log-odds`），生成 prompt 升到 `graph-v2`。结构规则强制每个选项都有权重、权重键只能在该探针 `targets` 内、每个 target 至少被一个选项使用、权重有正有负（能区分假设）、钳制在 −1~1；`MathPlugin.evidence_model()` 优先读图内权重，只有已标注种子图回退 `EVIDENCE`，未知图返回空表。真实 20 题：结构 18/20（`P_DERIV_007`/`P_GEOM_001` 两次都无探针），68/68 探针、204/204 选项有权重且 68/68 有正负对比；4 次重试，2 次重试后通过、2 次因 `no_probes` 失败；p50 3.91s / p95 5.04s。`P_DERIV_003` 仍漏 `a=0`——**证据权重只保证「答了会更新后验」，不保证图的数学结论正确**。
   - **S5 第三阶段已完成（2026-10-29）：SymPy 验证器 + 反例。** 形式化字段按建议放在**图顶层** `claim`（`specs/solution-graph.schema.json` 的 `$defs/claim`）：`kind`（v1 只有 `parameter_range`）、`parameter`/`variable`（单字母小写）、`variable_domain`、`constraint{expression,relation}`、`answer[{lower,upper,lower_inclusive,upper_inclusive}]`，语义是 `∀x∈D: f(x,a) rel 0 ⇔ a∈answer`。`application/verification.py` 定义端口与 `pass|fail|unknown`，`infrastructure/verification/sympy_verifier.py` 做**反例搜索**：表达式走字符白名单 + `__builtins__` 置空的 SymPy 命名空间 + 自由符号白名单；x 取线性网格 + 12 个数量级 + 边界加密，参数在区间内外各取样（含端点本身），对最紧处做黄金分割细化；两个方向都查（区间内不满足 → 偏宽；区间外满足 → 偏窄）。`fail` 带 `a=…, x=…, 表达式=…` 的具体反例，回灌给模型重试一次；仍失败则**丢弃 claim、保留图**（`claim_dropped_refuted`），这是刻意的：`P_GEO_001` 这种“图对、claim 形式化错”的题不该整题报废，但答案也不能再被当作已核对。claim 的 kind/relation/符号冲突直接丢弃（`claim_dropped_unsupported`），不浪费重试。真实 20 题见上方状态；报告：`eval/reports/m2.5-s5-verification.md`（含变形自检与正向对照：同一题 `[0,E]` → pass、`(-∞,E]` → fail 带反例）。
   - **S5 第四阶段已完成（2026-10-30）：生成图接进 ALIGN/PROBE。** ① `TypeCueAligner` 按节点类型做**存在性**检查（线索词 / 是否写过式子 / 同一字母两侧分类 / 3-gram 兜底），`CompositeAligner` 按 `annotated_ids` 分发（S8 起改为按 `problem.annotated`），`RuleBasedAligner` 一行未改；② 缺节点的**类型**决定先验（`NODE_TYPE_LAYER` + `FOCUS_PRIORS` + `from_alignment(focus=...)`），种子题没有 `focus` 时仍走原来的节点档案，10 条 golden 逐字节不变；③ `build_diagnosis_card` 分两支：标注题沿用旧文案，生成题引用「推动后验的那次作答」或只报「过程里没有出现这一步」，id 用 `node:{id}`/`verify:{problem_id}`；④ `ProblemResolver`：标注库严格命中 → 否则现场建图 → 存为 `annotated=False`（`P_GEN_<指纹>`，同题不重复生成），没有建图器或建图失败仍 422。实测：`scripts/eval/s5_session.py` 20 题建会话 20/20、出卡 7/20、卡点节点 7/7 属于该图，报告 `eval/reports/m2.5-s5-session.md`。出卡率低不是接线问题：生成图每题只有 3–7 个探针、权重 max|w|=0.60（|w|≥0.8 的 0 条），targets 又分散在不同假设对上，同一个 `0.80 + 0.25` 门槛很难在 6 轮里达到——**这属于 S5 ③ 的探针/权重校准**，不要靠调低门槛「修」。
   - **S5 ② 的边界（写进第 13 章）**：存在性对齐发现不了「写错」；生成题没有存储答案 → 泄漏守卫退化；首问预算现在含一次建图（p50 4–5s）。
   - **S5 ③ 已完成（2026-10-30）**：prompt `graph-v6` 要求权重用满 ±1；图构建器在模型写得偏弱时按全图统一系数放大到 0.90（只放大、不改符号与相对强弱，记 `evidence_calibrated`；ADR-0003）。20 题建会话 20/20、**出卡 20/20（上一轮 7/20）**、卡点节点 20/20 在图内；125 探针 / 750 权重，max|w|=0.90，|w|≥0.8 的 350 条；p50 6.4s / p95 9.3s（首问治理后按 `graph-v9` 重跑：98 探针、建图 p50 4.3s、出卡仍 20/20，见 ADR-0004）。④ **已由 claim-only repair 覆盖（2026-10-30 晚）**：首轮生成仍偶发写错（`P_DERIV_003` 历史四轮写 `(-∞,e]`；本轮 20 题首轮就写 `[0,e]`），但被反例推翻后只重写区间，受控探针五例（负参数段、整段漏、两端开闭）**14/15 修对**（`eval/reports/m2.5-s5-claim-repair.md`）。没有把具体函数写进 prompt；修复请求里的表达式来自模型自己的 claim。批量统计仍以 `s5_verify.py` 为准。
   - **S6 已完成（2026-10-30）：物理接入，PARTIAL 档。** `PhysicsPlugin`（`subject="physics"`、`level=PARTIAL`）通过同一个 `LLMGraphGenerator` 生成图，prompt 为 `graph-v6-physics`；物理图不写 claim（v1 SymPy 验证器只覆盖数学参数范围），写了就丢弃并记 `claim_dropped_unsupported`；探针 targets 仍复用 H_L1/H_L2/H_L4，但 `hypothesis_labels` 换成物理词表，评分/先验/门槛完全不动。`api/deps.py` 同时注册数学与物理插件，`domain/dialogue/` 一行未改。真实 6 题：建会话 6/6、出卡 6/6、卡点节点 6/6 在图内、卡面 6/6 物理词表；27 探针 / 170 权重，max|w|=0.90，|w|≥0.8 的 95 条；p50 5.77s / p95 6.66s。报告：`eval/reports/m2.5-s6-physics.md`。**S6 后续已验证器**：`PhysicsPlugin.verify()` 读取 `StudentStep.data`，量纲错误/数值矛盾返回 `fail`，缺数据/未知单位/未知符号/畸形输入返回 `unknown`；纯文本和数学路径仍 `unknown`。`domain/dialogue/` 与数学 SymPy 验证器未改。物理暂无标注题集/真实学生作答，6/6 是接线结果不是诊断准确率。
   - **S7 已完成（2026-10-30）：NONE 档承诺降级，语文接入。** `ChinesePlugin`（`subject="chinese"`、`level=NONE`）与数学/物理共用同一个 `SessionService`、状态机和 `CompositeAligner`；`application/commitment.py` 的能力表是唯一开关，NONE 在 ALIGN 之后直接收束到 `STOP → CLOSED`，不调用探针规划器、不生成卡点卡。输出换成另一张契约（`specs/structure-hint.schema.json` / `domain/diagnosis/hint.py`）：`one_line` + `steps[{node_id,text,status}]` + `focus_node_id` + `next_step` + 固定 disclaimer，没有 layer/confidence/next_action/verify；提示由对齐结果派生，每次 `get()` 重建。语文 prompt `graph-v6-chinese` 只要求步骤，探针/claim 若被写出会被丢弃（`probes_dropped_unsupported` / `claim_dropped_unsupported`），`review(require_probes=False)` 允许无探针图。真实 6 题 × 2 段过程：建会话 12/12、结构提示 12/12、schema 合规 12/12、出卡 0/12、探针 0/12；同题复用同一张图 6/6，覆盖数 full ≥ partial 6/6、focus 后移 4/6；p50 2.3s / p95 3.2s。报告：`eval/reports/m2.5-s7-none-tier.md`。**已知低估**：整句 3-gram 覆盖率对多分句语文节点偏严，覆盖计数偏低（partial 1.0/8、full 1.7/8）；**S7 之后**该补的是分句级匹配或对齐器端口（S8 候选），不是调低门槛。物理 PARTIAL 验证器的量纲/数值回代已落地（需要 `StudentStep.data`）；矢量、微积分、不确定度与自然语言抽取仍未做。
   - **S8 已完成（2026-10-30）：对齐策略插件化 + 分句级匹配，契约 v0.2。** `SubjectPlugin.aligner_for(problem) -> StepAligner`；`SessionFactory` 先问插件，`CompositeAligner` 改按 `problem.annotated` 分发，`api/deps.py` 只留无插件回退。数学标注→`RuleBasedAligner`、生成→`TypeCueAligner`，物理 `TypeCueAligner`，语文 `ClauseCueAligner`（小句 ≥4 字、公共段 ≥4 字、覆盖 ≥75% 为 `covered` / ≥15% 为 `partial`）。`AlignmentResult` 加 `partial_node_ids`；`structure-hint.schema.json` 升 v0.2，`HintOut` 加 `partial`，前端计数「有写到的步数（含部分）」。6 题 × 3 段过程：建会话 18/18、schema 18/18、服务=直接调用 18/18、0 卡/0 探针、CLOSED 18/18；同一张图旧 full covered 均值 1.7 → 新 covered 1.7 + partial 2.3（加权 2.8），full≥partial 6/6、新≥旧 6/6、blank 全 missing 6/6。报告：`eval/reports/m2.5-s8-clause-alignment.md`。**边界**：字面重合不是语义匹配；`partial` 不是写错；数学/物理没有 opt-in；`domain/dialogue/` 未改。**S8 之后**仍没有语文标注题集/真实学生作答，18/18 是接线验收，不是诊断准确率。
3. **待收口的既有问题**：`docs/design/plan/` 未入库；M2.5 题集已扩到 100 道数学（带 `expected_answer`）+ 6 物理 + 6 语文，但 `eval/golden/` 仍是 10 条，`eval/golden/README` 的 100 条配额未达（golden 是模拟对话，不是题集）。前端有组件测试与一次手工浏览器 smoke（单步检查 fail/unknown + 390px），但还没有自动化浏览器端到端。
4. **等式链校验已接出孤岛（2026-10-30 深夜完成方案 A + B，2026-10-31 补前端入口与 v0.2 契约；默认关）。**
   - **已落地**：`SessionService.start()` 在 `factory.create()`（对齐）之前对 `command.work` 跑 `check_work`；finding 存进 `DialogueSession.work_findings`，`card_builder` 在标注/生成两张卡上把第一条 finding 写成「一句话结论」、公式与数值放进「依据」。端口是 `application/work_check.EqualityChecker`，实现是 `infrastructure/verification/equalities.SympyEqualityChecker`（缺 SymPy 时返回空，不抛异常）；开关 `SYNAPSE_EQUALITY_CHECK`（`infrastructure/features.py`，默认 `off`），也可用 `build_container(..., features=FeatureFlags(equality_check=True))` 显式打开。
   - **验收（实跑）**：`public-attempts-v0.1.jsonl` 的 `P_PUB_002` 卡面出现「你写的「(sin(x)/(x+sin(x)/cos(x))) = (sin(x)/x+cos(x))」这一步等号不成立：x→0 时左边极限 0.5、右边 2。」；同批 4 条只命中这 1 条（`P_PUB_001/003/004` 无误报），报告 `eval/reports/m2.5-s5-student-review-public-equality.md`。开关关闭时 10 条 golden 卡面逐字节不变（`.tmp/golden-cards-before.json` 对照）、`m2_exit.py` **10/10**；`pytest` **334 全绿**；`ruff format --check`、`ruff check`、`mypy src`、import-linter 全过。
   - **方案 B 已完成（2026-10-30 深夜；2026-10-31 升 v0.2）**：新增 `POST /api/v1/sessions/{session_id}/steps`（请求 `StepRequest`：`text` 必填，`node_id`/`data` 可选；响应 `StepVerdictOut`：`version`/`status`/`detail`/`findings`）并登记 `specs/step-verification.schema.json`。`SessionService.verify_step()` 只查会话所属学科的插件，**不推进状态、不写仓储、不出卡**；未知会话 404。`MathPlugin.verify()` 不再占位：开关打开时调 `EqualityChecker.findings(step.text)`，有可证伪的等号就返回 `fail` 并带学生原句与反例（多条最多列 3 条、detail 截到 900 字），没找到、读不懂或开关关闭一律 `unknown`——**它从不返回 `pass`**，因为「没找到反例」不等于「这步正确」。物理仍走结构化 `data`（量纲/数值回代），纯文本 `unknown`。**前端入口已完成（2026-10-31）**：`SessionOut` 新增 `subject`，数学诊断页多一个折叠式「有一步拿不准？」的 `StepCheck`（`apps/web/components/StepCheck.tsx`），贴一行式子即调 `verifyStep()`；结果按 `fail`/`unknown` 分色显示，`fail` 直接用 v0.2 的 `findings` 分行显示「公式 / 反例」（不再解析 `detail` 前缀），`unknown` 明确写「没判出来不等于这一步正确」。语文、物理不显示该入口（语文没有可判真值，物理需要结构化载荷，摆出来是空承诺）。验收：`pytest` **340 全绿**（在 339 条基础上新增 schema 校验；反例用例同时断言 `findings` 与状态未变）；`ruff check`、`ruff format --check`、`mypy src`、import-linter、`check_repo.py` 全过；开关关闭时 10 条 golden 卡面仍逐字节不变，`m2_exit.py` **10/10**；前端 `npm run typecheck`/`lint`/`test`（4 文件 16 测试）/`build` 通过，并用浏览器 smoke 跑通 `fail` 与 `unknown` 两条路径、390px 无横向溢出。
   - **仍未做**：数学仍只查等号（赋值、定义、读不懂的式子跳过），物理前端没有结构化 `data` 表单；单步验证没有审计/限流，也没有把结果回写会话历史。措辞仍只写「这个等号不成立」＋具体反例。
5. **包装层已起步（2026-10-31）：`/about` 把类比、标签与边界写清楚。**
   - **页面**：`apps/web/app/about/page.tsx`，从页脚「为什么这样设计」进入，不放进交题主路径。四段：① 突触是类比，只约束模型形状（成功提取增强、久不用衰减），不宣称神经测量；② CHC 只做标签空间，`demand` 目前仍是图节点字段，**未进入结论、也未用来选探针**；③ 验证边界五项（存在性对齐、等号反例、图结构、归因、延迟正确率），前两项有可复现验收、第三四项只有小样本或构造真值、第五项没有数据；④ 三条 DOI 引用。
   - **引用**：Carroll（1993，CHC 能力分类）、Sweller（1988，认知负荷）、Hattie & Timperley（2007，反馈）。每条的 DOI 都用 Crossref 核过；页面写明「设计概念的来源，不是效果背书」。
   - **顺手修正**：`README.md` 第 2 节原来写「七维决定下一个问题问什么」，但代码里 `demand` 只被结构校验与审计序列化读取；已改成「尚未用它更新后验或选择探针」。这条比页面本身重要——文档不能比代码多走一步。
   - **验收**：`typecheck` / `lint` / `test`（4 文件 16 测试，新增 `/about` 3 条）/ `build` 全过；浏览器在 1440 与 390 宽下均无横向溢出，390px 时两列卡片折成一列、页脚入口可点。**边界**：没有对照实验与延迟正确率；`/about` 是设计说明，不是效果报告。

---

## 四、命令

```powershell
# 一键启本地（首次会建 venv、装依赖）
python scripts/dev/run.py
python scripts/dev/run.py --check        # 只查环境

# 后端
cd apps/api
pytest
ruff check src tests
ruff format --check src tests          # CI 会跑，别只跑 check
.\.venv\Scripts\python.exe -m mypy src # 本机 mypy.exe 会静默 exit 1，见环境陷阱
.\.venv\Scripts\lint-imports.exe         # 分层契约，CI 强制

# 前端
cd apps/web
npm run typecheck
npm run lint
npm test                              # Vitest + jsdom：组件回归
npm run build

# 契约重新生成（DTO → OpenAPI → TS 类型）
python scripts/contracts/generate.py

# M2 退出判定（10 条 golden 回放，产出 eval/reports/m2-exit-v0.1.md）
cd apps/api
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py
# 真实模型双跑（key 放仓库根 .env，或导出 DEEPSEEK_API_KEY；结果不变，只多一份差异报告）
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py --live-shadow

# M2 首问整体 P95 门禁（20 道未见题，含现场建图；预算 8s，失败退出码 1）
# 报告里有「阶段耗时」一节：建图调用数/重试数、p50/p95、输出 token 中位数、改写次数
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_first_question.py
# 尾延迟旋钮：SYNAPSE_GRAPH_RETRY_BUDGET_S（默认 7.5s，claim 重试的预算线）

# M2.5 S4 建图（20 道未见题；需真实 key；产出 eval/reports/m2.5-s4-graph-build.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py

# M2.5 S5 建图 + claim 反例验证（同 20 题；产出 eval/reports/m2.5-s5-verification.md 与 s5-graphs/）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_verify.py

# M2.5 S5 claim 只重写区间的受控探针（默认五例：负参数段 (-∞,e]、整段漏 [1,e]、
# 两端开闭 (0,e]/[0,e)、负参数段收窄 (-1,e]；--case NAME 单跑、--repeats N 控次数；
# 需真实 key；产出 eval/reports/m2.5-s5-claim-repair.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_claim_repair.py

# M2.5 S5 ④ 真实学生作答复盘（读 eval/problems/student-answers-v0.1.jsonl；
# 出卡/卡点层/期望卡点是否命中，最后一列留给老师填；需真实 key；
# 产出 eval/reports/m2.5-s5-student-review.md）
$env:SYNAPSE_LLM_MODE='on'
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_review.py --limit 5

# M2.5 S5 ②/③ 请求链路（20 题现场建图 → 探针 → 卡点卡；产出 eval/reports/m2.5-s5-session.md）
# --policy aligned（默认）模拟“作答与对齐结论一致”，--policy first 一律选第一项作对照
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_session.py

# M2.5 S5 ③ 缺口定位探针（构造真值：让模型扮演学生故意跳过一步；需真实 key；
# --limit N 控题数；产出 eval/reports/m2.5-s5-gap-probe.md）
$env:SYNAPSE_LLM_MODE='on'
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_gap_probe.py --limit 20

# M2.5 S6 物理接入（6 题；需真实 key；产出 eval/reports/m2.5-s6-physics.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s6_physics.py

# M2.5 S6 物理 PARTIAL 验证器自检（无需 key；固定正反例，退出码 0 表示全过）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s6_verifier.py

# M2.5 S7 NONE 档结构提示（6 道语文题 × 2 段过程；需真实 key；产出 eval/reports/m2.5-s7-none-tier.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s7_none_tier.py

# M2.5 S8 分句级对齐（6 道语文题 × 3 段过程 partial/full/blank；需真实 key；产出 eval/reports/m2.5-s8-clause-alignment.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s8_alignment.py

# 设计书重建（源：docs/design/chapters/*.md）
python tools/merge_markdown.py
.\.tmp\toolvenv\Scripts\python.exe tools/generate_docx.py
& tools\update_toc_and_export.ps1        # 需 Word，输出 DOCX 目录 + PDF
```

---

## 五、环境陷阱（踩过的，别再踩）

| 陷阱 | 实际情况 |
|---|---|
| 没有 `pwsh` | 当前 shell 就是 Windows PowerShell 5.1，脚本用 `& tools\xxx.ps1` 直接调 |
| `python-docx` 未安装 | 文档构建需 `tools/requirements.txt`；已建 `.tmp/toolvenv`，用它跑 `tools/*.py` |
| `docs/design/` 在 `.gitignore`，**但 `chapters/*.md` 已被跟踪** | 改章节文件会进公开仓库；`docs/design/plan/` 与 `release/` 才真被忽略 |
| `release/` 产物需手动重建 | 改了章节不重建，DOCX/PDF 就是旧的（曾差一天） |
| Git 远端走 HTTPS + GCM | SSH 22/443 均不通；`git push` 无需交互 |
| `seed.py` 只有一道题 | 换题 422 是刻意边界，扩题属 M2.5 |
| `lint-imports.exe` 静默 exit 1 | 本机 exe 即使 `PYTHONPATH` 正确也可能静默失败（无输出）。先 `$env:PYTHONPATH=(Resolve-Path src).Path`，再 `.\.venv\Scripts\python.exe -c "from importlinter.cli import lint_imports_command; lint_imports_command()"`；通过时打印「Contracts: 1 kept」。CI 用 editable 安装，不受影响 |
| `.venv\Scripts\mypy.exe` 静默 exit 1 | 本机 `mypy.exe --version` 都返回 1 且无输出，但 `.\.venv\Scripts\python.exe -m mypy src` 正常（70 files, no issues）。用模块方式跑，别把静默失败当成类型错误；CI 的 `mypy src` 不受影响 |
| 8000 是默认端口，但可能被别的服务占用 | 脚本与前端默认都是 8000（`scripts/dev/run.py --api-port 8000`、`client.ts` 回退 `http://localhost:8000`）。先查 `Get-NetTCPConnection -State Listen -LocalPort 8000`；如果确实被 `cs-web-ai-backend-1` 之类的容器占用、uvicorn 报 `winerror 10013`，才临时改 `--api-port 8100`，并在 `apps/web/.env.local` 写 `NEXT_PUBLIC_API_BASE=http://localhost:8100`（该文件被 `*.local` 忽略）；改完要重启 `npm run dev`——`NEXT_PUBLIC_*` 在 dev 启动时就内联了，热更新换不掉。**端口空闲时不要照抄 8100。** |
| 新增 Python 依赖要重装 venv | `pyproject.toml` 加了 `jsonschema`（运行时）与 `types-jsonschema`（dev）；旧 venv 没有时会 ImportError。`pip install -e ".[dev]"` 一次补齐 |
| 根目录 `eval/` 在 `.gitignore` | 只忽略**根目录**的私有评测材料；`scripts/eval/` 是工具、必须入库（早先写成不带锚点的 `eval/`，把 `m2_exit.py` 一起吞了）。golden 数据仍需 `git add -f eval/golden/golden-v0.1.jsonl`，`eval/reports/` 是产物不入库 |
| CI 跑 `ruff format --check` | 只跑 `ruff check` 会在 CI 挂（format 与 check 是两套规则）；写完先 `ruff format src tests`。文件末尾缺换行也算未格式化 |
| 生成图 prompt 已升到 `graph-v9` | v2 起每个探针的每个选项都必须有 `evidence` 权重；v3 起可选 `claim`（参数区间）并把验证接进建图；v4 起要求每个探针至少一个权重达到 ±0.8~1.0、同一假设的选项差 ≥1.0、整图覆盖三个假设；v6 还要求检查 parameter=0、parameter<0、variable→±∞；**v7/v8/v9 是首问延迟治理的三版**（v7 探针 3 个 → 出卡掉到 15/20；v8 探针 4 个 → 16/20；v9 探针 4–5 个 + 每个假设两向权重 → 20/20）。旧图和旧报告先看报告头部的 prompt 版本。schema 里 `probe.evidence` 与 `claim` 都是可选，「生成图必须有 evidence」由 `graph_structure.review(require_evidence=True)` 强制 |
| 物理/语文的 prompt 版本各自钉住 | `SYNAPSE_GRAPH_PROMPT_VERSION` 现在**只控制数学**（默认 `graph-v9`）；物理是 `_PROFILES` 里的常量 `graph-v9-physics`，语文是 `graph-v6-chinese`。它们的 prompt 文本没跟着数学改，标签就不能假装改了——`test_graph_build.py` 专门断言这三个值。改物理/语文 prompt 时改常量并同步测试，别指望环境变量 |
| 首问对生成题不再改写（0 次 `llm_call` 是设计） | `SessionService.start()` 对 `annotated=False` 的题用确定性 `GraphProbeComposer`，只对标注种子题调 `opening_composer`（`LeakSafeProbeComposer(T3)`）。看到生成题首问没有 `probe_rewrite` 审计行，不要当成 composer 没接上；`tests/test_first_question.py` 有 4 条断言盯着（生成题不调、标注题调、第 2 轮起生成题也调、改写要审计） |
| prompt 长度不花时间，输出长度才是预算 | 实测 37 tokens 与 3677 tokens 的 TTFT 无差异（都是 0.8–3s 的供应商底价），completion ≈220–320 tokens/s。想省首问延迟就去砍输出（探针数/选项数/evidence 条数），把 system prompt 压缩一遍不会有可测收益——别为此改 prompt 的规则 |
| SymPy 在组合根预热 | `build_container()` 对生成器调 `warm()`，`DefaultGraphVerifier.warm()` 幂等 import SymPy（1665ms）。**不要**把这个导入挪回请求路径，也不要在测试里依赖「第一次带 claim 的调用会自己导入」——预热缺失的表现是单个请求多 1.7s |
| claim 修复只用预算剩余量 | 反例推翻 claim 后只发一次 `graph_claim_repair`（只重写区间，不重生成整图）；只有当「`SYNAPSE_GRAPH_RETRY_BUDGET_S`（默认 7.5s）− 已用时间 ≥ 1s」才发，且调用超时直接取这个剩余量。超时/格式错/继续被推翻/预算不足都保留图、丢 claim，记 `claim_dropped_refuted` 加 `claim_retry_timeout` / `claim_retry_malformed` / `claim_repair_refuted` / `retry_skipped_budget`。**只修一次**，不要改成循环。schema 失败的重试仍走整图（那是拿到图的唯一路径），但要用最小可用图 |
| 一次模型调用只写一条审计 | `graph_build` 的行数就是调用次数。claim 被推翻的「丢弃+保留图」分支原来写两行（`schema_ok=false` 一行、`schema_ok=true` 一行），按行统计会把调用数和重试数都算多；现在丢弃的那次一行、保留的那次一行。看到「23 次调用 / 3 次重试」这类历史数字先确认是哪一版 |
| 探针数直接决定出卡率 | `aligned` 策略下同一批 20 题：3 探针 15/20、4 探针 16/20、5 探针 **20/20**。卡点门槛 0.80+0.25 没动，变的是「攒证据的轮数」。压输出预算时先看 s5_session 的出卡率，不要只看建图耗时——省下的 0.5s 可能换来 4 道题不出卡 |
| 生成图证据会被全图校准 | `review(..., calibrate_evidence=True)` 只在全图峰值 `0 < max|w| < 0.90` 时按 `0.90/峰值` 统一放大，记 `evidence_calibrated`；只放大不缩小，不改符号与相对强弱，手写种子图不走这条分支。0.90 是证据强度下限，不是数学正确性；引用生成图权重时先看报告里的 max|w| 与修复码 |
| PowerShell `Set-Content` 会按 ANSI 重写含中文的 UTF-8 文件 | 本机这样把 `test_graph_build.py` 写坏过（中文变 `?`，ruff 报 `stream did not contain valid UTF-8`）。改 Python/中文文件一律用 edit 工具；确需命令行替换先确认 `$PSVersionTable.PSVersion` 并显式 `-Encoding utf8` |
| SymPy 没有 `py.typed` | `mypy src` 会报 `import-untyped`；`pyproject.toml` 里对 `sympy*` 开了 `ignore_missing_imports`（验证器把所有 SymPy 调用收在 float 边界的 helper 后面）。`sympy` 只在 `[dev]` extras 里，生产环境缺它时验证器返回 `unknown/unavailable`，不抛异常 |
| `claim` 是可丢弃的元数据 | 形状不支持（`kind`/`relation` 不在 v1、`parameter` 与 `variable` 同字母）→ 直接丢弃并记 `claim_dropped_unsupported`；反例推翻且重试后仍错 → 丢弃并记 `claim_dropped_refuted`。两种情况**图都保留**，`graph.claim` 变 `None`、反例留在 `GraphBuildResult.verification`。不要顺手把它改成建图失败，也别把丢弃当静默降级——修复码和审计里的 `verification_status` 都记着 |
| 模型会把探针放到顶层 | 观测到 `{"nodes":[...],"probes":[...]}` 的扁平化写法；探针没有归属节点，猜归属就是发明结构，所以判 `probes_top_level`（`schema_invalid`）并让重试带着提示改。prompt 第 1、12 条写死了「探针在节点内部」 |
| 验证是反例搜索，不是证明 | `pass` 只表示固定网格 + 黄金分割细化没找到反例；`unknown` 是没 claim / 读不懂 / 落在 1e-9 容差带。对外表述只能用「未发现反例」，不能写「已证明」 |
| `Probe.evidence` 的键是**选项字母** | `{"A": {"H_L2": 0.6}}`，与 `SubmitAnswerCommand.option_id` 同一套编码；写成选项文本不会报错——`HypothesisSet.observe()` 查不到就静默不更新后验，表现出来是「答了 6 轮置信度还在 0.45 附近」。评测脚本里犯过一次（`s5_session.py`），排查时先看 `session.hypotheses.evidence` |
| 生成题没有存储答案 | `InMemoryAnswerStore.answer_for()` 对 `P_GEN_*` 抛 `KeyError`，`AnswerStoreLeakGuardFactory` 捕获后退化为通用短语表（`guards.py` 里写明）。这意味着 n-gram 泄漏规则在生成题上**不生效**，只剩 prompt 约束与 `forbidden_token`；不要在报告里把它算成「泄漏守卫已覆盖」 |
| 通用对齐只查「有没有写」 | `TypeCueAligner` 与 `ClauseCueAligner` 都是存在性检查：漏了能发现，写错了发现不了。后者只多一个 `partial`（至少一个小句对上了），仍是「写到没写到」而不是「对不对」。卡面措辞因此只有两种——引用某次作答，或「过程里没有出现「…」这一步」；结构提示多一档「写到了一部分」。**不要**把它改成「这一步错了/理解偏了」，那是 `RuleBasedAligner` + 标注 golden 才支撑得起的断言 |
| 首问预算现在含一次建图 | 未见题走 `ProblemResolver` 会现场建图（p50 4–5s），首问 8s 预算的余量比标注库路径小；`on:10` 灰度要单独看这一支的 P95，不要把 M2 的 1.10s 改写延迟当整体口径 |
| 物理接入不是「自动识别」 | `PhysicsPlugin.identify()` 对任意文本返回 `None`；没有标注物理题集，`subject="physics"` 必须由请求显式声明。未声明时 `ProblemResolver` 仍按数学走，物理题会被数学 prompt 建图——这是 S3「不猜学科」的延续，不是 bug；前端要把学科选择传给 API |
| 物理图没有 claim | 物理 prompt 第 11 条明确不输出 claim；模型若仍写，建图器丢弃并记 `claim_dropped_unsupported`，`verification.status` 为 `unknown`。不要用数学 SymPy 验证器去“验”物理答案（单位/矢量不在其覆盖内），也不要把 `unknown` 写成“已核对” |
| 物理 `verify()` 需要结构化 `StudentStep.data` | `PhysicsPlugin.verify()` 只读 `data`（`equation`/`expression`、`unit`、`units`、`values`、`expected`、`tolerance`）；纯文本返回 `unknown`，不要靠正则猜单位。`pass` 可能只做了量纲（detail 写明“未做数值回代”），不能写成“答案已证明”。解析器禁止 `eval`/`exec`，只解释白名单 AST；未知单位/符号/函数/畸形输入一律 `unknown` |
| 物理卡面靠 `hypothesis_labels` | 假设 id、先验、log-odds、`0.80+0.25` 门槛全部与数学共用；物理只替换卡面文案。排查“物理卡出现恒成立/参数分类”时先看 `SessionFactory._labels_for()` 和插件的 `hypothesis_labels`，不要新建一套假设 id |
| `s5_session.py` 已支持 `subject` | 读 JSONL 的 `subject` 字段（默认 `math`）并传给 `StartSessionCommand`；S6 的 `s6_physics.py` 复用它的 `run_case`/统计。改这个脚本时保持数学默认路径不变 |
| 语文（NONE 档）不生成探针与 claim | `graph-v6-chinese` 明确写「不要输出探针」「不要输出 claim」；模型若仍写了，`_build_graph` 丢弃并记 `probes_dropped_unsupported` / `claim_dropped_unsupported`，**图保留**。无探针图只对非探针学科放行（`review(..., require_probes=False)`），数学/物理仍强制；不要把这两条修复码当失败 |
| NONE 档不出卡不是「前端藏起来」 | `application/commitment.py` 的 `Capabilities` 是唯一开关，`SessionService.start()` 在建图/对齐之后、探针规划之前分流；NONE 会话没有 `prompt`、没有 `diagnosis`，`turn=0` 且状态直接 `CLOSED`，`GET /sessions/{id}` 也不会凭空出现卡。排查时先看 `capabilities_for(level)`，不要在前端或 DTO 里加第二处判断 |
| 结构提示是派生值，不进聚合根 | `StructureHint` 由对齐结果 + 图在 `get()`/`start()` 时重建，刷新后一致；`progress.confidence` 对 NONE 会话仍是 `HypothesisSet` 的初始值，**不能当把握显示**——前端以 `hint.level == "none"` 为准忽略 progress，卡片/探针一律不渲染 |
| 结构提示的「没写到」是存在性判断，v0.2 多一档「只写到一部分」 | `missing` 表示连一个小句/类型线索词都没对上；`partial` 表示至少一个小句对上、但覆盖率 <75%。两者都不表示写错。语文节点常是多分句长句，S8 用分句级匹配把 S7 的 `missing` 拆出 `partial`（full covered 仍 1.7，partial 2.3，加权 2.8/8）；阈值在 `ClauseCueAligner`，不要为了「看起来更准」调低。措辞固定「看起来没有写到 / 只写到了一部分」，不要写成「这一步错了」 |
| `specs/structure-hint.schema.json` 是 v0.2 必检契约 | `check_repo.py` 的 `PUBLIC_REQUIRED` 与 `REQUIRED` 都登记了它；`status` 枚举是 `covered|partial|missing`，`version` 必须是 `"0.2"`。改 `HintOut`/`StructureHint` 必须同步 spec 与 `apps/web/src/lib/api/generated.ts`，否则类型检查与契约测试会对不上。它是**另一张表**，不要往 `DiagnosisOut` 上挂可选字段来「复用」 |
| 对齐策略由插件选，不在 deps 里分支 | `SubjectPlugin.aligner_for(problem)` 是唯一入口；`SessionFactory` 只在没有插件时退回构造参数。`CompositeAligner` 只看 `problem.annotated`，不再有第二套 `annotated_ids`；新增学科时实现 `aligner_for()`，不要改 `factory.py` 或 `deps.py` 的 if/else。数学/物理的两态对齐器不得产生 `partial`，`AlignmentResult.partial_node_ids` 默认空 |
| 浏览器侧首问只占 1–5%，且不能靠 prefetch 省 | 真实浏览器量到的是「API 4.19–5.58s + 客户端 56–168ms（本机）/ 221–237ms（4G RTT 150ms）」。客户端那半是 App Router 动态路由取 RSC 的 1 个 RTT；`router.prefetch("/diagnose/_")` 在 4G 下没有可测收益（prefetch 只取片段壳，真 RSC 仍按真实 id 再取），别再加回来。量的时候每题必须是**没被 `ProblemResolver` 缓存过**的新题，否则会量到 0.2s 的缓存命中 |
| 前端测试跑的是 jsdom，不是浏览器 | `npm test` 用 `vitest.config.mts` + `src/test/setup.ts`；jsdom 没有 `matchMedia`/`rAF`，已在 setup 里垫片，`next/link` 在 `StructureHintView.test.tsx` 里被替换成 `<a>`。组件测试不覆盖真实布局、CSS 与动画，不能替代 `npm run build` 或浏览器 smoke；新增依赖后先跑 `npm ci --dry-run` 确认 lock 一致 |
| 没有真数据时也有可机算的准确率：构造真值 | `scripts/eval/s5_gap_probe.py` 让模型扮演学生、**故意跳过第 k 步**并自报 `kept`，于是「哪一步该算没写」由构造决定。20 题（1 条泄漏剔除）：写了的步骤被认出 **59/98 = 60%**、缺口被认成 `missing` **13/19**、「首个 `missing` 就是被跳过那步」**4/19 = 21%**、卡点落在它 **4/18 = 22%**。前两个能干净归因到 `TypeCueAligner`（整句 3-gram 对口语改写几乎不命中）；最后那个含 `aligned` 策略代答的水分。`kept` 自报是防伪约定：模型把跳过的那步写了、或与节点文本有 6 字以上重合，就判泄漏并剔除（本轮 1/20）。改对齐器前后各跑一遍，比争论哪个匹配器更强可靠 |
| 判学生写的式子：误判比漏判更伤 | `verification/notation.py` 只做机械转写（`2x`→`2*x`、`x²`→`x**2`、`sinX`→`sin(x)`、`根号（16）`→`sqrt(16)`），**读不懂就返回 `None`，绝不猜**；`equalities.py` 只在「两边都读得懂、自由符号相同、且都不是单个符号」时才判等号，`x=2`、`an=3^(n-1)` 这类赋值/定义不判。踩过的坑：`根号下（80/245）` 若被截成 `80/245`，会把学生**正确**的一步判成「等号不成立」——现在整段跳过并记 `notation_unsupported`。写这条链路的测试先测「不该报的没报」（`test_unreadable_heights_do_not_produce_a_false_alarm`），再测「该报的报了」 |
| 等式链校验是 opt-in；卡片只查首问 | `SYNAPSE_EQUALITY_CHECK` 默认 `off`；打开后 finding 会替换标注题手写的 `one_line`（golden 的逐字节基线只保证在 `off` 下成立）。finding 在 `SessionService.start()` 写进 `session.work_findings`；后续步骤走 `POST /sessions/{id}/steps`（只读、不推进状态、不出卡），开关关闭时返回 `unknown`。数学 `MathPlugin.verify()` **只返回 `fail` 或 `unknown`，永不返回 `pass`**——没找到可证伪的等号不等于这步正确。生产环境缺 SymPy 时 `SympyEqualityChecker` 返回空 findings、不抛异常——空结果只是「没判」，不能写成「已核对」 |
| 单步验证的 `fail` 用 `findings`，不解析 `detail` | `specs/step-verification.schema.json` 已是 **v0.2**：`fail` 返回 `findings[{kind,left,right,summary,counterexample}]`（最多 3 条，`left`/`right` 各 500 字、`summary` 300 字），`detail` 只作可读句子，**没有稳定前缀**。`unknown`/`pass` 的 `findings` 必须为空；schema 的 `if/then` 会强制 `fail` 至少 1 条、`unknown`/`pass` 为 0 条；不要从 `detail` 里切「这个等号不成立：」来排版。改 `StepVerdictOut`/`Verdict` 必须同步 spec、`apps/web/src/lib/api/generated.ts` 与 `test_step_verdict_conforms_to_the_public_schema`（`Draft202012Validator` 校验真响应） |
| 出卡率不是诊断准确率，命中率也不是 | `s5_session.py` 的 `aligned` 策略让模拟学生顺着对齐结论答题：20/20、100 题里 99/100 出卡只能证明接线。真实复盘跑 `s5_review.py`：它读学生原文，出卡与「期望卡点」做去空白子串匹配，`人工判断` 一列留空给老师。4 条 `public-web`（公开问答页里学生自己写的过程）拿到 4/4 出卡、4/4 节点在图内，但关键词命中只有 0/4（另一次 1/4）——**其中两三张卡其实指对了步骤**（`P_PUB_002`「代入基本极限 sin x/x→1」、`P_PUB_004`「用 a_n=S_n-S_{n-1} 消去 S」），是期望关键词「化简」「下标」没出现在节点文本里。**命中率比诊断本身更粗**，别拿它当准确率；卡点层仍 4/4 是 `L1`（层由「对齐发现的第一处缺失」决定，和题目语义无关） |
| 生成题的卡面文案不能沿用种子题的主题 | 种子 `H_L1` 的 label 是「概念不清：恒成立与最值」，生成题早期直接复用它，于是 100 题里数列、立体几何、概率的卡都写着「恒成立与最值」。现在 `MathPlugin.labels_for(problem)` 按 `problem.annotated` 分档：标注题返回原表（种子卡逐字节不变），生成题用「概念不清：没抓住这一步的关键条件」；`SessionFactory._labels_for(problem)` 先问 `labels_for()` 再退回 `hypothesis_labels` 映射。物理/语文的 `hypothesis_labels` 不受影响。加卡面文案时先想清楚「这句话对任意主题的题都成立吗」 |
| 复盘脚本的 `work` 会改变对齐结果 | `StartSessionCommand` 的 `work` 参与存在性对齐，`answer` 只用于泄漏守卫/展示。`s5_session.py` 默认灌 `SAMPLE_WORK["math"]`（「先确认题目的条件，再按参数分类讨论」），所以它对齐到的节点是那句模板话匹配到的；复盘时必须传学生原文，否则量到的是模板的卡点 |
| `s4_graph_build.py` 的默认参数仍是 20 题 v0.1 | 默认 `--problems unseen-v0.1.jsonl`、`--out m2.5-s4-graph-build.md`、`--graphs-dir s4-graphs`，而这三项都已被 `-v02` 取代（`eval/reports/INDEX.md` 里标为历史）。跑 100 题必须显式给：`--problems eval/problems/unseen-v0.2.jsonl --out eval/reports/m2.5-s4-graph-build-v02.md --graphs-dir eval/reports/s4-graphs-v02`。否则会用 20 题口径**覆盖**那份历史报告，第二天看起来像指标倒退——这是「报告名不带轮次」的直接代价 |

---

## 六、红线（改坏了产品就没了）

1. **LLM 不得决定状态**——它只输出 `ProbePrompt` 候选；`session.advance()` 必须由应用层调用。
2. **LLM 主链路不得进 Arq 队列**——进队列就破 8s 首问预算。
3. **规则版不得删除**——`SYNAPSE_LLM_MODE=off` 必须让全部测试通过；它是降级路径，也是对照基线。
4. **答案隔离不得合并**——`AnswerStore` 与 `ProbeComposer` 物理分离；`answer_for()` 的返回值永不进模型上下文。
5. **`specs/` 先改后动代码**——破坏性变更要升 `version`。
6. **README 不写完成度**——对外它是架构文档；进度只写在本文件。

---

## 七、文档地图

```text
README.md                    对外：架构（无进度）
AGENTS.md                    对内：本文件
docs/README.md               文档总索引（三层：设想／主体／实现）
docs/adr/                    决策记录（改选条件）
docs/design/chapters/        设计书正文 00–14 + 附录（会被合并成 DOCX/PDF）
docs/design/plan/            本地详尽计划（未入库）
docs/design/release/         构建产物（未入库，需重建）
docs/vision/                 设想层：学习机理（诊断—归因—干预—巩固），不承诺已实现
specs/                       机器可验证契约（JSON Schema + 状态机）
apps/api/                    后端：domain / application / infrastructure / api 分层
apps/web/                    前端：Next.js 15
eval/golden/                 M2 金标准 10 条（入库，需 `git add -f`）
eval/problems/               M2.5 题集：100 道数学（v0.2，带 expected_answer）+ 6 物理 + 6 语文
                             + 学生作答样本（3 条 synthetic + 4 条 public-web，入库，需 `git add -f`）
eval/reports/                评测报告与生成图（产物，不入库；INDEX.md 是基线索引）
eval/redteam/                诱导／越界／泄漏用例（只有 README，未开工）
scripts/release/             公开仓库导出：export_public.py + templates/（把本仓裁成对外树）
```

---

## 八、历史背景（为什么长这样）

项目起点是"12 分钟测评 + 学习 OS"，在设计与评审中被判定跑偏，整体归档到 `_local/archive/v0-broad-os/`，转向**单题诊断引导**。因此仓库里有两代材料的痕迹：

- `_local/archive/v0-broad-os/` — 旧方案全文，**不要当现状引用**；
- 第 11 章记录的是当时的 Java/Spring 设计过程，**已被 ADR-0001 取代**，只作方法论留存；
- 旧会话里的 "M2 = 处方-验证闭环" 属于 v0 口径，与当前 M2（LLM 追问）无关。

当前 M2 / M2.5 的定义见第 12、13 章。

文档与计划按**范围与验收**表述，不写「几人几周」这类投入估算。