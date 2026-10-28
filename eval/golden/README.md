# eval/golden

100 条 golden 对话。格式为 JSONL，一行一条。

## 字段

```json
{
  "id": "G0001",
  "problem_id": "P_FUNC_001",
  "category": "wrong_answer",
  "problem": "f(x)=ln x - a x, ...",
  "student_answer": "a>=1/e",
  "student_work": "f'(x)=1/x-a; ...",
  "expected": {
    "layer": "L2",
    "node_id": "n4",
    "label": "条件转译/参数分类",
    "acceptable_layers": ["L2"],
    "must_ask": ["a=0 时 f'(x) 是什么"],
    "must_not": ["直接给 a<=0 的结论"]
  },
  "teachers": [
    {"id": "T01", "layer": "L2", "node_id": "n4"},
    {"id": "T02", "layer": "L2", "node_id": "n4"}
  ],
  "notes": "答案对但过程漏条件；用于测第一处偏离"
}
```

## 类别配额

| 类别 | 数量 |
|---|---|
| `wrong_answer` | 60 |
| `right_answer_missing_case` | 20 |
| `no_idea` | 10 |
| `negative`（超纲/多卡点/情绪） | 10 |

## 标注规则

- 两位教师**独立**标注，不能先看系统输出；
- 不一致时记录，不强行统一；以多数为金标准，第三位仲裁只用于争议集；
- 每条必须写 `must_ask` 与 `must_not`，否则不算完成；
- 学生原文脱敏，保留 `student_id` 的哈希。

## 命名

`G0001.jsonl` 单条文件或 `golden-v0.1.jsonl` 汇总。版本号进文件名，不覆盖旧版本。