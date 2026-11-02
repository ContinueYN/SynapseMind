# infra

自托管 Docker Compose 栈：**nginx + Next.js web + FastAPI api + PostgreSQL 16 + Redis 7**。

定位：**单机多账号演示 / 作品集**。`SYNAPSE_AUTH=on` 时每个人自己注册、各自一个隔离工作区，模型 key 由用户自己填（BYOK，服务端加密保存）；仍不是集群、多租户 SaaS 或学校部署。这一层只承诺“一条命令能起、能看健康状态、能备份回滚”。

选型背景见 [ADR-0001](../docs/adr/0001-language-and-code-architecture.md)。

## 这套栈里有什么

| 服务 | 镜像 / 构建 | 端口 | 持久化 |
|---|---|---|---|
| `nginx` | `nginx:1.27-alpine` + `infra/nginx.conf` | 宿主 `:80`（可改） | — |
| `web` | `infra/Dockerfile.web`（Node 22，standalone `server.js`） | 仅内网 `:3000` | — |
| `api` | `infra/Dockerfile.api`（Python 3.12-slim，非 root） | 仅内网 `:8000` | `appdata` 挂 `/data` |
| `postgres` | `postgres:16-alpine` | 仅内网 `:5432` | `pgdata` |
| `redis` | `redis:7-alpine`（AOF） | 仅内网 `:6379` | `redisdata` |

- 只有 nginx 暴露宿主端口；`api` / `web` / `postgres` / `redis` 走 compose 内网。
- 四个服务（postgres / redis / api / web）都有 healthcheck，`api`、`web`、`nginx` 用 `depends_on: condition: service_healthy` 串起来。
- nginx 的 `/api/` 关闭 `proxy_buffering`，SSE 不会被缓冲；`client_max_body_size 2m`。
- **本栈没有 worker、没有 minio/对象存储、没有 pgvector、没有 TLS 终止。** 旧版本文档里写的 Arq worker 与对象存储不在这一片里。

## 快速开始

在**仓库根目录**执行（`-f infra/compose.yaml` 固定写在命令里，避免和别的 compose 文件混）：

```bash
cp infra/.env.example infra/.env      # 可选；不建 .env 也能用默认值起来
docker compose -f infra/compose.yaml up -d --build
docker compose -f infra/compose.yaml ps
```

验证：

```bash
curl http://localhost/api/v1/health          # {"status":"ok","version":"0.1.0"}
```

浏览器打开 <http://localhost>。`:80` 被占用时见下。

只需要校验配置、不启动容器（无 Docker daemon 也可）：

```bash
docker compose -f infra/compose.yaml config --quiet
```

`docker compose ... ps` 里五个服务都应是 `healthy`；`api` 的启动日志会先打印 `[entrypoint] database reachable ...`、再打印 Alembic 的 `Running upgrade -> 0001_auth ...` / `0002_session_rotation` / `0003_model_credentials`，最后才是 uvicorn。

`:80` 被占用时，在 `infra/.env` 里设 `SYNAPSE_HTTP_PORT=8080`，然后访问 `http://localhost:8080`。

首次 `up` 会拉取 postgres/redis/nginx 并构建两个自建镜像；改完代码要 `--build` 才会生效（`api` 镜像是 wheel 安装，不在容器里挂源码）。

## 环境变量

模板：`infra/.env.example`。所有键在 `infra/compose.yaml` 里都有同样的默认值，所以**不建 `.env` 也能起**。

