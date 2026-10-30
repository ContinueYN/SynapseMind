# apps/api

Python 3.12 + FastAPI 的**模块化单体**。在线链路（状态机、对齐、探针、卡点卡、答案防护）在这里；离线任务规划在 [`../worker`](../worker/README.md)。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。

## 已有模块

```text
apps/api/src/synapse/
├─ domain/                    # 纯函数/值对象，零 I/O
│  ├─ dialogue/
│  │  ├─ states.py            # DialogueState + DialogueAction
│  │  ├─ events.py            # DialogueEvent
│  │  ├─ table.py             # 显式转移表、IllegalTransition
│  │  └─ session.py           # 聚合根：advance/record_turn/current_probe_id
│  ├─ problem/
│  │  ├─ models.py            # Problem / SolutionGraph / Probe / AlignmentResult
│  │  ├─ identification.py    # 严格识别：归一化后“包含”已标注题，否则拒绝
│  │  └─ alignment.py         # StepAligner 端口 + Rule/TypeCue/Clause 三种对齐策略
│  ├─ diagnosis/
│  │  ├─ models.py            # L0–L6、Hypothesis、DiagnosisCard
│  │  └─ hypotheses.py        # 先验/对数似然证据/后验/判定
│  ├─ evidence/models.py      # Evidence + EvidenceChain（来源/主张/支持假设/轮次）
│  └─ guard/leak.py           # 禁用词 + n-gram 出口防护
├─ application/               # 用例编排 + ports（Protocol）
│  ├─ ports.py                # SessionRepository / ProblemRepository / AnswerStore / Clock / IdGenerator
│  ├─ llm.py                  # LLMClient 端口 + 请求/响应 DTO + 超时/失败异常
│  ├─ audit.py                # AuditEntry + CallAuditor（一次调用、一次降级、一次 shadow 差异）
│  ├─ trace.py                # 请求级上下文（session_id/turn），不拓宽 composer 签名
│  ├─ factory.py              # SessionFactory：组装会话，不让 service new 聚合
│  ├─ planner.py              # ProbePlanner 策略：优先区分 top 假设
│  ├─ composer.py             # GraphProbeComposer + LeakSafe/Fallback/Shadow/Canary 装饰器
│  ├─ card_builder.py         # 由收敛假设生成 DiagnosisCard
│  ├─ replay.py               # golden 回放与退出判定（eval 与 pytest 共用）
│  ├─ subject.py              # SubjectPlugin 端口：识别/建图/对齐策略/探针/证据/验证
│  └─ service.py              # SessionService（Facade）：start/get/submit/exit
├─ infrastructure/            # 端口实现
│  ├─ seed.py                 # M1 唯一种子题 + 4 个探针 + 标准答案
│  ├─ in_memory.py            # 会话/题目/答案仓储（重启即丢）
│  ├─ guards.py               # 唯一读取答案的适配器：构造泄漏防护
│  ├─ system.py               # UTC 时钟 / S_ 会话 ID
│  ├─ subjects/               # 学科插件实现（M2.5）
│  │  ├─ math.py              # MathPlugin：严格识别 + 种子图/EVIDENCE + 生成图证据
│  │  ├─ physics.py           # PhysicsPlugin：生成图 + 量纲/数值验证（PARTIAL）
│  │  └─ chinese.py           # ChinesePlugin：生成图 + 结构提示（NONE）
│  └─ llm/                    # 唯一允许 import 模型客户端的包
│     ├─ settings.py          # off/shadow/on:10 开关、模型、超时、canary 分桶
│     ├─ client.py            # OpenAI 兼容客户端（默认 DeepSeek）
│     ├─ replay.py            # 按请求哈希回放录制响应（CI 零成本）
│     ├─ schema.py            # 结构化输出校验（一问、≤80 字、单行）
│     ├─ composer.py          # LLMProbeComposer：只改写措辞
│     └─ audit.py             # JSONL / 内存审计落地
└─ api/                       # FastAPI 协议层
   ├─ schemas.py              # Pydantic DTO；学习模式无 solution 字段
   ├─ mappers.py              # domain → DTO
   ├─ deps.py                 # 组合根 Container + DI
   ├─ routes.py               # /api/v1/* 薄路由
   └─ main.py                 # create_app、CORS、app 实例
```

## 依赖方向

```text
api → application → domain
api → infrastructure → application.ports
domain 不 import FastAPI / SQLAlchemy / OpenAI
application 不 import 任何模型 SDK；模型客户端只在 infrastructure/llm
```

`import-linter` 在本地与 CI 强制；当前契约 `API -> application -> domain` 保持 0 broken。

## 设计模式落点

