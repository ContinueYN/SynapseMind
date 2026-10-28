# apps/ai-worker

Python 离线任务：OCR 后处理、知识 ETL、golden 评测、批量标注辅助。

## 不做的事

- 不处理在线追问的实时状态机（在 `apps/api` 的 `ai` 模块）。
- 不直接写业务库；通过 API 或消息队列回写。
- 不把模型输出直接当标注真值；必须有人审。

## 计划任务

| 任务 | 输入 | 输出 |
|---|---|---|
| `ocr_postprocess` | 题目原图/OCR 原始结果 | LaTeX 归一化文本、置信度 |
| `kb_etl` | 教材/讲义/错因卡 | `kb_chunk` + embedding |
| `eval_golden` | `eval/golden/*.jsonl` | 一致率、轮数、泄漏率报告 |
| `redteam` | `eval/redteam/*.txt` | 泄漏/越界/诱导结果 |
| `sample_review` | 线上会话 ID | 抽样复核清单 |

## 目录约定

```text
ai-worker/
├─ src/
│  ├─ ocr/
│  ├─ etl/
│  ├─ eval/
│  └─ redteam/
├─ tests/
└─ requirements.txt
```

## 目标命令

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m src.eval.run --set golden
```

> 当前目录只有设计说明，尚未提交源码与依赖。