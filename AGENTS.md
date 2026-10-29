# AGENTS.md — 开发交接

> 本文件面向**接手开发的人或新会话**。对外文档是 [README.md](README.md)（只讲架构，不标进度）；进度、未决项、环境陷阱都记在这里。

---

## 一、当前状态（2026-10-29）

**M1 walking skeleton 可本地运行**：交题 → 解法图对齐 → 2 轮探针 → L2 卡点卡。规则版实现，内存仓储。

**M2（窄口径）已落地**：`infrastructure/llm` + `LLMProbeComposer` + 校验/重试/降级 + `shadow` 双跑 + 10 条 golden 回放与退出判定报告。默认 `SYNAPSE_LLM_MODE=off`，部署形态与 M1 相同（内存仓储、无队列）。

**M2.5 S4/S5 已落地（2026-10-29 / 2026-10-30）**：解法图可由模型生成，必须过结构规则与 `specs/solution-graph.schema.json`，失败只重试一次并显式报错；生成图自带每个选项的 log-odds 证据权重（prompt 升到 `graph-v3`），`MathPlugin.evidence_model()` 只对已标注种子图回退 `EVIDENCE`。**S5 第三阶段：答案可被反例打脸**——图顶层可选 `claim`（`∀x∈D: f(x,a) rel 0 ⇔ a∈区间`），`infrastructure/verification/` 用 SymPy 做反例搜索并返回 `pass|fail|unknown`，`fail` 带具体反例回灌给模型重试一次。真实 20 题重跑（`graph-v3` 连跑四轮）：**建图稳定 20/20**，最后一轮 23 次调用、3 次重试，p50 4.05s / p95 5.51s；20 题里只有 `P_DERIV_003` 属于 v1 能形式化的形状，四轮都给出同一个错的 `a∈(-∞,e]`——`a=-24.46` 在答案区间内但 `x=-6.8e12` 时表达式 `-1.67e14 < 0`，带反例重试一次仍是同一区间，于是**丢弃 claim、保留图**。另外，模型偶尔会把存在性条件（`P_DERIV_004` 两个零点、`P_GEO_001` 两个交点）写成 `relation:"="` 的 claim，四轮里出现过 0–3 次，按“形状不支持”丢弃（`claim_dropped_unsupported`）；同一题两次生成的节点数/claim 数量会变，这是 `temperature=0` 不保证可重复的已知问题。**S5 第四阶段（2026-10-30）：生成图已接进 HTTP 主链路**——`TypeCueAligner`（存在性检查）+ `CompositeAligner` 按 `annotated_ids` 分发，缺节点按类型给先验（`NODE_TYPE_LAYER`/`FOCUS_PRIORS`），`build_diagnosis_card` 分标注/生成两支，`ProblemResolver` 未命中标注库就现场建图并存为 `annotated=False`。20 道未见题：建会话 20/20、出卡 7/20（其余按设计停在低置信收束）、**卡点节点 7/7 属于该图**；p50 5.4s、p95 35.9s（两次生成重试把尾巴拉长）（`eval/reports/m2.5-s5-session.md`）。

**2026-10-29 内容修正（重要）**：种子题 `P_FUNC_001` 的 `SAMPLE_ANSWER` 原写成 `a∈(-∞,0]∪[1/e,∞)`，但 `a≤0` 时 `f(x)=ln x - a x→+∞`，不满足恒成立；正确范围是 `a≥1/e`。已修正答案/参考解、n6 节点文本、`p_union` 的正确选项与证据方向、卡点卡 one-line、golden v0.1 的 g-001/g-004/g-005/g-006/g-009 标注（配额改为 3/3/2/2），并新增 `test_seed_math.py` 用 SymPy 直接验证答案。10 条 golden 仍 10/10、平均 2.40 轮。**教训**：关键词对齐的 golden 只能证明“步骤覆盖率”，不能证明数学正确；验证器必须能对形式化断言给出反例或证明。

