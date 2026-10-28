# infra

部署与运维。MVP 只保留“能一键起、能看一条 trace、能回滚”的最小集。

## 目录

| 目录 | 内容 |
|---|---|
| [`docker/`](docker/README.md) | `docker-compose.yml`、Dockerfile、Nginx 配置 |
| `observability/` | Prometheus 规则、Grafana 大盘 JSON、OTel 配置 |
| `serverless/` | OCR/PDF 导出的 FC 配置 |
| `k8s/` | **Phase 2 再建**，MVP 不引入 |

## MVP 拓扑

```text
Browser
  │
Nginx（SSE 关闭缓冲、限流）
  │
gateway（Spring Cloud Gateway）
  ├─ core（session/problem/diagnosis/evidence）
  ├─ ai（parser/coach/verifier）
  └─ content（knowledge/admin）
        │
MySQL 8 · Redis 7 · PostgreSQL 16 + pgvector · 对象存储
```

## 约定

- 所有服务只暴露内网端口；只有 Nginx 对外。
- 健康检查分 `/health/live` 与 `/health/ready`。
- 配置走环境变量，密钥不进仓库；提交 `.env.example`。
- 每个部署单元一个 Dockerfile；镜像 <250MB（JRE 基础镜像 + 分层）。
- 回滚：镜像 tag + Flyway 向前兼容；不做自动 down migration。

## 本地

```bash
cd infra/docker
cp .env.example .env
docker compose up -d
```

> 当前只有说明与占位；Compose 文件在 M1 提交。