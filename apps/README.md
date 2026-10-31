# apps

面向用户的运行单元。M1 的 `web` 与 `api` 已可本地运行；`worker` 仍只有设计说明。

| 目录 | 技术 | 职责 | 当前状态 |
|---|---|---|---|
| [`web/`](web/README.md) | Next.js 15 + TypeScript | 交题、追问、卡点卡 | M1 可运行 |
| [`api/`](api/README.md) | Python 3.12 + FastAPI | 状态机、会话、题目、诊断、答案防护 | M1 可运行 |
| [`worker/`](worker/README.md) | Python + Arq | OCR 后处理、知识 ETL、离线评测、红队 | 设计；M2 落地 |

选型依据见 [ADR-0001](../docs/adr/0001-language-and-code-architecture.md)。

## 约定

- `apps/api` 是**模块化单体**，不按 7 个服务拆进程；边界在 Python 包与端口上。
- `apps/web` 只通过 `/api/v1/*` 访问后端，不直连数据库/向量库。
- `apps/worker` 不处理在线追问；在线编排在 `apps/api`。
- 跨应用契约的源放 [`../specs/`](../specs/)；手写 TS 类型放 `apps/web/src/lib/api/`，不单独建空 `packages/`。
- 生成物（OpenAPI、截图、DOCX/PDF）不进 `specs/`；本地放 `.tmp/`，已被 `.gitignore` 忽略。

## 本地启动

在仓库根目录一条命令启动 API + Web（首次自动建 venv/装依赖）：

```powershell
python scripts/dev/run.py
# 或 .\scripts\dev\run.ps1
```

只检查环境：`python scripts/dev/run.py --check`。手动启动：

```powershell
# API（Python 3.12+）
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn --app-dir src synapse.api.main:app --reload --port 8000
```

```powershell
# Web（Node.js 22+）
cd apps/web
npm install
npm run dev
```

```powershell
# Worker（M2；尚未实现）
# 与 api 共用同一个 synapse 包与镜像，只换启动命令
uv run --project apps/api arq synapse.workers.settings.WorkerSettings
```

> 当前只跑文本链路；拍照 OCR、LLM 生成、RAG、PostgreSQL/Redis 与鉴权在 M2/M3。本地可用 SQLite 会话快照（`SYNAPSE_SESSION_DB`，`run.py` 默认开启），但它不是 PostgreSQL 替代品。不要为“看起来完整”提前加空服务或第二份领域模型。