**未实现**（不要以为已经有）：

| 能力 | 状态 |
|---|---|
| LLM 追问 | **有**：`infrastructure/llm/`（DeepSeek，默认 `off`）；T5「LLM 辅助对齐」未做且默认不做 |
| `shadow` 真实对照 | **已跑（2026-10-29，真实 key）**：10/10 不变，24/24 JSON 合法，p95 1.10s，0 重试 0 降级；细节见 `eval/reports/m2-exit-v0.1-shadow.md` 与 ADR-0002 §5.1 |
| 学科插件 / 解法图生成 | `SubjectPlugin` + `MathPlugin` 包装种子图（S1–S3）；识别为严格匹配（不同题交给建图器，识别不了且建不出图才 422）。**S4/S5 有生成器且已接进主链路**：`LLMGraphGenerator`（prompt → JSON → 机械修复 → 结构规则 → schema → 验证 → 一次重试）生成图、逐选项证据权重与可证伪 `claim`；`ProblemResolver` 未命中标注库就现场建图并登记为 `annotated=False`，通用对齐与通用卡点卡按图工作。第二学科属 S6 |
| RAG / 向量检索 | 无 |
| PostgreSQL / Redis / Alembic | 无；`InMemorySessionRepository` |
| OCR | 无；`image_url` 仅在 DTO 预留 |
| 鉴权 / 多租户 | 无 |
| worker 实际任务 | 无；`apps/worker` 只有说明 |
| 24h 迁移验证 / 教师复核 | 无 |

**已知硬边界**：入口的默认路径仍是「只有一道标注题」——`SYNAPSE_LLM_MODE=off`（默认）或缺少 key 时，非种子题依旧返回 **422**，这是显式设计，不是 bug。接上 key 后入口会现场建图（`ProblemResolver` + `MathPlugin.build_graph`），建图失败同样 422 并给出原因。**生成题的能力边界**：① 通用对齐（`TypeCueAligner`）只判断「这一步有没有被写到」，写错了发现不了；② 生成题没有存储答案，泄漏守卫退化为通用短语检查；③ 卡点卡的 `HYPOTHESES[*].node_id` 仍是种子专用，生成题的卡面从「探针 → 节点」反推节点。证据表 `EVIDENCE` 覆盖种子题的四个探针，实测只有 `H_L2` 能越过 `0.80 + 0.25`；`L1`/`L4` 案例按「低置信不硬判」收束（见 `eval/reports/m2-exit-v0.1.md`）。

---

## 二、必读顺序

1. [`specs/dialogue-state.md`](specs/dialogue-state.md) — 10 状态、转移、8 条硬约束。**任何改动先看它。**
2. [`README.md`](README.md) — 架构总览（九节，含决策记录）。
3. [`docs/design/chapters/12-M2交付计划.md`](docs/design/chapters/12-M2交付计划.md) — 下一步做什么、怎么验收。
4. [`docs/design/chapters/13-学科插件与可扩展架构.md`](docs/design/chapters/13-学科插件与可扩展架构.md) — 全学科怎么走。
5. [`docs/adr/0001-language-and-code-architecture.md`](docs/adr/0001-language-and-code-architecture.md) — 技术选型与改选条件。
6. [`docs/adr/0002-llm-provider-and-golden-scale.md`](docs/adr/0002-llm-provider-and-golden-scale.md) — 模型供应商与 golden 规模（已定：DeepSeek `deepseek-chat` / 10 条）。

**本地详尽版**（未入库，仅本机存在）：

- `docs/design/plan/M2-开发说明.md` — 含未决项与取舍记录
- `docs/design/plan/M2.5-学科插件与可扩展架构.md` — 含 `SubjectPlugin` 草案与 S1–S7
- `.tmp/m2-digest-main.md`、`.tmp/m2-digest-small.md` — 历史会话的提取与逐行引用（可追溯需求来源）

---