| 变量 | 默认 | 说明 |
|---|---|---|
| `SYNAPSE_HTTP_PORT` | `80` | nginx 宿主端口 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `synapse` | 初始化 Postgres 用；改密码后旧 `pgdata` 不会自动跟着改 |
| `SYNAPSE_DATABASE_URL` | `postgresql+psycopg://synapse:synapse@postgres:5432/synapse` | auth 的 `users` / `auth_sessions` 表和 BYOK 的 `user_model_credentials` 表建在这里（Alembic）；诊断数据不在这里 |
| `SYNAPSE_REDIS_URL` | `redis://redis:6379/0` | `SYNAPSE_AUTH=on` 时 auth 会话 token 存 Redis；诊断链路还没用 Redis |
| `SYNAPSE_AUTH` | `on` | `on`：注册/登录/一次性会话 cookie 生效；`off`：回到匿名本地基线（不建 engine） |
| `SYNAPSE_AUTH_ALLOW_SIGNUP` | `on` | `on`：任何人都能注册（每人一个隔离工作区）；`off`：只有第一个账号能注册 |
| `SYNAPSE_COOKIE_SECURE` | `off` | 本地是 HTTP，`Secure` cookie 浏览器不会回传 |
| `SYNAPSE_BYOK` | `on` | 用登录用户自己保存的模型 key；`SYNAPSE_LLM_MODE` 仍需非 `off` 才会真的调用模型 |
| `SYNAPSE_CREDENTIAL_KEY` | 空 | 加密用户 key 的主密钥（Fernet）；**空 = 关闭 BYOK 存储**：设置页读写返回 503，`encryption_ready=false` |
| `SYNAPSE_SESSION_DB` | `/data/synapse.sqlite3` | **诊断会话仍落 SQLite**，在 `appdata` 卷上 |
| `SYNAPSE_REVIEW_DB` | `/data/review.sqlite3` | **复核队列仍落 SQLite**，同一个卷 |
| `SYNAPSE_WEB_ORIGINS` | `http://localhost,http://127.0.0.1` | API 的 CORS 白名单（同源调用时基本用不到） |
| `NEXT_PUBLIC_API_BASE` | 空 | 空 = 同源，浏览器请求 `/api/v1/...` 由 nginx 转给 api |
| `SYNAPSE_LLM_MODE` | `on` | 开着才可能调用模型；没有可用 key（用户或服务端）时仍走规则路径。`SYNAPSE_EXEC` / `SYNAPSE_RAG` 默认 `off`，保持确定性基线 |
| `SYNAPSE_CHC_ATTRIBUTION` | `on` | 卡面显示 7 个**题目需求标签**（CHC 维度），不是能力分；关掉则回到 v0.1 卡 |
| `DEEPSEEK_API_KEY` | 空 | 可选的服务端兜底 key：用户自己保存的 key 优先，没有保存的用户和匿名请求才用它 |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | **构建期**参数：pypi.org 慢/不通时指向镜像再 build api |

> `NEXT_PUBLIC_*` 是**构建期**内联的：改 `NEXT_PUBLIC_API_BASE` 必须 `docker compose -f infra/compose.yaml build web` 重新构建，改运行时环境变量不会生效。

## 多账号、BYOK 与一次性登录票据

**注册**：`SYNAPSE_AUTH_ALLOW_SIGNUP=on` 时 `/api/v1/auth/register` 对所有人开放；每个账号的会话、快照和模型 key 互相隔离（拿别人的 session id 只会得到 404）。设成 `off` 就回到旧策略：只有第一个账号能注册。

**主密钥**：`SYNAPSE_CREDENTIAL_KEY` 是加密所有用户模型 key 的 Fernet 主密钥。它为空时 BYOK 写入关闭（`PUT /api/v1/settings/model` 与 `/test` 返回 503），所以先设好再给用户用：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把输出写进 `infra/.env` 的 `SYNAPSE_CREDENTIAL_KEY=...`，然后重建/重启 api。`docker compose exec api env | grep SYNAPSE_CREDENTIAL_KEY` 可确认注入成功（不要把值贴进日志或 issue）。

- 换成另一个主密钥不会自动重加密：已保存的行会变成“无法解密”，设置页显示 `configured=false` + 警告，用户重新保存一次即可；**丢主密钥等于所有用户要重填 key**，这是刻意的（明文不落库）。
- 用户 key 只在调用模型时短暂解密，随请求结束丢弃；API 从不回传 key，只回传 `key_last4`。

**一次性登录票据**：登录/注册成功时，`synapse_session` 里放的是一次性登录票据（服务端只存哈希）；第一个受保护请求（`/auth/me`、`/api/v1/sessions/*` 或 `/api/v1/settings/*`）消费它并换发普通会话 cookie。之后同一个普通 cookie 反复使用，不再轮转，也不会因为并发认证请求被判成复用——标签页里正常并发请求是安全的。已经消费过的**登录票据**再次出现才会被判定为复用（可能是被窃取），服务端会撤销整条 token family 并让用户重新登录；普通会话只在 logout、过期或显式撤销时失效。`SYNAPSE_AUTH_SESSION_TTL_S` 是整条链的硬过期（默认 7 天）。

**诊断数据仍在 SQLite**：`/data/synapse.sqlite3` 存会话快照（含学生作答原文），`/data/review.sqlite3` 存复核队列；Postgres 只放账号、会话 token 的哈希和加密后的模型 key。

构建 api 时如果 PyPI 很慢或被挡（本机实测 pypi.org 只有 ~10 KB/s，换镜像后 40 秒装完），用镜像再 build：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  docker compose -f infra/compose.yaml build api
```

PowerShell：`$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"; docker compose -f infra/compose.yaml build api`。也可以把它写进 `infra/.env`。

## 数据库与迁移（Alembic）

容器启动顺序由 `infra/docker/api-entrypoint.sh` 负责：

