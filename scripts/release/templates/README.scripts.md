# scripts

仓库级脚本，不参与运行时。

```text
scripts/
├─ dev/
│  ├─ run.py             # 一键启动 API + Web
│  └─ run.ps1            # Windows 包装
├─ contracts/
│  ├─ generate.py        # OpenAPI -> generated.ts
│  └─ export_openapi.py  # 只导出 OpenAPI
└─ checks/
   └─ check_repo.py      # 必需文件、链接、JSON 检查
```

## 可选本地检查

CI 不运行文档完整性检查；需要排查时再手动执行：

```bash
python scripts/checks/check_repo.py
```

## 一键启动

```powershell
python scripts/dev/run.py
# 只检查环境
python scripts/dev/run.py --check
# 启动、确认健康、再自动停
python scripts/dev/run.py --smoke --no-install
```

## 导出 OpenAPI 与生成 TS 类型

需要先安装 API 依赖：

```powershell
python scripts/contracts/generate.py
```

它等价于：

```powershell
apps\api\.venv\Scripts\python.exe scripts\contracts\export_openapi.py
cd apps/web
npm run generate:api
```

生成的 OpenAPI 写到本地忽略目录；`apps/web/src/lib/api/generated.ts` 入库，供 fresh clone 直接 typecheck/build。不要把生成物粘回 `specs/`。