## 三、下一步（按优先级）

1. **M2 收尾**（T1–T4 + T6–T7 已完成，真实 shadow 已跑）：
   - 实测口径：JSON 合法 24/24、p95 1.10s、0 降级（ADR-0002 §5.1）；
   - `on:10` 灰度前仍需确认的是**首问整体** P95（现在是单次改写延迟，不含检索/状态推进）；
   - 请求 `deepseek-chat` 实际服务 id 是 `deepseek-flash`，冻结基线看审计里的 `model` 字段。
2. **M2.5**：第 13 章 S1–S7。S1/S2/S3 已完成（枚举扩到 `math`/`physics` + 三学段；`SubjectPlugin` + `MathPlugin`；识别从关键字换成「归一化包含」严格匹配，不同题返回 422）。
   - **S4 已完成（2026-10-29）**：`application/graph.py`（端口）+ `domain/problem/graph_structure.py`（结构规则/机械修复）+ `infrastructure/llm/graph.py`（生成 + spec 校验 + 一次重试 + 进程内缓存 + 指纹审计）。20 道未见题结构 20/20、人工抽查 19/20（95%）；0 重试 0 修复；p50 3.65s / p95 4.54s。报告：`eval/reports/m2.5-s4-graph-build.md`、`eval/reports/m2.5-s4-graph-review.md`。
   - **S4 暴露的两件事**：① 抽查唯一失败是 P_DERIV_003 漏 `a=0` 边界——**prompt 守不住数学边界**，S5 的验证器/反例必须补；② `temperature=0` 仍不可重复（同题两次 7/8 节点、指纹不同），缓存只保进程内，回归比对记录指纹。
   - **S5 第一阶段已完成（2026-10-29）**：证据表改为会话级数据——`HypothesisSet.from_alignment(..., evidence=...)`，`SessionFactory` 调 `SubjectPlugin.evidence_model()`；`EVIDENCE` 只作无插件时的默认。补齐 `p_union` 四个选项的权重（原来答了也不更新后验），契约测试保证种子题每个探针每个选项都有权重。10 条 golden 仍 10/10、平均 2.40 轮。
   - **S5 第二阶段已完成（2026-10-29）**：生成图新增 `Probe.evidence`（`选项 → 假设 → log-odds`），生成 prompt 升到 `graph-v2`。结构规则强制每个选项都有权重、权重键只能在该探针 `targets` 内、每个 target 至少被一个选项使用、权重有正有负（能区分假设）、钳制在 −1~1；`MathPlugin.evidence_model()` 优先读图内权重，只有已标注种子图回退 `EVIDENCE`，未知图返回空表。真实 20 题：结构 18/20（`P_DERIV_007`/`P_GEOM_001` 两次都无探针），68/68 探针、204/204 选项有权重且 68/68 有正负对比；4 次重试，2 次重试后通过、2 次因 `no_probes` 失败；p50 3.91s / p95 5.04s。`P_DERIV_003` 仍漏 `a=0`——**证据权重只保证「答了会更新后验」，不保证图的数学结论正确**。
   - **S5 第三阶段已完成（2026-10-29）：SymPy 验证器 + 反例。** 形式化字段按建议放在**图顶层** `claim`（`specs/solution-graph.schema.json` 的 `$defs/claim`）：`kind`（v1 只有 `parameter_range`）、`parameter`/`variable`（单字母小写）、`variable_domain`、`constraint{expression,relation}`、`answer[{lower,upper,lower_inclusive,upper_inclusive}]`，语义是 `∀x∈D: f(x,a) rel 0 ⇔ a∈answer`。`application/verification.py` 定义端口与 `pass|fail|unknown`，`infrastructure/verification/sympy_verifier.py` 做**反例搜索**：表达式走字符白名单 + `__builtins__` 置空的 SymPy 命名空间 + 自由符号白名单；x 取线性网格 + 12 个数量级 + 边界加密，参数在区间内外各取样（含端点本身），对最紧处做黄金分割细化；两个方向都查（区间内不满足 → 偏宽；区间外满足 → 偏窄）。`fail` 带 `a=…, x=…, 表达式=…` 的具体反例，回灌给模型重试一次；仍失败则**丢弃 claim、保留图**（`claim_dropped_refuted`），这是刻意的：`P_GEO_001` 这种“图对、claim 形式化错”的题不该整题报废，但答案也不能再被当作已核对。claim 的 kind/relation/符号冲突直接丢弃（`claim_dropped_unsupported`），不浪费重试。真实 20 题见上方状态；报告：`eval/reports/m2.5-s5-verification.md`（含变形自检与正向对照：同一题 `[0,E]` → pass、`(-∞,E]` → fail 带反例）。
   - **S5 第四阶段已完成（2026-10-30）：生成图接进 ALIGN/PROBE。** ① `TypeCueAligner` 按节点类型做**存在性**检查（线索词 / 是否写过式子 / 同一字母两侧分类 / 3-gram 兜底），`CompositeAligner` 按 `annotated_ids` 分发，`RuleBasedAligner` 一行未改；② 缺节点的**类型**决定先验（`NODE_TYPE_LAYER` + `FOCUS_PRIORS` + `from_alignment(focus=...)`），种子题没有 `focus` 时仍走原来的节点档案，10 条 golden 逐字节不变；③ `build_diagnosis_card` 分两支：标注题沿用旧文案，生成题引用「推动后验的那次作答」或只报「过程里没有出现这一步」，id 用 `node:{id}`/`verify:{problem_id}`；④ `ProblemResolver`：标注库严格命中 → 否则现场建图 → 存为 `annotated=False`（`P_GEN_<指纹>`，同题不重复生成），没有建图器或建图失败仍 422。实测：`scripts/eval/s5_session.py` 20 题建会话 20/20、出卡 7/20、卡点节点 7/7 属于该图，报告 `eval/reports/m2.5-s5-session.md`。出卡率低不是接线问题：生成图每题只有 3–7 个探针、权重 max|w|=0.60（|w|≥0.8 的 0 条），targets 又分散在不同假设对上，同一个 `0.80 + 0.25` 门槛很难在 6 轮里达到——**这属于 S5 ③ 的探针/权重校准**，不要靠调低门槛「修」。
   - **S5 ② 的边界（写进第 13 章）**：存在性对齐发现不了「写错」；生成题没有存储答案 → 泄漏守卫退化；首问预算现在含一次建图（p50 4–5s）。
   - **S5 剩余（下一步）**：③ 校准探针与权重：未见题出卡率只有 7/20，原因不是链路（建会话 20/20），而是生成图的探针太少（3–7 个）、权重太小（max|w|=0.60，无一条 ≥0.8）、targets 分散，`0.80 + 0.25` 在 6 轮里很难达到。可选做法：prompt 要求「权重用满 ±1 且同一探针的选项拉开差距」、要求每个假设层至少有一个探针、或给未见题单独标定门槛（后两者要写 ADR，别静默改）。④ 提高 claim 覆盖率：四轮里模型每次只对 `P_DERIV_003` 一题给出 claim（它也是这 20 题里唯一适合 v1 形状的题），但这题两次都写 `(-∞,e]`——验证器能拦，拦下之后模型没有第二次修正能力，得靠“端点必须代回检验”的 prompt 约束或第二轮回灌更强的提示。扩到 100 题评测集时把「claim 覆盖率」「推翻率」「出卡率」一起记。
   - **S6**：接第二个学科（物理），状态机零改动。