1. 有 `SYNAPSE_DATABASE_URL` 就等 Postgres 的 host:port 可连（最多 60s，失败退出 1）；
2. **存在 `alembic.ini` 就执行 `alembic upgrade head`**；
3. `exec uvicorn synapse.api.main:app --host 0.0.0.0 --port 8000`。

第 2 步是**刻意宽容**的：本栈不重复创建迁移、不写 auth 代码；当前 `apps/api` 已经带 `alembic.ini`、`alembic/` 和 auth/BYOK 依赖，所以正常构建的镜像会直接跑到 `0003_model_credentials`。如果用的是 auth 落地前的旧镜像，启动日志会是：

```text
[entrypoint] no alembic.ini: skipping migrations (SQLite stores only)
```

那时 Postgres 是空的，API 只跑 SQLite 盘；重新构建 api 镜像即可（依赖从 `apps/api/pyproject.toml` 读，`psycopg`/`alembic`/`redis` 由那份依赖决定，本栈不另 pin 一份）。

手动跑迁移：

```bash
docker compose -f infra/compose.yaml exec api alembic upgrade head
docker compose -f infra/compose.yaml exec api alembic current
```

**数据没有迁移到 Postgres。** 现在 Postgres 承载账号相关表（`users`、`auth_sessions`、`user_model_credentials`）；诊断会话（`/data/synapse.sqlite3`）和复核队列（`/data/review.sqlite3`）仍然是 SQLite 文件。SQLite 的结构版本由应用自己的 `PRAGMA user_version` 管理，不是 Alembic；旧快照（v0.1）要用仓库里的 `scripts/dev/session_store.py migrate` 显式升级，这条 CLI 不在镜像里。

> auth 与 BYOK 的依赖（`sqlalchemy` / `alembic` / `psycopg` / `argon2-cffi` / `redis` / `cryptography`）和 `alembic.ini` / `alembic/` 由 `apps/api` 自己维护；本栈只从 `apps/api/pyproject.toml` 安装运行时依赖，并在镜像里存在 `alembic.ini` 时跑迁移。依赖有变动后**重建 api 镜像**即可（`docker compose -f infra/compose.yaml build api`），不要手写建表 SQL 或另建一套迁移。

## 备份

两个存储分开备，别只备一个。

**Postgres（auth 数据）**——`--file` 在容器内落盘再 `cp` 出来，避开 Windows PowerShell 重定向把二进制 dump 写坏：

```bash
docker compose -f infra/compose.yaml exec postgres pg_dump -U synapse -d synapse --format=custom --file=/tmp/synapse.dump
docker compose -f infra/compose.yaml cp postgres:/tmp/synapse.dump ./synapse-$(date +%F).dump
```

**SQLite（诊断 / 复核）**——用 `VACUUM INTO` 在 API 进程运行中拿一致快照（目标文件必须不存在）：

```bash
docker compose -f infra/compose.yaml exec -T api python -c "import sqlite3; sqlite3.connect('/data/synapse.sqlite3').execute(\"VACUUM INTO '/tmp/backup-synapse.sqlite3'\")"
docker compose -f infra/compose.yaml cp api:/tmp/backup-synapse.sqlite3 ./synapse-$(date +%F).sqlite3
```

**整个数据卷**（含两个 SQLite 文件；先停 api 再打包，别在写的时候拷卷）：

```bash
docker compose -f infra/compose.yaml stop api
docker run --rm -v synapse_appdata:/data -v "${PWD}:/backup" alpine tar czf /backup/appdata-$(date +%F).tgz -C /data .
docker compose -f infra/compose.yaml start api
```

卷名带项目名前缀（`name: synapse`）：`synapse_appdata`、`synapse_pgdata`、`synapse_redisdata`。

## 恢复

Postgres：

```bash
docker compose -f infra/compose.yaml stop api web
docker compose -f infra/compose.yaml cp ./synapse-2026-11-02.dump postgres:/tmp/restore.dump
docker compose -f infra/compose.yaml exec -T postgres pg_restore -U synapse -d synapse --clean --if-exists /tmp/restore.dump
docker compose -f infra/compose.yaml start api web
```

SQLite（先停 api，拷回去后把属主改回非 root 的 `10001`，否则 API 写不进去）：

```bash
docker compose -f infra/compose.yaml stop api
docker compose -f infra/compose.yaml cp ./synapse-2026-11-02.sqlite3 api:/data/synapse.sqlite3
docker compose -f infra/compose.yaml start api
docker compose -f infra/compose.yaml exec -u root api chown 10001:10001 /data/synapse.sqlite3
```

卷级恢复：`docker compose -f infra/compose.yaml down`（**不要加 `-v`**），把 `appdata-*.tgz` 解回卷，再 `up -d`。

