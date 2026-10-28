# 仓库结构说明

这不是“最终版架构”，而是**当前这一版为什么这样放**的说明。原则只有一句：

> 目录按“运行时边界、契约源、验证、文档、工具”分，不按语言或文件类型分。

新增目录前先回答三个问题：**它有真实文件吗？有明确 owner 吗？有触发条件吗？** 三个都答不上来，就先不建。

## 一眼看懂

```text
.
├─ apps/                  # 能独立构建/部署的单元
│  ├─ web/               # Next.js：界面、SEO、SSE 外壳
│  ├─ api/               # FastAPI：状态机、诊断、AI 编排、SSE
│  └─ worker/            # Arq 部署入口；代码与 api 共用，不复制
├─ specs/                 # 契约源：状态机 + JSON Schema
├─ eval/                  # 怎么证明诊断是准的
│  ├─ golden/            # 双教师标注的黄金对话
│  └─ redteam/           # 诱导、边界、泄漏测试
├─ infra/                 # Compose / Nginx / 可观测性配置（M1 落）
├─ tools/                 # 文档生成与图，不是运行时依赖
├─ scripts/               # CI/本地检查，不是业务代码
├─ docs/
│  ├─ adr/               # 架构决策记录（为什么这样选）
│  ├─ design/
│  │  ├─ chapters/       # 第 0–12 章，唯一手写源
│  │  └─ assets/         # 3 张设计图，由脚本生成
│  └─ reference/         # 能力清单等原始参考
├─ .github/workflows/     # CI
├─ README.md              # 项目入口
├─ STRUCTURE.md           # 本文件
├─ CONTRIBUTING.md
└─ CHANGELOG.md
```

本地、**不上传**的：

```text
_local/                   # 旧版归档；不进 Git
docs/design/release/      # 合并 MD / DOCX / PDF；生成物，不进 Git
.tmp/                     # 临时检查脚本
```

## 每个目录放什么

| 目录 | 放这里 | 不放这里 | 当前有什么 |
|---|---|---|---|
| `apps/web/` | 页面、组件、RSC/ISR、SEO、SSE 客户端、BFF 透传 | 状态机、诊断规则、Prompt 编排、答案判定 | `app/`、`components/`、`src/lib/api/`、`package.json` |
| `apps/api/` | `domain`（纯函数）、`application`（用例/ports）、`infrastructure`（LLM/RAG/DB）、`api`（路由/SSE）、`workers`（任务） | 前端页面、文档生成、部署脚本 | `src/synapse/`、`tests/`、`pyproject.toml` |
| `apps/worker/` | 部署入口与任务说明；与 api 同镜像、不同 command | 第二份领域代码、第二套模型 | `README.md`；M2 起任务 |
| `specs/` | 状态机转移表、输入/解法图/诊断卡 JSON Schema | 生成的 TS 类型、运行时代码、草稿 | 1 个状态机文档 + 3 个 schema |
| `eval/golden/` | 黄金对话、双教师标注、评分 rubric | 真实学生隐私数据、生产日志 | `README.md`；完整 100 条本地/私有 |
| `eval/redteam/` | 诱导、越界、答案泄漏、提示注入用例 | 普通单元测试 | `README.md` |
| `infra/` | `compose.yaml`、Dockerfile、Nginx、OTel 配置 | 业务代码、前端组件 | `README.md`；M2 起容器文件 |
| `tools/` | `diagrams.py`、`merge_markdown.py`、`generate_docx.py`、TOC/PDF 脚本 | 运行时依赖、业务逻辑 | 5 个脚本 + `requirements.txt` |
| `scripts/` | `check_repo.py`、`dev.py`、`contracts.py` 等仓库级检查/启动/导出 | 应用入口、部署脚本 | 4 个脚本 + `README.md` |
| `docs/adr/` | 一个决策一个文件：背景、选项、评分、后果、改选条件 | 教程、会议记录、未决讨论 | `0001` 语言与代码架构 |
| `docs/design/chapters/` | 第 0–12 章 Markdown，按编号排序 | DOCX/PDF、合并稿、图片 | 13 个章节源文件 |
| `docs/design/assets/` | 由 `tools/diagrams.py` 生成的 3 张 PNG | 手工改图、截图堆 | 3 张图 |
| `docs/reference/` | 原始能力清单、外部资料摘要 | 正式设计正文 | `skill.txt` |
| `.github/workflows/` | CI：链接、JSON、skill 映射检查 | 本地脚本 | `ci.yml` |