3. **待收口的既有问题**：前端无自动化测试（只有手工 smoke）；`docs/design/plan/` 未入库；评测集有 10 条、`eval/golden/README` 的 100 条配额未达（需 M2.5 扩题）。

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
mypy src
.\.venv\Scripts\lint-imports.exe         # 分层契约，CI 强制

# 前端
cd apps/web
npm run typecheck
npm run lint
npm run build

# 契约重新生成（DTO → OpenAPI → TS 类型）
python scripts/contracts/generate.py

# M2 退出判定（10 条 golden 回放，产出 eval/reports/m2-exit-v0.1.md）
cd apps/api
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py
# 真实模型双跑（key 放仓库根 .env，或导出 DEEPSEEK_API_KEY；结果不变，只多一份差异报告）
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py --live-shadow

# M2.5 S4 建图（20 道未见题；需真实 key；产出 eval/reports/m2.5-s4-graph-build.md）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py

# M2.5 S5 建图 + claim 反例验证（同 20 题；产出 eval/reports/m2.5-s5-verification.md 与 s5-graphs/）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_verify.py

# M2.5 S5 ② 请求链路（20 题现场建图 → 探针 → 卡点卡；产出 eval/reports/m2.5-s5-session.md）
# --policy aligned（默认）模拟“作答与对齐结论一致”，--policy first 一律选第一项作对照
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_session.py

