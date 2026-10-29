# AGENTS.md — 开发交接

> 本文件面向**接手开发的人或新会话**。对外文档是 [README.md](README.md)（只讲架构，不标进度）；进度、未决项、环境陷阱都记在这里。

---

## 一、当前状态（2026-10-29）

**M1 walking skeleton 可本地运行**：交题 → 解法图对齐 → 2 轮探针 → L2 卡点卡。规则版实现，内存仓储。

**未实现**（不要以为已经有）：

| 能力 | 状态 |
|---|---|
| LLM 追问 | 无；`ProbeComposer` 只有模板实现 |
| 学科插件 / 解法图生成 | 无；图写死在 `seed.py` |
| RAG / 向量检索 | 无 |
| PostgreSQL / Redis / Alembic | 无；`InMemorySessionRepository` |
| OCR | 无；`image_url` 仅在 DTO 预留 |
| 鉴权 / 多租户 | 无 |
| worker 实际任务 | 无；`apps/worker` 只有说明 |
| 24h 迁移验证 / 教师复核 | 无 |

**已知硬边界**：只支持一道种子题（函数与导数），换题返回 **422** —— 这是显式设计，不是 bug。

---

## 二、必读顺序

1. [`specs/dialogue-state.md`](specs/dialogue-state.md) — 10 状态、转移、8 条硬约束。**任何改动先看它。**
2. [`README.md`](README.md) — 架构总览（九节，含决策记录）。
3. [`docs/design/chapters/12-M2交付计划.md`](docs/design/chapters/12-M2交付计划.md) — 下一步做什么、怎么验收。
4. [`docs/design/chapters/13-学科插件与可扩展架构.md`](docs/design/chapters/13-学科插件与可扩展架构.md) — 全学科怎么走。
5. [`docs/adr/0001-language-and-code-architecture.md`](docs/adr/0001-language-and-code-architecture.md) — 技术选型与改选条件。

**本地详尽版**（未入库，仅本机存在）：

- `docs/design/plan/M2-开发说明.md` — 含未决项与取舍记录
- `docs/design/plan/M2.5-学科插件与可扩展架构.md` — 含 `SubjectPlugin` 草案与 S1–S7
- `.tmp/m2-digest-main.md`、`.tmp/m2-digest-small.md` — 历史会话的提取与逐行引用（可追溯需求来源）

---

## 三、下一步（按优先级）

1. **M2**：按第 12 章 T1–T4 + T6–T7 推进。开工前必须先定两件事——**模型供应商**、**金标准规模（10/100/200）**，否则工期待定。
2. **M2.5**：第 13 章 S1–S7。关键门槛是 S6（接第二个学科且状态机零改动）。
3. **待收口的既有问题**：前端无自动化测试（只有手工 smoke）；`docs/design/plan/` 未入库；评测集为空（`eval/golden/` 只有 README）。

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
mypy src
.\.venv\Scripts\lint-imports.exe         # 分层契约，CI 强制

# 前端
cd apps/web
npm run typecheck
npm run lint
npm run build

# 契约重新生成（DTO → OpenAPI → TS 类型）
python scripts/contracts/generate.py

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
eval/                        评测集（当前仅 README 占位）
```

---

## 八、历史背景（为什么长这样）

项目起点是"12 分钟测评 + 学习 OS"，在设计与评审中被判定跑偏，整体归档到 `_local/archive/v0-broad-os/`，转向**单题诊断引导**（3 人 / 8 周）。因此仓库里有两代材料的痕迹：

- `_local/archive/v0-broad-os/` — 旧方案全文，**不要当现状引用**；
- 第 11 章记录的是当时的 Java/Spring 设计过程，**已被 ADR-0001 取代**，只作方法论留存；
- 旧会话里的 "M2 = 处方-验证闭环" 属于 v0 口径，与当前 M2（LLM 追问）无关。

当前 M2 / M2.5 的定义见第 12、13 章。