# scripts

仓库级脚本，不参与运行时。

| 脚本 | 用途 |
|---|---|
| `check_repo.py` | CI/本地检查：必需文件、Markdown 链接、JSON 可解析、11 项 skill 映射 |
| `dev.py` | 一键启动 API + Web；首次建 venv/装依赖；`--check` 只检查，`--smoke` 启动后自动停 |
| `dev.ps1` | Windows 包装：`.\scripts\dev.ps1` |
| `contracts.py` | 导出 OpenAPI 并生成 `apps/web/src/lib/api/generated.ts` |
| `export_openapi.py` | 只导出 OpenAPI；默认写到本地忽略的 `docs/design/release/openapi.json` |
| `new_chapter.py` | **待加**：新建章节并自动编号 |
| `serve_docs.sh` | **待加**：本地预览 Markdown |

## 检查

```bash
python scripts/check_repo.py
```

检查内容：

- 根目录必需文件是否存在；
- `README.md` 与 `docs/` 下的相对链接/图片是否可解析；
- `specs/*.json` 是否为合法 JSON；
- `docs/design/chapters/08-skill映射.md` 是否有 11 条编号映射；
- 三张设计图是否存在。

## 一键启动

```powershell
python scripts/dev.py
# 只检查环境
python scripts/dev.py --check
# 启动、确认健康、再自动停（用于验证）
python scripts/dev.py --smoke --no-install
```

## 导出 OpenAPI 与生成 TS 类型

需要先安装 API 依赖：

```powershell
python scripts/contracts.py
```

它等价于：

```powershell
# 1. 用 API venv 导出 OpenAPI
apps\api\.venv\Scripts\python.exe scripts\export_openapi.py
# 2. 在 apps/web 生成 TS 类型
cd apps/web
npm run generate:api
```

生成物默认在 `docs/design/release/`（忽略）；`apps/web/src/lib/api/generated.ts` 入库，供 fresh clone 直接 typecheck/build。不要把它粘回 `specs/`；`specs/` 只放人写的契约源。

不检查 Word/PDF 的版式；版式用 `tools/update_toc_and_export.ps1` 后人工抽查。