# apps

面向用户的运行单元。当前是**脚手架**，代码从 MVP 开始逐步填入。

| 目录 | 技术 | 职责 |
|---|---|---|
| [`api/`](api/README.md) | Java 21 + Spring Boot 3 | 网关、会话、题目、诊断、知识、证据、AI 编排 |
| [`web/`](web/README.md) | Next.js + TypeScript | 交题、追问、卡点卡、迁移验证、教师后台 |
| [`ai-worker/`](ai-worker/README.md) | Python | OCR 后处理、知识 ETL、离线评测、批量标注 |

## 约定

- `apps/api` 先做**模块化单体**，不按 7 个服务拆进程；边界在包和接口上。
- `apps/web` 只通过 `/api/v1/*` 访问后端，不直连数据库/向量库。
- `apps/ai-worker` 不处理在线追问；在线编排在 `api` 的 `ai` 模块。
- 跨应用契约放 [`../specs/`](../specs/) 与 [`../packages/contracts/`](../packages/contracts/)。

## 本地启动（目标形态）

```bash
# API
cd apps/api && ./mvnw spring-boot:run

# Web
cd apps/web && pnpm install && pnpm dev

# Worker（按需）
cd apps/ai-worker && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

> 以上命令是目标形态；当前仓库尚未提交可运行代码，先在 `specs/` 定契约，再按里程碑落地。