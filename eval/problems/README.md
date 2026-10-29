# eval/problems

M2.5 S4 建图评测集。**v0.1 共 20 条**：`unseen-v0.1.jsonl`，JSONL 一行一题。

> `eval/` 整体在 `.gitignore` 内。本目录的文件需要 `git add -f`，否则新克隆与 CI 都没有题。

## 用途

衡量 `build_graph()` 的建图成功率（第 13 章 §13.7 S4：20 道未见题 ≥80%）。这里只有**题干**，没有答案、没有过程、没有人工解法图——建图器必须自己拆解。

- 题目覆盖高中常见的函数/导数、数列、三角、立体几何、解析几何、概率、向量、复数、不等式；不是种子题的变体。
- 题目集不参与 prompt 调参：若发现系统性失败，只修 prompt 的通用规则，并在报告里记录版本与改动。
- 判断标准见 `scripts/eval/s4_graph_build.py`：结构合法（schema + 依赖/探针规则）且人工抽查通过；抽查不通过的题不计入成功率。

## 字段

| 字段 | 说明 |
|---|---|
| `id` | 题目 id，必须匹配 `^P_[A-Z0-9_]+$`（图契约要求） |
| `subject` / `grade` | 学科与学段，当前只用 `math` / `high_school` |
| `topic` | 主题标签，进报告，方便看哪类题失败 |
| `text` | 题干原文；学生提交的题面应大致等于它 |

## 运行

```powershell
cd apps/api
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py
```

需要仓库根 `.env` 里的 `DEEPSEEK_API_KEY`（或环境变量）。报告写入 `eval/reports/m2.5-s4-graph-build.md`，逐题图写入 `eval/reports/s4-graphs/`，两者都不入库。

## 命名

版本号进文件名，不覆盖旧版本：`unseen-v0.1.jsonl` → `unseen-v0.2.jsonl`。