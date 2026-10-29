# eval/golden

M2 金标准集。**v0.1 共 10 条**：`golden-v0.1.jsonl`，JSONL 一行一条。

> `eval/` 整体在 `.gitignore` 内。本目录的 `README.md` 与 `golden-v0.1.jsonl` 需要入库，新增数据请 `git add -f`，否则新克隆与 CI 都没有 case。

## 字段（v0.1 实际使用）

```json
{
  "case_id": "g-001",
  "category": "wrong_answer",
  "problem_text": "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。",
  "answer": "a≥1/e",
  "work": "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。...",
  "label_layer": "L2",
  "answers": ["A", "A"],
  "max_turn": 5,
  "expect": "diagnose",
  "notes": "只做了 a>0 一支，漏掉 a≤0。"
}
```

| 字段 | 说明 |
|---|---|
| `case_id` | 全局唯一，`g-NNN` |
| `category` | `wrong_answer` / `right_answer_missing_case` / `no_idea` / `negative` |
| `problem_text` | 必须能被 `InMemoryProblemRepository.find_for` 命中（当前只有种子题） |
| `answer` / `work` | 学生原文；**入库前脱敏**，真实数据另存 `student_id_hash` |
| `label_layer` | 人工标注的卡点层：`L1` / `L2` / `L4`；`NONE` 表示过程完整、无断点 |
| `answers` | 逐轮选项 id（`A`–`D` / `UNKNOWN`），按探针被问到的顺序 |
| `max_turn` | 允许收敛的最晚轮次（≤5 才算通过） |
| `expect` | `diagnose`（应在 ≤`max_turn` 轮定位到 `label_layer`）或 `stop`（应安全收束、不断言卡点） |
| `notes` | 标注理由，进退出判定报告 |

## 判定

由 `apps/api/src/synapse/application/replay.py` 执行，测试在 `apps/api/tests/test_golden.py`：

1. `expect=diagnose`：`turn ≤ max_turn`、`kind == diagnose`、top-1 的层等于 `label_layer`；
2. `expect=stop`：到轮次上限或探针用完，`kind != diagnose`，不得硬判；
3. 全程泄漏降级次数为 0（`reason_code == LEAK_FALLBACK`）。

报告：`python scripts/eval/m2_exit.py` → `eval/reports/m2-exit-v0.1.md`。

## v0.1 的构成与已知边界

| 类别 | v0.1 | 目标配额（100 条口径） |
|---|---|---|
| `wrong_answer` | 4 | 60 |
| `right_answer_missing_case` | 2 | 20 |
| `no_idea` | 2 | 10 |
| `negative` | 2 | 10 |

- 只有一道种子题（`P_FUNC_001`），10 条 case 共享同一张解法图。
- `EVIDENCE` 只对 `p_a0_derivative` / `p_boundary_check` / `p_max_value` 有权重，实测仅 `H_L2` 能越过 `0.80 + 0.25`；`L1` / `L4` 案例记为 `expect=stop`。
- 可诊断案例平均 2.4 轮收束（第 12 章 §12.6 的目标是 4–6 轮）。原因不是追问变少，而是单图证据第 2 轮就饱和。
- 这三条都是 M2.5（学科插件 + 证据标定）的输入。

## 100 条口径的目标格式（尚未使用）

早期设计给 100 条留了更重的标注字段：`expected.must_ask` / `must_not`、`teachers[]`（两位教师独立标注 + 第三位仲裁）。扩到 100 条时再引入，避免现在为不存在的规模付出标注成本。

## 命名

版本号进文件名，不覆盖旧版本：`golden-v0.1.jsonl` → `golden-v0.2.jsonl`。