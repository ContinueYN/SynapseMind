# eval

离线评测与红队。**没有这个目录，项目就只剩演示。**

## 数据集

| 目录 | 内容 | 目标 |
|---|---|---|
| [`golden/`](golden/README.md) | 100 条真实/仿真对话，双教师标注 | 卡点一致率 ≥75% |
| [`redteam/`](redteam/README.md) | 50 条诱导/边界输入 | 答案泄漏 0、越界 0 |

## 核心指标

| 指标 | 目标 | 说明 |
|---|---|---|
| 卡点节点一致率 | ≥75% | 系统 vs 双教师多数 |
| L 层一致率 | ≥80% | 同一节点 |
| 平均追问轮数 | 4–6 | 超过 6 轮强制收束 |
| 首问 P95 | <8s | 不含 OCR |
| 答案泄漏 | 0 | 5-gram + SymPy + 人工抽样 |
| “说中了” | ≥70% | 1–5 分，≥4 算中 |
| 24h 迁移 | ≥60% | 新题同节点不复发 |

## 报告

每次跑完输出：

```text
reports/
└─ 2026-11-01/
   ├─ summary.json
   ├─ disagreements.md
   └─ leaks.md
```

`summary.json` 只放聚合与版本号；具体对话用 `session_id` 追溯，不把学生原文贴进报告。

## 运行

```bash
python -m apps.ai_worker.eval.run --set golden --model configs/mvp.yaml
```

> 当前只有格式说明，尚无数据与脚本。先标 10 条跑通，再扩到 100 条。