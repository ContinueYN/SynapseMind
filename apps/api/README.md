# apps/api

Python 3.12 + FastAPI 的**模块化单体**。在线链路（状态机、诊断、AI 编排、SSE）都在这里；离线任务在 [`../worker`](../worker/README.md)。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。

## 计划模块

```text
apps/api/src/synapse/
├─ domain/           # 纯函数，零 I/O
│  ├─ dialogue/      # 状态、事件、转移表、会话不变量
│  ├─ diagnosis/     # 步骤对齐、假设后验、卡点判定
│  ├─ problem/       # 题目、解法图、答案隔离仓储
│  ├─ evidence/      # 证据链、迁移验证
│  └─ guard/         # 泄漏规则、引用规则
├─ application/      # 用例编排 + ports（Protocol）
├─ infrastructure/   # llm/ rag/ db/ cache/ ocr/ cas 实现
├─ api/              # FastAPI 路由、SSE、鉴权、幂等
└─ workers/          # Arq 任务入口（与 worker 共用）
```

## 依赖方向

```text
api → application → domain
infrastructure → application.ports
domain 不 import FastAPI / SQLAlchemy / OpenAI
```

用 `import-linter` 在 CI 强制；`openai`/模型 SDK 只允许出现在 `infrastructure/llm/`。

## 里程碑

| 阶段 | 交付 | 退出条件 |
|---|---|---|
| M1 | `dialogue` + `problem` + `diagnosis` 文本闭环 | 3 道题端到端可演示 |
| M2 | `infrastructure/llm` 追问 + JSON Schema 校验 + 降级 | 5 轮内区分 2 个假设 |
| M3 | `rag` 检索 + 引用校验 | recall@8 ≥0.80 |
| M4 | `evidence` 迁移验证 + 教师复核 | 24h 迁移可记录 |

## 约定

- 路由函数 ≤20 行；业务在 `application`，状态迁移在 `domain`。
- **LLM 不决定下一状态**：它只填槽位、给动作候选；转移表说了算。
- 所有 LLM 输出先过 Pydantic/JSON Schema，再进状态机；失败重试 1 次后走确定性模板。
- 答案独立表 + 独立仓储；Prompt 构建器物理上读不到答案。
- 学习模式响应 DTO 里**不允许出现 `solution`/`final_answer` 字段**。
- 数据库变更用 Alembic；接口变更先改 `specs/`，再改代码。

## 构建（目标）

```bash
uv sync
uv run fastapi dev src/synapse/api/main.py
uv run pytest
```

> 当前目录只有设计说明，尚未提交 `pyproject.toml` 与源码。