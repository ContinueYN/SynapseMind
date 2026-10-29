# 设计方案

本目录只放“产品与工程设计方案”，不放运行时代码。

```text
design/
├─ chapters/     # 第 0–14 章，唯一手写源
├─ release/      # 本地生成：合并 MD + DOCX + PDF（.gitignore）
└─ assets/       # 3 张设计图
```

## 版本

当前 **v0.2 · 单题诊断引导**；技术选型 v0.3 已由 [ADR-0001](../adr/0001-language-and-code-architecture.md) 更新为 **Next.js + TypeScript + Python/FastAPI + PostgreSQL/pgvector**。

> 第 7/8 章已按 ADR-0001 重写（v0.3）；本地 DOCX/PDF 已重生成但不入库；第 11 章保留旧 Java 设计过程，仅作方法记录。

- 入口：学生提交一道不会/做错的题 + 自己的答案/过程，或只说“完全不会”。
- 过程：解法图 → 步骤对齐 → 2–6 轮追问 → 卡点卡 → 3 分钟微干预 → 迁移验证。
- 边界：高中数学“函数与导数”，100 道种子题，30 道深标。
- 非目标：题库、AI 家教、12 分钟测评、智商测试、提分承诺。

## 结构约定

- **chapters 是源**：改文字、改表格、改示例都改这里。
- **release 是产物**：由脚本合并生成，不直接编辑，也不提交 Git；发布时放 Release。
- **assets 是图**：由 `tools/diagrams.py` 生成，不手工改 PNG。
- **图片引用**：章节里用 `../assets/xxx.png`；合并版里同样是 `../assets/xxx.png`。

## 重新生成

```bash
python -m pip install -r tools/requirements.txt
python tools/diagrams.py
python tools/merge_markdown.py
python tools/generate_docx.py
pwsh tools/update_toc_and_export.ps1   # Windows + Word
```

DOCX 的目录、页码、PDF 导出依赖 Word COM；没有 Word 时只能生成 DOCX 草稿，目录需在 Word 中按 F9 更新。

## 版本归档

旧版“12 分钟测评 + 学习 OS + 增长”方案在本地 `_local/archive/v0-broad-os/`，不上传、不再维护。