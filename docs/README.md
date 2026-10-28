# 文档

> 仓库级目录说明见 [STRUCTURE.md](../STRUCTURE.md)。

| 目录 | 内容 |
|---|---|
| [`adr/`](adr/README.md) | 架构决策记录；[0001 语言与代码架构](adr/0001-language-and-code-architecture.md) 是技术选型的准绳 |
| [`design/`](design/README.md) | 产品与工程设计方案：分章 Markdown、三张图；DOCX/PDF 本地生成 |
| [`design/chapters/`](design/chapters/) | 第 0–12 章源文件，改内容从这里改 |
| `design/release/` | **本地生成，不入库**；DOCX/PDF 发布时作为 Release 附件 |
| [`design/assets/`](design/assets/) | 单题闭环图、诊断引擎图、技术架构图；由 `tools/diagrams.py` 生成 |
| [`reference/skill.txt`](reference/skill.txt) | 能力清单原文，第 8 章逐条映射的依据 |

## 阅读顺序

1. [一页纸](design/chapters/00-一页纸.md)
2. [核心体验](design/chapters/02-核心体验.md)
3. [诊断引擎](design/chapters/04-诊断引擎.md)
4. [Prompt 与 Agent](design/chapters/05-Prompt与Agent.md)
5. [RAG 与内容](design/chapters/06-RAG与内容.md)
6. [语言与代码架构 ADR](adr/0001-language-and-code-architecture.md)（技术选型先看这篇）
7. [技术架构](design/chapters/07-技术架构.md)（v0.3：Next.js + Python/FastAPI + PostgreSQL/pgvector，3 容器）
8. [skill.txt 映射](design/chapters/08-skill映射.md)
9. [可行性与 MVP](design/chapters/09-可行性与MVP.md)

## 构建文档

```bash
python -m pip install -r tools/requirements.txt
python tools/diagrams.py
python tools/merge_markdown.py
python tools/generate_docx.py
# Windows + Word 环境：更新目录并导出 PDF
pwsh tools/update_toc_and_export.ps1
```

> 生成脚本会覆盖 `design/release/` 下的同名文件；该目录已忽略、不入库。改稿请改 `design/chapters/`，不要直接改 DOCX。