# 仓库一致性（CI 第一个 job）
python scripts/checks/check_repo.py

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
| 章节链接不能指向 `plan/` | CI 的 `check_repo.py` 会解析相对链接，指向未入库文件 → 流水线红 |
| `release/` 产物需手动重建 | 改了章节不重建，DOCX/PDF 就是旧的（曾差一天） |
| Git 远端走 HTTPS + GCM | SSH 22/443 均不通；`git push` 无需交互 |
| `seed.py` 只有一道题 | 换题 422 是刻意边界，扩题属 M2.5 |
| `lint-imports.exe` 静默 exit 1 | 本机 exe 即使 `PYTHONPATH` 正确也可能静默失败（无输出）。先 `$env:PYTHONPATH=(Resolve-Path src).Path`，再 `.\.venv\Scripts\python.exe -c "from importlinter.cli import lint_imports_command; lint_imports_command()"`；通过时打印「Contracts: 1 kept」。CI 用 editable 安装，不受影响 |
| 新增 Python 依赖要重装 venv | `pyproject.toml` 加了 `jsonschema`（运行时）与 `types-jsonschema`（dev）；旧 venv 没有时会 ImportError。`pip install -e ".[dev]"` 一次补齐 |
| 根目录 `eval/` 在 `.gitignore` | 只忽略**根目录**的私有评测材料；`scripts/eval/` 是工具、必须入库（早先写成不带锚点的 `eval/`，把 `m2_exit.py` 一起吞了）。golden 数据仍需 `git add -f eval/golden/golden-v0.1.jsonl`，`eval/reports/` 是产物不入库 |
| CI 跑 `ruff format --check` | 只跑 `ruff check` 会在 CI 挂（format 与 check 是两套规则）；写完先 `ruff format src tests`。文件末尾缺换行也算未格式化 |
| 生成图 prompt 已升到 `graph-v3` | v2 起每个探针的每个选项都必须有 `evidence` 权重；v3 起可选 `claim`（参数区间）并把验证接进建图。旧图和旧报告没有 `claim`，比较时先看报告头部的 prompt 版本。schema 里 `probe.evidence` 与 `claim` 都是可选，「生成图必须有 evidence」由 `graph_structure.review(require_evidence=True)` 强制 |
| SymPy 没有 `py.typed` | `mypy src` 会报 `import-untyped`；`pyproject.toml` 里对 `sympy*` 开了 `ignore_missing_imports`（验证器把所有 SymPy 调用收在 float 边界的 helper 后面）。`sympy` 只在 `[dev]` extras 里，生产环境缺它时验证器返回 `unknown/unavailable`，不抛异常 |
| `claim` 是可丢弃的元数据 | 形状不支持（`kind`/`relation` 不在 v1、`parameter` 与 `variable` 同字母）→ 直接丢弃并记 `claim_dropped_unsupported`；反例推翻且重试后仍错 → 丢弃并记 `claim_dropped_refuted`。两种情况**图都保留**，`graph.claim` 变 `None`、反例留在 `GraphBuildResult.verification`。不要顺手把它改成建图失败，也别把丢弃当静默降级——修复码和审计里的 `verification_status` 都记着 |
| 模型会把探针放到顶层 | 观测到 `{"nodes":[...],"probes":[...]}` 的扁平化写法；探针没有归属节点，猜归属就是发明结构，所以判 `probes_top_level`（`schema_invalid`）并让重试带着提示改。prompt 第 1、12 条写死了「探针在节点内部」 |
| 验证是反例搜索，不是证明 | `pass` 只表示固定网格 + 黄金分割细化没找到反例；`unknown` 是没 claim / 读不懂 / 落在 1e-9 容差带。对外表述只能用「未发现反例」，不能写「已证明」 |
| `Probe.evidence` 的键是**选项字母** | `{"A": {"H_L2": 0.6}}`，与 `SubmitAnswerCommand.option_id` 同一套编码；写成选项文本不会报错——`HypothesisSet.observe()` 查不到就静默不更新后验，表现出来是「答了 6 轮置信度还在 0.45 附近」。评测脚本里犯过一次（`s5_session.py`），排查时先看 `session.hypotheses.evidence` |
| 生成题没有存储答案 | `InMemoryAnswerStore.answer_for()` 对 `P_GEN_*` 抛 `KeyError`，`AnswerStoreLeakGuardFactory` 捕获后退化为通用短语表（`guards.py` 里写明）。这意味着 n-gram 泄漏规则在生成题上**不生效**，只剩 prompt 约束与 `forbidden_token`；不要在报告里把它算成「泄漏守卫已覆盖」 |
| 通用对齐只查「有没有写」 | `TypeCueAligner` 是存在性检查：漏了能发现，写错了发现不了。卡面措辞因此只有两种——引用某次作答，或「过程里没有出现「…」这一步」。**不要**把它改成「这一步错了/理解偏了」，那是 `RuleBasedAligner` + 标注 golden 才支撑得起的断言 |
| 首问预算现在含一次建图 | 未见题走 `ProblemResolver` 会现场建图（p50 4–5s），首问 8s 预算的余量比标注库路径小；`on:10` 灰度要单独看这一支的 P95，不要把 M2 的 1.10s 改写延迟当整体口径 |

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
docs/adr/                    决策记录（改选条件）
docs/design/chapters/        设计书正文 00–14 + 附录（会被合并成 DOCX/PDF）
docs/design/plan/            本地详尽计划（未入库）
docs/design/release/         构建产物（未入库，需重建）
specs/                       机器可验证契约（JSON Schema + 状态机）
apps/api/                    后端：domain / application / infrastructure / api 分层
apps/web/                    前端：Next.js 15
eval/golden/                 M2 金标准 10 条（入库，需 `git add -f`）
eval/problems/               M2.5 S4 建图题 20 条（入库，需 `git add -f`）
eval/reports/                评测报告与生成图（产物，不入库）
```

---

## 八、历史背景（为什么长这样）

项目起点是"12 分钟测评 + 学习 OS"，在设计与评审中被判定跑偏，整体归档到 `_local/archive/v0-broad-os/`，转向**单题诊断引导**。因此仓库里有两代材料的痕迹：

- `_local/archive/v0-broad-os/` — 旧方案全文，**不要当现状引用**；
- 第 11 章记录的是当时的 Java/Spring 设计过程，**已被 ADR-0001 取代**，只作方法论留存；
- 旧会话里的 "M2 = 处方-验证闭环" 属于 v0 口径，与当前 M2（LLM 追问）无关。

当前 M2 / M2.5 的定义见第 12、13 章。

文档与计划按**范围与验收**表述，不写「几人几周」这类投入估算。