## 三条最容易放错的边界

### 1. `apps/` 不是“语言目录”

- 正确：`apps/web`、`apps/api`、`apps/worker`
- 错误：`frontend/`、`backend/`、`java/`、`python/`

理由：换语言时目录不该重命名；能独立部署的单元才是边界。`apps/worker` 保留，是因为它是**第三个容器**，不是第二份代码。

### 2. `specs/` 是源，`apps/` 是消费者

改状态机或 JSON 字段的顺序：

```text
specs/ 改契约 → 改 apps/api 的 Pydantic/转移表 → 生成 TS 类型 → 跑 golden
```

不要把生成的 TypeScript 类型、OpenAPI JSON 贴回 `specs/`；`specs/` 只放人写得清、机器验得了的源。

### 3. `eval/` 不是 `tests/`

- `tests/` 证明“代码没坏”；
- `eval/` 证明“诊断说得准”。

所以 `eval/` 与 `docs/` 平级，不塞进 `apps/api/tests/`。完整 golden 数据可能含题目/答案，默认本地或私有；公开仓库只放格式说明和少量合成样例。

## 说明文档索引

| 想了解 | 看 |
|---|---|
| 项目定位与快速开始 | [README.md](README.md) |
| 为什么选 TS + Python、为什么不用 Go/Java | [docs/adr/0001-language-and-code-architecture.md](docs/adr/0001-language-and-code-architecture.md) |
| 应用怎么分工 | [apps/README.md](apps/README.md) |
| API 分层与约束 | [apps/api/README.md](apps/api/README.md) |
| Web 职责 | [apps/web/README.md](apps/web/README.md) |
| Worker 与 api 的关系 | [apps/worker/README.md](apps/worker/README.md) |
| 契约与 schema | [specs/README.md](specs/README.md) |
| 评测怎么组织 | [eval/README.md](eval/README.md) |
| 部署拓扑 | [infra/README.md](infra/README.md) |
| 文档怎么生成 | [tools/README.md](tools/README.md) |
| CI 检查什么 | [scripts/README.md](scripts/README.md) |
| 设计文档怎么读 | [docs/README.md](docs/README.md) |
| 设计章节源 | [docs/design/README.md](docs/design/README.md) |
| ADR 索引 | [docs/adr/README.md](docs/adr/README.md) |
| 能力清单原文 | [docs/reference/README.md](docs/reference/README.md) |

## 什么时候才加新目录

| 想加 | 先等到 |
|---|---|
| `services/` | 拆分触发条件满足：单模块周发布 >2 次且互相阻塞、资源画像差 >3 倍、故障域必须隔离、团队 >6 人、单库写入到分区阈值；至少满足两条 |
| `packages/contracts/` | 真的出现第二个消费方（Web 之外），再建生成物目录 |
| `infra/observability/` | 有第一条需要长期看的 SLO，而不是“先摆个 Prometheus” |
| `docs/design/release/` | 只在本地产出；如果要在仓库里放，先接受二进制 diff 与 5MB+ 体积 |
| `docs/archive/` | 不建；旧版放本地 `_local/archive/`，Git 历史足够追溯 |

## 命名约定

- 目录/文件：小写 + 短横线；中文文件名只用于设计章节，保持编号前缀。
- 章节：`NN-标题.md`，`NN` 两位；新增章节先改 `docs/design/README.md` 的阅读顺序。
- ADR：`NNNN-短标题.md`，编号递增，不覆盖旧决策；被取代时改状态并链接新 ADR。
- 图片：`NN-名称.png`，由 `tools/diagrams.py` 生成；不手工改 PNG。
- 生成物：`docs/design/release/` 下同名覆盖；不提交、不手改。

---

*维护规则：这份文件与目录一起改。目录变了但这里没改，视为文档缺陷。*