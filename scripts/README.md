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
├─ checks/
│  └─ check_repo.py      # 文件、链接、JSON、skill 映射检查
└─ release/
   └─ export_public.py   # 可选的公开树导出工具
```

## 检查

```bash
python scripts/checks/check_repo.py
```

检查内容：

- 根目录必需文件是否存在；
- `README.md` 与 `docs/` 下的相对链接/图片是否可解析；
- `specs/*.json` 是否为合法 JSON；
- `docs/design/chapters/08-skill映射.md` 是否有 11 条编号映射；
- 三张设计图是否存在。

## 一键启动

```powershell
python scripts/dev/run.py
# Windows 包装
.\scripts\dev\run.ps1
# 只检查环境
python scripts/dev/run.py --check
# 启动、确认健康、再自动停（用于验证）
python scripts/dev/run.py --smoke --no-install
```

## 导出 OpenAPI 与生成 TS 类型

需要先安装 API 依赖：

```powershell
python scripts/contracts/generate.py
```

它等价于：

```powershell
# 1. 用 API venv 导出 OpenAPI
apps\api\.venv\Scripts\python.exe scripts\contracts\export_openapi.py
# 2. 在 apps/web 生成 TS 类型
cd apps/web
npm run generate:api
```

生成物默认在 `.tmp/`（忽略）；`apps/web/src/lib/api/generated.ts` 入库，供 fresh clone 直接 typecheck/build。不要把它粘回 `specs/`；`specs/` 只放人写的契约源。

## 公开树（可选）

`scripts/release/export_public.py` 只在需要发布公开代码时使用；它不是日常开发步骤，也不会创建/推送任何远程仓库。