# eval

离线评测与红队。**没有这个目录，项目就只剩演示。**

> 整个 `eval/` 在 `.gitignore` 内（根目录锚定）。数据集与报告是私有材料：小样本数据、`README` 用 `git add -f` 入库，报告只留在本地。

## 数据集

| 目录 | 内容 | 当前规模 | 目标 |
|---|---|---|---|
| [`golden/`](golden/README.md) | 金标准对话：题目 + 学生过程 + 标注层 + 逐轮作答 | 10 条 | 100 条，卡点一致率 ≥75% |
| [`problems/`](problems/README.md) | 建图评测题：只有题干与主题标签 | 20 条 | 换题后 ≥80% 建图成功 |
| [`redteam/`](redteam/README.md) | 诱导、越界、答案泄漏、提示注入用例 | 只有格式说明 | 50 条，泄漏 0、越界 0 |

## 核心指标

| 指标 | 目标 | 说明 |
|---|---|---|
| 卡点节点一致率 | ≥75% | 系统 vs 双教师多数 |
| L 层一致率 | ≥80% | 同一节点 |
| 建图成功率 | ≥80% | 20 道未见题，结构合法 + 人工抽查通过 |
| 平均追问轮数 | 4–6 | 超过 6 轮强制收束 |
| 首问 P95 | <8s | 不含 OCR |
| 答案泄漏 | 0 | 5-gram + SymPy + 人工抽样 |
| “说中了” | ≥70% | 1–5 分，≥4 算中 |
| 24h 迁移 | ≥60% | 新题同节点不复发 |

## 运行

```powershell
cd apps/api

# M2 退出判定：10 条 golden 回放（off 规则基线；加 --live-shadow 对照模型）
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py --live-shadow

# M2.5 S4 建图：20 道未见题，需要 DEEPSEEK_API_KEY（仓库根 .env）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py
```

## 报告

产物不进 Git，留在本地：

```text
eval/reports/
├─ m2-exit-v0.1.md              # 逐轮 (turn, top1, margin, kind)
├─ m2-exit-v0.1-shadow.md       # 真实模型双跑的差异与审计统计
├─ m2.5-s4-graph-build.md       # 20 题建图的机械结果
├─ m2.5-s4-graph-review.md      # 人工抽查结论（当前 19/20）
└─ s4-graphs/*.json             # 逐题生成的图，供复核与比对
```

聚合数据只放版本号、模型 id、prompt 版本和指纹；`session_id` 用于追溯，不把学生原文贴进报告。