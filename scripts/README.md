# scripts

仓库级脚本，不参与运行时。

| 脚本 | 用途 |
|---|---|
| `check_repo.py` | CI/本地检查：必需文件、Markdown 链接、JSON 可解析、11 项 skill 映射 |
| `export_openapi.py` | 从 FastAPI `create_app()` 导出 OpenAPI；默认写到本地忽略的 `docs/design/release/openapi.json` |
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

## 导出 OpenAPI

需要先安装 API 依赖：

```powershell
cd apps/api
.\.venv\Scripts\Activate.ps1
python ..\..\scripts\export_openapi.py
# 指定输出位置
python ..\..\scripts\export_openapi.py --out ..\..\.tmp\openapi.json
```

生成物默认在 `docs/design/release/`，该目录被 `.gitignore` 忽略；不要把它粘回 `specs/`。`specs/` 只放人写的契约源。

不检查 Word/PDF 的版式；版式用 `tools/update_toc_and_export.ps1` 后人工抽查。