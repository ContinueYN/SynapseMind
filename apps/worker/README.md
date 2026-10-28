# apps/worker

Python 离线任务的**部署入口**：OCR 后处理、知识 ETL、golden 评测、红队、批量标注辅助。

代码不在这里重复一份：worker 与 `apps/api` 共用同一个镜像和 `synapse` 包，只是启动命令不同。这样领域模型、契约、评测脚本只有一份。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。

## 不做的事

- 不处理在线追问的实时状态机（在 `apps/api` 的 `application`/`domain`）。
- 不直接写业务库；通过应用层端口或队列回写。
- 不把模型输出直接当标注真值；必须有人审。
- 不把 LLM 主链路塞进队列；进队列就破了 8s 首问。

## 计划任务

| 任务 | 输入 | 输出 |
|---|---|---|
| `ocr_postprocess` | 题目原图/OCR 原始结果 | LaTeX 归一化文本、置信度 |
| `kb_etl` | 教材/讲义/错因卡 | `kb_chunk` + embedding |
| `eval_golden` | `eval/golden/*.jsonl` | 一致率、轮数、泄漏率报告 |
| `redteam` | `eval/redteam/*.txt` | 泄漏/越界/诱导结果 |
| `sample_review` | 线上会话 ID | 抽样复核清单 |

## 代码位置

```text
apps/api/src/synapse/workers/
├─ settings.py       # Arq WorkerSettings
├─ ocr.py
├─ etl.py
├─ eval.py
└─ redteam.py
```

`apps/worker/` 只保留本说明与（后续的）容器启动配置，不放第二份领域代码。

## 目标命令

```bash
# 与 api 同一个镜像/依赖
uv run --project apps/api arq synapse.workers.settings.WorkerSettings

# 评测
uv run --project apps/api python -m synapse.workers.eval --set golden
```

> 当前目录只有设计说明，尚未提交源码与依赖。