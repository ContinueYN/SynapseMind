# tools

文档构建工具。不是运行时依赖。

| 文件 | 用途 |
|---|---|
| `diagrams.py` | 用 Pillow 生成 3 张设计图（2400×1400 / 2600×1600） |
| `merge_markdown.py` | 把 `docs/design/chapters/*.md` 合并成 `release/` 的 Markdown |
| `generate_docx.py` | 读取合并后的 Markdown，生成带封面、目录域、页眉页脚的 DOCX |
| `update_toc_and_export.ps1` | Windows + Word：更新目录页码、套 TOC 样式、导出 PDF |
| `requirements.txt` | `python-docx`、`Pillow` |

## 构建

```bash
python -m pip install -r tools/requirements.txt
python tools/diagrams.py
python tools/merge_markdown.py
python tools/generate_docx.py
pwsh tools/update_toc_and_export.ps1
```

## 说明

- **章节是唯一源**：`merge_markdown.py` 按文件名顺序合并 `docs/design/chapters/*.md`（当前 00–15，不写死编号——加了新章节也不用改这句）；不要直接改 `release/` 的 Markdown。
- `generate_docx.py` 读取合并后的 Markdown，图片按该文件所在目录解析（`../assets/...`）。
- DOCX 的目录是 Word 域；首次打开需更新域，或直接跑 PowerShell 脚本。
- PDF 导出依赖 Word COM；Linux/CI 只能生成 DOCX 草稿，不能导出同版式 PDF。
- 脚本会覆盖 `release/` 下同名产物；不要手改生成物。

## 换字体

`diagrams.py` 默认用 Windows 的 `msyh.ttc` / `msyhbd.ttc`。换平台时改 `FONT_DIR`，或把字体文件放进 `docs/design/assets/fonts/` 并改路径。