## 回滚

- **代码**：镜像已经在 compose 里固定成 `synapse-api:local` / `synapse-web:local`。要回滚就重新构建并打 git sha 标签，再改 compose 的 `image:` 指向它：
  ```bash
  docker build -f infra/Dockerfile.api -t synapse-api:$(git rev-parse --short HEAD) .
  docker build -f infra/Dockerfile.web -t synapse-web:$(git rev-parse --short HEAD) .
  ```
  生产不要用 `latest`，用 sha。
- **数据**：Alembic 只往前；本栈**不自动跑 downgrade**。回滚数据一律走上面的备份恢复，不要手改表结构。
- **配置**：`.env` 不进仓库；改了 `NEXT_PUBLIC_API_BASE` 记得重建 web。

## 放到 VPS / 加 TLS

本地不终止 TLS，浏览器直接访问 `http://localhost`。要暴露到公网时：

1. 在 nginx 加 `listen 443 ssl;` 的 server 块（挂载证书/私钥，只读），80 端口只做跳转；或在前面再加一层 Caddy/Traefik 做终止。
2. `SYNAPSE_COOKIE_SECURE=on`（HTTPS 下才回传 Secure cookie）。
3. `SYNAPSE_WEB_ORIGINS` 加上真实 origin；如果 `NEXT_PUBLIC_API_BASE` 要改成绝对地址，**必须重建 web 镜像**。
4. 不要把 `/admin/review` 直接暴露公网：它目前和诊断接口共用同一套权限模型，没有独立的管理员鉴权。
5. 建议只开放 80/443，Postgres/Redis 不映射宿主端口（当前配置本来就没有映射）。

## 已知限制（known limits）

- **单机、单实例**：SQLite 仍是单写者；多副本时 API 的 revision CAS 只保证不丢更新，不保证吞吐。
- **没有完整 Postgres 迁移**：Postgres 目前只有账号、会话链和加密后的模型 key；诊断会话、复核队列、生成题仍是 `/data` 上的 SQLite 文件。
- **主密钥只有一把**：`SYNAPSE_CREDENTIAL_KEY` 同时加密所有用户的 key，不做轮换/多版本；换值后已保存的行无法解密（设置页显示未配置，用户重填即可），丢了也只能重填。没有 KMS 或硬件密钥。
- **只有登录票据是一次性的**：登录后的首个受保护请求消费票据并换发普通会话；普通会话可并发复用，不会因为并发被强制下线。复用已消费的登录票据才会撤销整条 token family。
- 没有 worker / 后台 TTL / 对象存储 / OCR / pgvector 检索；RAG 默认关，开了还会在容器里下模型（默认 `~/.cache`，重启即失）。
- 没有自动备份、监控、日志采集；`json-file` 日志按 10 MB × 3 轮转。
- healthcheck 用 `/api/v1/health`，并**故意把 401/403 当作存活**（auth 开启时会话路由会要求登录）；这只证明进程在服务，不证明鉴权配置正确。
- 镜像按 `apps/api/pyproject.toml` 的运行时依赖构建；依赖变动（含 `cryptography`）后必须重建，否则 entrypoint 会因为 `alembic.ini` 在而 `alembic` 不在而报错退出（这是刻意的显式失败，不是静默跳过）。
- `.dockerignore` 排除了 `apps/api/var/`、`var/`、`.env`：本地 SQLite（学生文本）和密钥不会进镜像层。

## 与 auth/Alembic 的契约

- 本栈只消费约定好的环境变量（`SYNAPSE_DATABASE_URL` / `SYNAPSE_REDIS_URL` / `SYNAPSE_AUTH` / `SYNAPSE_AUTH_ALLOW_SIGNUP` / `SYNAPSE_COOKIE_SECURE` / `SYNAPSE_BYOK` / `SYNAPSE_CREDENTIAL_KEY` / `SYNAPSE_SESSION_DB` / `SYNAPSE_REVIEW_DB`），不实现登录、不建迁移、不碰 `apps/api` 业务代码；登录/迁移/加密代码在 `apps/api` 自己那侧。
- 迁移只认 `apps/api/alembic.ini`（镜像 `WORKDIR /app`）。如果那边把 ini 放到别处或改了命令名，需要同步 `infra/docker/api-entrypoint.sh`。
- 浏览器默认同源（`NEXT_PUBLIC_API_BASE` 为空），cookie 会跟着 `/api/` 请求走；如果 auth 改成跨域，除了 `SYNAPSE_WEB_ORIGINS`，还要给 API 的 CORS 打开 `allow_credentials`，那属于 `apps/api` 的改动。