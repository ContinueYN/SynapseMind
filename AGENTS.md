# AGENTS.md — 开发交接

> 本文件面向**接手开发的人或新会话**。对外文档是 [README.md](README.md)（只讲架构，不标进度）；进度、未决项、环境陷阱都记在这里。

---

## 一、当前状态（2026-10-29）

**M1 walking skeleton 可本地运行**：交题 → 解法图对齐 → 2 轮探针 → L2 卡点卡。规则版实现，内存仓储。

**M2（窄口径）已落地**：`infrastructure/llm` + `LLMProbeComposer` + 校验/重试/降级 + `shadow` 双跑 + 10 条 golden 回放与退出判定报告。默认 `SYNAPSE_LLM_MODE=off`，部署形态与 M1 相同（内存仓储、无队列）。

**未实现**（不要以为已经有）：

| 能力 | 状态 |
|---|---|
| LLM 追问 | **有**：`infrastructure/llm/`（DeepSeek，默认 `off`）；T5「LLM 辅助对齐」未做且默认不做 |
| `shadow` 真实对照 | **已跑（2026-10-29，真实 key）**：10/10 不变，24/24 JSON 合法，p95 1.10s，0 重试 0 降级；细节见 `eval/reports/m2-exit-v0.1-shadow.md` 与 ADR-0002 §5.1 |
| 学科插件 / 解法图生成 | **骨架有**：`SubjectPlugin` 端口 + `MathPlugin` 包装种子图（M2.5 S1/S2）；图仍手写，**生成属 S4**，第二学科属 S6 |
| RAG / 向量检索 | 无 |
| PostgreSQL / Redis / Alembic | 无；`InMemorySessionRepository` |
| OCR | 无；`image_url` 仅在 DTO 预留 |
| 鉴权 / 多租户 | 无 |
| worker 实际任务 | 无；`apps/worker` 只有说明 |
| 24h 迁移验证 / 教师复核 | 无 |

**已知硬边界**：只支持一道种子题（函数与导数），换题返回 **422** —— 这是显式设计，不是 bug。证据表 `EVIDENCE` 只覆盖三个探针，实测只有 `H_L2` 能越过 `0.80 + 0.25`；`L1`/`L4` 案例按「低置信不硬判」收束（见 `eval/reports/m2-exit-v0.1.md`）。

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
2. **M2.5**：第 13 章 S1–S7。S1/S2 已完成（枚举扩到 `math`/`physics` + 三学段；`SubjectPlugin` + `MathPlugin`，行为不变，语义仍是「只服务一道种子题」）。下一步：
   - **S3** 把识别彻底移到插件（`find_for` 里已无关键字逻辑，剩下的是给 `physics` 补 handler）；
   - **S4** 建图生成 + schema 校验 + 修复重试（20 道未见题 ≥80%）；
   - **S5** 证据表由插件提供，补上 `p_union` 缺权重与「平均 2.4 轮饱和」两处标定问题。
   - 关键门槛仍是 S6（接第二个学科且状态机零改动）。
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
# 真实模型双跑（需 DEEPSEEK_API_KEY；结果不变，只多一份差异报告）
$env:SYNAPSE_LLM_MODE = "shadow"; .\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py

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
| `lint-imports.exe` 静默 exit 1 | venv 里没有 editable 安装的 `synapse`，先 `$env:PYTHONPATH="src"`（或 `pip install -e .`）再跑；契约通过时应打印「Contracts: 1 kept」 |
| `eval/` 整体在 `.gitignore` | golden 数据必须 `git add -f eval/golden/golden-v0.1.jsonl`，否则新克隆/CI 没有 case（`eval/golden/README.md` 被跟踪是历史遗留）；`eval/reports/` 是产物，不入库 |
| CI 跑 `ruff format --check` | 只跑 `ruff check` 会在 CI 挂（format 与 check 是两套规则）；写完先 `ruff format src tests`。文件末尾缺换行也算未格式化 |

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
docs/design/chapters/        设计书正文 00–13 + 附录（会被合并成 DOCX/PDF）
docs/design/plan/            本地详尽计划（未入库）
docs/design/release/         构建产物（未入库，需重建）
specs/                       机器可验证契约（JSON Schema + 状态机）
apps/api/                    后端：domain / application / infrastructure / api 分层
apps/web/                    前端：Next.js 15
eval/golden/                 M2 金标准 10 条（入库，需 `git add -f`）
eval/reports/                退出判定报告（产物，不入库）
```

---

## 八、历史背景（为什么长这样）

项目起点是"12 分钟测评 + 学习 OS"，在设计与评审中被判定跑偏，整体归档到 `_local/archive/v0-broad-os/`，转向**单题诊断引导**（3 人 / 8 周）。因此仓库里有两代材料的痕迹：

- `_local/archive/v0-broad-os/` — 旧方案全文，**不要当现状引用**；
- 第 11 章记录的是当时的 Java/Spring 设计过程，**已被 ADR-0001 取代**，只作方法论留存；
- 旧会话里的 "M2 = 处方-验证闭环" 属于 v0 口径，与当前 M2（LLM 追问）无关。

当前 M2 / M2.5 的定义见第 12、13 章。