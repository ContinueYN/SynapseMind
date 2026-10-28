# scripts

仓库级脚本，不参与运行时。

| 脚本 | 用途 |
|---|---|
| `check_repo.py` | CI/本地检查：必需文件、Markdown 链接、JSON 可解析 |
| `dev.py` | 一键启动 API + Web；首次建 venv/装依赖；`--check` 只检查，`--smoke` 启动后自动停 |
| `dev.ps1` | Windows 包装：`.\scripts\dev.ps1` |
| `contracts.py` | 导出 OpenAPI 并生成 `apps/web/src/lib/api/generated.ts` |
| `export_openapi.py` | 只导出 OpenAPI 到本地忽略目录 |

## 检查

```bash
python scripts/check_repo.py
```

## 一键启动

```powershell
python scripts/dev.py
# 只检查环境
python scripts/dev.py --check
# 启动、确认健康、再自动停
python scripts/dev.py --smoke --no-install
```

## 导出 OpenAPI 与生成 TS 类型

需要先安装 API 依赖：

```powershell
python scripts/contracts.py
```

它等价于：

```powershell
apps\api\.venv\Scripts\python.exe scripts\export_openapi.py
cd apps/web
npm run generate:api
```

生成的 OpenAPI 写到本地忽略目录；`apps/web/src/lib/api/generated.ts` 入库，供 fresh clone 直接 typecheck/build。不要把生成物粘回 `specs/`。