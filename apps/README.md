# apps

面向用户的运行单元。当前是**脚手架**，代码从 MVP 开始逐步填入。

| 目录 | 技术 | 职责 |
|---|---|---|
| [`web/`](web/README.md) | Next.js + TypeScript | 交题、追问、卡点卡、迁移验证、教师后台、SEO |
| [`api/`](api/README.md) | Python 3.12 + FastAPI | 状态机、会话、题目、诊断、知识、证据、AI 编排、SSE |
| [`worker/`](worker/README.md) | Python + Arq | OCR 后处理、知识 ETL、离线评测、红队 |

选型依据见 [ADR-0001](../docs/adr/0001-language-and-code-architecture.md)。

## 约定

- `apps/api` 是**模块化单体**，不按 7 个服务拆进程；边界在 Python 包与端口上。
- `apps/web` 只通过 `/api/v1/*` 访问后端，不直连数据库/向量库。
- `apps/worker` 不处理在线追问；在线编排在 `apps/api`。
- 跨应用契约的源放 [`../specs/`](../specs/)；生成的 TS 类型/客户端在 M1 放到 `apps/web/src/lib/api/`，不单独建空 `packages/`。

## 本地启动（目标形态）

```bash
# API
cd apps/api && uv sync && uv run fastapi dev src/synapse/api/main.py

# Web
cd apps/web && pnpm install && pnpm dev

# Worker（按需）
uv run --project apps/api arq synapse.workers.settings.WorkerSettings
```

> 以上命令是目标形态；当前仓库尚未提交可运行代码，先在 `specs/` 定契约，再按里程碑落地。