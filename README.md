# SynapseMind 突触智学

> 单题诊断：把“我不会”定位到一个可验证的卡点。

学生提交一道题和作答过程。系统不评分、不排名，也不直接给出完整解答；它以 2–6 轮追问，定位解题链上最早失效的认知动作，输出一张卡点卡：层位、证据、被排除的竞争假设、置信度与下一步训练。

模型负责生成候选问题与措辞；状态推进、证据门禁和停止条件由代码决定。

![诊断引擎：解法图、步骤对齐、假设与探针](docs/design/assets/02-diagnosis-engine.png)

## 诊断对象

一道题被拆成一张解法图（DAG）。节点是七类认知动作：

| 类型 | 含义 |
|---|---|
| `READ` | 读题、符号与量词 |
| `CONCEPT` | 定义、定理与公式 |
| `CONDITION` | 文字条件转成式子、图形或分类 |
| `STRATEGY` | 选择整体路径 |
| `TRANSFORM` | 等价变形 |
| `COMPUTE` | 计算与代数 |
| `CHECK` | 校验、边界与反例 |

卡点按认知层位标注：

| 层位 | 性质 | 典型表现 |
|---|---|---|
| L0 | 读题与语义 | 漏读条件，误读“任意 / 存在” |
| L1 | 概念与定理 | 不知道 `f'(x)=0` 只是必要条件 |
| L2 | 条件转译 | 参数分类缺支，边界未检查 |
| L3 | 策略 | 选错方法，或使用未验证的前提 |
| L4 | 执行 | 变形、求导、解不等式出错 |
| L5 | 校验与元认知 | 不检验充分性，自信与正确率背离 |
| L6 | 资源与状态 | 时间不足、焦虑、注意力下降 |

判定标准是可证伪性。L2 的卡点必须能落到具体反例，例如 `a=-1` 时原式不成立；模型的主观判断不能作为结论。

## 对话内核

10 个状态，事件驱动。转移表写在代码里，不交给模型：

```text
INGEST → PARSE → ALIGN → PROBE ⇄ PROBE
                          ├─→ DIAGNOSE → INTERVENE → VERIFY → CLOSED
                          └─→ STOP → CLOSED
PARSE → NEED_INPUT → PARSE
ALIGN → DIAGNOSE   （断点唯一且证据充分）
ALIGN → STOP       （超纲 / 无法建图）
```

| # | 约束 | 实现位置 |
|---|---|---|
| 1 | 一次一问，选项不超过 4 个 | Schema 校验 |
| 2 | 学习模式不输出最终答案 | 输出结构、出口守卫 |
| 3 | LLM 只输出动作候选，不推进状态 | 转移表 |
| 4 | 后验 < 0.55 不硬判 | 阈值守卫 |
| 5 | 最多 6 轮，到顶必须收束 | 计数器 |
| 6 | 进入诊断需后验 ≥ 0.80，且领先 ≥ 0.25 | 后验与边际 |
| 7 | 每轮回答写入证据链，缺证据不诊断 | 证据门禁 |

后验用 log-odds 累加，softmax 归一。标注题的选项权重来自人工标定；生成图的权重由模型给出，再经结构规则与全图校准，未知题不借用其他题的权重。

## 诊断引擎

1. **解法图**：标注题使用预置图；未见题由模型现场生成，并经过 schema、结构规则与一次重试。
2. **步骤对齐**：标注题使用规则对齐；生成题按节点类型检查线索词、式子与覆盖范围。
3. **断点定位**：取最早失效、且前置节点均通过的节点。
4. **假设与探针**：在 2–3 个候选假设之间选择区分度最高的探针，一次只问一个问题。
5. **收束**：后验达到阈值后生成卡点卡；否则在 6 轮内低置信收束。

细节见 [诊断引擎](docs/design/chapters/04-诊断引擎.md)。

## 答案隔离

