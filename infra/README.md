# infra

部署与运维。MVP 只保留“能一键起、能看一条 trace、能回滚”的最小集。

选型见 [ADR-0001](../docs/adr/0001-language-and-code-architecture.md)：**3 个容器、1 个 Postgres、1 个 Redis**，不引 K8s/Spring Cloud/MySQL。

## 目录

| 目录 | 内容 |
|---|---|
| [`docker/`](docker/README.md) | `docker-compose.yml`、Dockerfile、Nginx 配置 |
| `observability/` | Prometheus 规则、Grafana 大盘 JSON、OTel 配置 |
| `serverless/` | OCR/PDF 导出的 FC 配置（可选） |
| `k8s/` | **Phase 2 再建**，MVP 不引入 |

## MVP 拓扑

```text
Browser
  │
Nginx（SSE 关闭缓冲、限流）
  ├─ web（Next.js：RSC/ISR、SSE 外壳）
  └─ api（FastAPI：状态机/诊断/AI/SSE）
        │
        ├─ worker（Arq：OCR 后处理/ETL/评测）
        ├─ PostgreSQL 16 + pgvector（业务 + 知识卡）
        ├─ Redis 7（会话/幂等/限流/SSE 重放）
        └─ 对象存储（题目原图，7 天生命周期）
```

## 约定

- 所有服务只暴露内网端口；只有 Nginx 对外。
- 健康检查分 `/health/live` 与 `/health/ready`。
- 配置走环境变量，密钥不进仓库；提交 `.env.example`。
- `api` 与 `worker` 共用同一镜像、不同 command；不为 worker 单独维护一套代码。
- 回滚：镜像 tag + Alembic 向前兼容；不做自动 down migration。
- 不把 `latest` 当生产 tag；用 git sha。

## 本地

```bash
cd infra/docker
cp .env.example .env
docker compose up -d
```

> 当前只有说明与占位；Compose 文件在 M1 提交。