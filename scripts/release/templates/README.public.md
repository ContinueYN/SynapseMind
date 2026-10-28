# SynapseMind 突触智学

> **不是讲这道题，是找到你卡住的那一步。**

学生交来一道不会或做错的题，加上自己的答案和过程（也可以只写“不会”）。系统用 2–6 轮追问，定位最早断掉的认知动作，给一张带证据的卡点卡，而不是先讲整题答案。

**当前状态：M1 walking skeleton，可本地运行。** 单题交题 → 解法图对齐 → 2 轮探针 → L2 卡点卡已经打通；LLM 生成、RAG、迁移验证、数据库与鉴权尚未接入。这不是已上线产品。

## 现在能跑什么

| 能力 | 状态 | 位置 |
|---|---|---|
| 交题 + 过程 | ✅ 文本、预填示例题 | `apps/web` |
| 状态机（显式转移表） | ✅ 10 个状态、事件驱动 | `apps/api/src/synapse/domain/dialogue/` |
| 步骤对齐 + 首个断点 | ✅ 规则版（M2 换 LLM 策略） | `domain/problem/alignment.py` |
| 假设后验 + 探针选择 | ✅ 3 个假设、2–6 轮、0.80/0.25 阈值 | `domain/diagnosis/` + `application/planner.py` |
| 答案泄漏防护 | ✅ 禁用词 + 5-gram 出口装饰器 | `domain/guard/` + `application/composer.py` |
| 卡点卡 + 独立卡页 | ✅ L2 示例、证据/排除/置信度/下一练 | `application/card_builder.py` + `/card/[sessionId]` |
| 持久化 | ⏳ 内存仓储（重启即丢） | `infrastructure/in_memory.py` |
| 拍照、LLM、RAG、24h 验证 | ⏳ M2/M3 | 产品设计文档不公开 |

## 快速开始

需要 Python 3.12+、Node.js 22+。一条命令启动 API 和 Web（首次会建 venv、装依赖）：

```powershell
python scripts/dev/run.py
```

打开 `http://localhost:3000`；API 文档在 `http://localhost:8000/docs`。`Ctrl+C` 会同时停掉两个进程。

只检查环境、不启动：

```powershell
python scripts/dev/run.py --check
```

手动分开启动：

```powershell
# 终端 1：API
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn --app-dir src synapse.api.main:app --reload --port 8000

# 终端 2：Web
cd apps/web
npm install
npm run dev
```

## 架构

- **Web**：Next.js 15 App Router + TypeScript，三个页面（交题 / 追问 / 卡点卡）。
- **API**：Python 3.12 + FastAPI + Pydantic v2，模块化单体，按 `domain / application / infrastructure / api` 分层；M1 用内存适配器。
- **契约**：DTO 是源，FastAPI 导出 OpenAPI，`scripts/contracts/generate.py` 生成 `apps/web/src/lib/api/generated.ts`；生成的 TS 已入库，fresh clone 不跑 Python 也能 typecheck/build。
- **硬约束**：LLM 不直接选下一状态；答案库与学习模式 DTO 物理隔离；一轮只问一个问题；最多 6 轮；后验 ≥ 0.80 且 margin ≥ 0.25 才收敛。

```text
.
├─ apps/
│  ├─ web/                  # Next.js：交题 / 追问 / 卡点卡
│  ├─ api/                  # FastAPI：状态机 / 对齐 / 探针 / 卡点卡 / 防护
│  └─ worker/               # Arq 入口（M2）
├─ specs/                   # 状态机 + JSON Schema
├─ infra/                   # Compose / Nginx / 可观测性规划
├─ scripts/                 # 启动、契约、检查、可选导出
├─ docs/adr/                # 架构决策记录
├─ .github/workflows/       # CI
├─ README.md
├─ CONTRIBUTING.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ CHANGELOG.md
```

应用分工见 [`apps/README.md`](apps/README.md)，API 约束见 [`apps/api/README.md`](apps/api/README.md)，Web 职责见 [`apps/web/README.md`](apps/web/README.md)。

## 检查命令

```powershell
# 后端
cd apps/api
pytest
ruff check src tests
ruff format --check src tests
mypy src
lint-imports

# 前端
cd apps/web
npm run typecheck
npm run lint
npm run build
```

## 当前边界

- 只支持一道种子题（高中数学「函数与导数」、参数分类）；换题返回 422，这是 M1 的显式边界。
- 没有数据库、LLM、OCR、鉴权；会话存在内存里，重启即丢。
- 没有真实用户数据或疗效证据；产品设计与评测数据不随公开仓库发布。
- UI 使用 React Bits 的 Aurora、GradientText、SpotlightCard、StarBorder，第三方许可与限制见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## License

原创代码使用 [MIT](LICENSE) © 2026 SynapseMind contributors。React Bits 组件不适用 MIT，使用前请阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。