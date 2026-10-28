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

## 服务

| 服务 | 端口 | 说明 |
|---|---|---|
| `nginx` | 8080 | 唯一入口；SSE 关闭 `proxy_buffering` |
| `api` | 8081 | Spring Boot，4 个部署单元可先合一个进程 |
| `web` | 3000 | Next.js |
| `mysql` | 3306 | 14 张核心表 |
| `redis` | 6379 | 会话/缓存/锁 |
| `postgres` | 5432 | pgvector，知识卡 |
| `minio` | 9000 | 题目原图，7 天生命周期 |

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
- MySQL/Postgres 数据卷命名，不随 `down` 删除。
- 健康检查失败要能自动重启，但不做无限重启风暴。
- `.env` 不入库；`.env.example` 只放占位值。