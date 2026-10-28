# infra/docker

MVP 的本地一键起。目标：3 条命令内看到“交题 → 追问 → 卡点卡”。

## 计划文件

```text
docker/
├─ docker-compose.yml
├─ .env.example
├─ nginx/
│  └─ nginx.conf
├─ api/
│  └─ Dockerfile
├─ web/
│  └─ Dockerfile
└─ worker/
   └─ Dockerfile
```

`api` 与 `worker` 可以共用 `api` 镜像，用不同 command 启动；`worker/Dockerfile` 仅当依赖差异明显时再拆。

## 服务

| 服务 | 端口 | 说明 |
|---|---|---|
| `nginx` | 8080 | 唯一入口；SSE 关闭 `proxy_buffering` |
| `web` | 3000 | Next.js（RSC/ISR、SSE 外壳） |
| `api` | 8081 | FastAPI，模块化单体 |
| `worker` | — | Arq，离线任务，不暴露端口 |
| `postgres` | 5432 | PostgreSQL 16 + pgvector，业务 + 知识卡 |
| `redis` | 6379 | 会话/缓存/幂等/限流/SSE 重放 |
| `minio` | 9000 | 题目原图，7 天生命周期 |

**没有 MySQL**：业务与向量统一在 PostgreSQL，避免双库事务与双份备份。

## Nginx 关键配置

```nginx
location /api/ {
    proxy_pass http://api:8081;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;          # SSE 必须
    proxy_read_timeout 120s;
    client_max_body_size 10m;
}
```

## 约定

- 不把 `latest` 当生产 tag；用 git sha。
- Postgres 数据卷命名，不随 `down` 删除。
- 健康检查失败要能自动重启，但不做无限重启风暴。
- `.env` 不入库；`.env.example` 只放占位值。