| 模式 | 位置 | 解决什么 |
|---|---|---|
| State（显式转移表） | `domain/dialogue/table.py` | 下一个状态由表决定，LLM 不能改流程 |
| Strategy | `domain/problem/alignment.py`、`application/planner.py` | 对齐算法、探针选择可替换 |
| Factory | `application/factory.py` | 会话组装集中一处，校验入口唯一 |
| Decorator | `application/composer.py` | 泄漏防护、失败降级、shadow 双跑、canary 分流都在同一签名上叠加，被装饰者无感 |
| Adapter | `infrastructure/llm/` | `LLMClient` 端口 → DeepSeek / Qwen / GLM / 回放，换供应商只换配置 |
| Repository / Ports | `application/ports.py` | 内存适配器可替换为 PostgreSQL，不碰领域 |
| Facade | `application/service.py` | 路由只依赖一个用例入口 |
| DTO / Mapper | `api/schemas.py`、`api/mappers.py` | HTTP 契约与领域对象解耦 |

> 没有为了“用模式”而加抽象：仓储先内存，LLM 先不接，探针先规则版；每个抽象都对应一个真实的替换点。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/sessions` | 交题 + 过程，返回首问 |
| `GET` | `/api/v1/sessions/{id}` | 恢复会话/当前问题 |
| `POST` | `/api/v1/sessions/{id}/turns` | 回答当前探针 |
| `POST` | `/api/v1/sessions/{id}/steps` | 验证一条步骤（只读，不推进会话） |
| `POST` | `/api/v1/sessions/{id}/exit` | 显式退出学习模式 |

约定：

- 响应 DTO **没有** `solution` / `final_answer` 字段；学习模式拿不到最终答案。
- `option_id` 为 `A`–`D` 或 `unknown`；文本答案也可匹配选项。
- 一次只返回一个 `prompt.question`；最多 6 轮。
- 后验 `≥0.80` 且领先 `≥0.25` 才出卡；到轮次上限仍 `<0.55` 明确不出确定卡点。
- `/steps` 只验证提交的这一步（`specs/step-verification.schema.json`）：不推进状态、不出卡；`unknown` 表示未启用/读不懂/没有可判的断言，不是“这步正确”。

## LLM 追问（M2）

模型只做一件事：把 `Probe` 里已经选好的问题换个更自然的说法。**选哪个探针仍由 `ProbePlanner` 决定，状态仍由转移表推进**——模型拿不到 `advance()`。

| 开关 | 行为 | 用途 |
|---|---|---|
| `off`（默认） | 全走 `GraphProbeComposer` | CI、本地、回滚态 |
| `shadow` | 双跑，返回规则结果，只记差异 | 上线前零风险对比 |
| `on:10` | `sha256(session_id) % 100 < 10` 走模型，失败回退规则 | canary |
| `on` | 全量 | 灰度通过后 |

环境变量：`SYNAPSE_LLM_MODE`、`SYNAPSE_LLM_MODEL`（默认 `deepseek-chat`）、`SYNAPSE_LLM_BASE_URL`、`SYNAPSE_LLM_API_KEY`（或 `DEEPSEEK_API_KEY`）、`SYNAPSE_LLM_TIMEOUT_S`、`SYNAPSE_LLM_AUDIT_PATH`。没有 key 时即使 `mode=on` 也走规则版。

本地把变量写进**仓库根目录的 `.env`** 即可：`scripts/dev/run.py` 用 `uvicorn --env-file` 传入，`scripts/eval/m2_exit.py` 显式 `load_dotenv()`。库代码与测试**不会**隐式读这个文件，所以本机的 key 不会改变测试结果。

生成图的 prompt 版本：数学由 `SYNAPSE_GRAPH_PROMPT_VERSION` 控制（默认 `graph-v9`），物理与语文各自钉在自己的常量上（`graph-v9-physics`、`graph-v6-chinese`）——它们的 prompt 文本没跟着数学一起改，审计标签就不能假装改了。缓存键包含版本，改 prompt 必须同时升版本，否则旧缓存会掩盖变化。

**首问的两次调用只留一次（ADR-0004）**：未见题要现场建图，首问就在 8s 预算里。生成题的首问走确定性渲染器，不再花一次模型往返去润色一条刚由同一个模型写出的问句；标注种子题仍走 T3 改写。claim 被反例推翻后**只重写区间**（`graph_claim_repair`），不再重生成整图；请求钉死表达式/参数/定义域，只允许改 `answer`，调用超时取 `SYNAPSE_GRAPH_RETRY_BUDGET_S`（默认 7.5s）减去已用时间，剩余不足 1s 就保留图、丢掉 claim 并记 `retry_skipped_budget`。SymPy 在 `build_container()` 预热，首次带 claim 的请求不再付约 1.7s 的导入。

失败链：JSON 不合法 → 重试 1 次 → 仍失败回退规则；超时与传输失败不重试（保 8s 首问预算），直接回退。每次调用、每次降级、每条 shadow 差异都写 `AuditEntry`：`session_id`、`turn`、`model`、`latency_ms`、`prompt_tokens`、`completion_tokens`、`retried`、`fallback_reason`、`schema_ok`。

答案隔离：发给模型的只有题面 `stem` 与探针本身；`node.text` / `common_errors` 不发送。出口仍是 `LeakSafeProbeComposer`（最外层），命中即改写。

## 学科插件（M2.5）

`SubjectPlugin` 是「对话内核不认识学科」的接缝：插件只提供**内容**（识别、图、对齐策略、探针、证据权重、验证结论），状态机仍决定状态。契约见第 13 章，端口在 [`application/subject.py`](src/synapse/application/subject.py)；实现在 [`infrastructure/subjects/`](src/synapse/infrastructure/subjects/)：`math.py`（STRONG）、`physics.py`（PARTIAL）、`chinese.py`（NONE）。S8 起 `aligner_for(problem)` 也由插件给出：数学在标注题/生成题之间切规则/类型线索，语文用分句级匹配，物理保持两态匹配。

**对外承诺由 `application/commitment.py` 的能力表决定**（这是唯一开关，别处不再判断）：

| `level` | 学科 | 探针 | 卡点卡 | 结构提示 |
|---|---|---|---|---|
| `STRONG` | 数学 | 有 | 有（附反例/SymPy 结论） | 无 |
| `PARTIAL` | 物理 | 有 | 有（`verify()` 只对结构化 `StudentStep.data` 给结论） | 无 |
| `NONE` | 语文 | 无 | **无** | **有**（`specs/structure-hint.schema.json`） |

NONE 档会话在 `ALIGN` 之后直接收束到 `STOP → CLOSED`：不追问、不定位卡点，只返回一条结构提示（步骤覆盖 + 下一步先看哪里 + 固定免责声明）。它不是卡点卡的简化版——`HintOut` 没有 `layer`/`confidence`/`next_action`/`verify`，前端也无法把它渲染成卡。S8 起步骤状态是 `covered`/`partial`/`missing`（schema v0.2）：`partial` 只表示“节点里至少一个小句被写到”，不是“写错”，也不是“卡在这里”。

| 方法 | 数学（S2–S4） | 物理（S6） | 语文（S7） |
|---|---|---|---|
| `identify()` | 归一化后「包含」已标注题；不同题一律拒绝 | 恒 `None`（必须显式声明 `subject`） | 恒 `None` |
| `build_graph()` | `Problem` 返回手写种子图；`ProblemDraft` 走 `LLMGraphGenerator`：生成 → 机械修复 → 结构规则 → `solution-graph.schema.json` → 失败重试一次（重试要最小可用图） | 同一个生成器，prompt `graph-v9-physics`，不输出 `claim` | 同一个生成器，prompt `graph-v6-chinese`，不输出探针与 `claim`；无探针图由 `review(require_probes=False)` 放行 |
| `aligner_for()` | 标注题 → `RuleBasedAligner`；生成题 → `TypeCueAligner` | `TypeCueAligner`（S6 基线不重标定） | `ClauseCueAligner`（分句重合，可报 `partial`） |
| `probes_for()` | 返回节点自带探针 | 同左（`hypothesis_labels` 换物理词表） | 恒空 |
| `evidence_model()` | 生成图读图内 `probe.evidence`；只有已标注种子图回退手写 `EVIDENCE` | 只读图内权重，不回退数学 `EVIDENCE` | 恒空 |
| `verify()` | 单步等式链：读 `text`，可证伪时 `fail`（带反例），否则 `unknown`；从不 `pass`，`data` 忽略。图顶层 `claim` 另由反例搜索核对（`pass`/`fail`/`unknown`） | `StudentStep.data` 的量纲与数值回代；纯文本 `unknown` | 恒 `unknown`（NONE 档没有可自动验证的真值） |

`subject` 是显式声明：文本识别出的学科与声明不一致时返回 **422**，而不是静默按文本路由。三个插件共用同一套状态机与诊断门槛；对齐策略由插件给出（S8），`domain/dialogue/` 一行未改。

识别是**严格**的：只接受确实包含已标注题原文的提交（比较前忽略空白、标点、全半角与 LaTeX 转义），其余返回 422 并说明原因。关键字匹配会把「同一知识点、另一道题」也当成种子题，用错的解法图解释学生的错误——那比拒绝更糟。

## 本地命令

在仓库根目录一条命令启动 API + Web：

```powershell
python scripts/dev/run.py
```

只跑 API 检查：

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

uvicorn --app-dir src synapse.api.main:app --reload --port 8000
pytest
ruff check src tests
mypy src
.\.venv\Scripts\lint-imports.exe

# M2 退出判定：10 条 golden 回放，产出 eval/reports/m2-exit-v0.1.md
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py
```

生成接口契约与 Web 类型（本地产物，`generated.ts` 入库）：

```powershell
python ..\..\scripts\contracts\generate.py
```

## 当前不做

- 不做拍照 OCR：`problem.image_url` 已在 DTO 预留，但未实现（M3）。
- 不做 LLM 辅助步骤对齐（第 12 章 T5）：对齐结果直接决定先验与证据链，交给模型后规则基线不再可比，回滚成本高；**默认不做**。
- 不做数据库/鉴权/多租户：仓储是内存版；重启丢会话是已知边界（M3/M4）。
- 不返回标准答案：即使答错，也只给卡点卡和下一练。
- 不提前拆服务：拆分触发条件见 [apps/README.md](../README.md) 与 ADR。