学习模式下，最终答案不进入可生成的输出路径。隔离由四层组成：

| 层 | 机制 |
|---|---|
| 检索 | 学习模式不装配解答类片段 |
| 模型输入 | 系统提示禁止给出最终答案与完整步骤 |
| 输出结构 | 响应类型不含 `solution`；问题长度与问号数受校验 |
| 出口 | 禁用词表与字符级 n-gram 检测，命中即改写为安全追问 |

用户仍可主动退出学习模式并查看答案。该次会话不生成卡点卡，也不计入诊断。

## 学科边界

| 学科 | 能力档 | 行为 |
|---|---|---|
| 数学 | 完整 | 生成或读取解法图，追问，输出卡点卡；支持单步等式校验 |
| 物理 | 部分 | 追问与卡点卡；量纲与数值回代需要结构化步骤，纯文本返回 `unknown` |
| 语文 | 提示 | 不追问、不出卡，只对齐步骤结构并输出提示 |

学科能力由插件的 `level` 决定，统一在 `application/commitment.py` 收口。新增学科需要实现 `SubjectPlugin`，不在路由或工厂里增加分支。

## 当前架构

```text
apps/web        Next.js 15 / React 19：交题、追问、诊断卡、单步检查
apps/api        FastAPI：状态机、诊断、生成图、验证、SSE
apps/worker     部署入口；当前无实际任务
specs            状态机与 JSON Schema
eval             公开评测协议；私有语料与逐题报告不入库
scripts          dev / contracts / checks / eval
docs/adr         架构决策记录
```

`apps/api` 分四层：`domain`、`application`、`infrastructure`、`api`。`domain` 不依赖数据库与模型 SDK，`application` 只依赖端口，跨层 import 由 import-linter 在 CI 中拦截。

当前使用内存仓储，未接入 PostgreSQL、Redis、RAG、鉴权与多租户。模型默认关闭；未配置 key 时只走规则路径，非种子题返回 422，这是显式边界。

## 已验证

| 项 | 结果 |
|---|---|
| 后端测试 | 本地 359 passed；公开 CI 337 collected / 3 skipped / 0 failed |
| 前端测试 | 39 passed / 6 files |
| 浏览器接线 | Playwright 4/4（mock API） |
| 结构化合图 | 100 道未见数学题 100/100 通过 schema 与结构规则；101 次调用、1 次重试；p50 4.17s / p95 4.83s |
| 首问延迟 | 20 道未见题 p50 4.2s / p95 4.7s（预算 8s） |
| 金标准回放 | 10/10，平均 2.40 轮 |

这些数字证明工程链路与契约，不证明诊断准确率。卡点是否指对，仍需教师标注与真实学生作答校准。

## 运行

```powershell
python scripts/dev/run.py          # 启动 API 与 Web
python scripts/dev/run.py --check  # 只检查环境
```

后端单独运行：

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src
```

前端单独运行：

```powershell
cd apps/web
npm run dev
npm run typecheck
npm test
npm run test:e2e
```

## 文档

| 文档 | 内容 |
|---|---|
| [产品与边界](docs/design/chapters/00-一页纸.md) | 三种入口、诊断流程、示例与当前范围 |
| [诊断引擎](docs/design/chapters/04-诊断引擎.md) | 解法图、对齐、卡点层级、假设与探针 |
| [ADR-0001](docs/adr/0001-language-and-code-architecture.md) | 语言与代码架构 |
| [ADR-0002](docs/adr/0002-llm-provider-and-golden-scale.md) | 模型供应商与金标准规模 |
| [ADR-0003](docs/adr/0003-generated-graph-evidence-calibration.md) | 生成图证据权重校准 |
| [ADR-0004](docs/adr/0004-first-question-latency-budget.md) | 首问延迟预算与治理 |
| [评测协议](eval/README.md) | 指标、口径与公开证据 |

## License

原创代码使用 MIT。第三方组件遵循各自许可。