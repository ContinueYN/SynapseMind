# apps/web

Next.js 15 App Router + TypeScript。只做“一次诊断”的界面，不做课程商城、社区、家长端大屏。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。Web 只负责页面、交互与 API 调用；状态机、诊断、答案防护都在 `apps/api`，不在 Next.js Route Handler 里。

## 已实现路由

| 路由 | 用途 |
|---|---|
| `/` | 交题：题目、答案、过程、自评 |
| `/diagnose/[sessionId]` | 一次一问的追问；进度、历史、退出 |
| `/card/[sessionId]` | 独立卡点卡：证据、排除项、置信度、下一练 |

设计稿中还有 `/practice/[taskId]`、`/verify/[sessionId]`、`/q/[problemId]`、`/admin/review`，**M1 不建空页面**，等对应后端能力落地再加。

## 组件边界

```text
apps/web/
├─ app/
│  ├─ layout.tsx              # AppShell + metadata
│  ├─ page.tsx                # 交题页；只负责创建会话与跳转
│  ├─ diagnose/[sessionId]/   # 会话状态机的前端投影
│  ├─ card/[sessionId]/       # 只读卡点卡页
│  └─ globals.css             # 设计令牌与响应式布局
├─ components/
│  ├─ ProblemForm.tsx         # 受控表单，提交交给父级
│  ├─ ProbeCard.tsx           # 单问题 + 选项 + 我不知道 + 退出
│  ├─ ProgressRail.tsx        # 轮次/置信度
│  ├─ DiagnosisCardView.tsx   # 卡点卡视图；“我不同意”本地记录
│  └─ Transcript.tsx          # 追问历史
└─ src/lib/api/
   ├─ generated.ts            # openapi-typescript 从 FastAPI 契约生成，勿手改
   ├─ types.ts                # 对生成类型的窄别名 + 交题输入 DTO
   └─ client.ts               # fetch 封装 + ApiError
```

- 页面负责“取数 + 状态更新”，展示组件只收 props；不把 fetch 散落在组件里。
- 所有 API 错误统一为 `ApiError(status, message)`；网络失败会给可操作的提示。
- 卡点卡页不重新请求诊断逻辑，只读取同一会话的 `diagnosis`。
- 契约变更流程：改 `apps/api` 的 Pydantic DTO → `python scripts/contracts.py` → 重新 typecheck；不要手改 `generated.ts`。

## 交互硬规则

- 一次只显示一个主问题；选项不超过 4 个。
- “我不知道”永远可点，点了换更具体的问法，不重复原题。
- “直接退出学习模式”是显式出口；退出后不生成卡点卡。
- 卡点卡上必须有“我不同意”，M1 先本地记录，M2 接复核队列。
- 移动端优先；当前是文本输入，拍照上传在 M2。
- 学习模式页面不出现最终答案。

## 命令

```powershell
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run typecheck
npm run lint
npm run build
npm run generate:api   # 需要先生成 .tmp/openapi.json
```

一键启动（含 API）：在仓库根目录 `python scripts/dev.py`。

环境变量：

```text
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

默认值就是本地 API；部署时改成实际 API 域名。CORS 白名单在 `apps/api` 的 `SYNAPSE_WEB_ORIGINS` 配置。

## 当前边界

- 只支持一道种子题；换题由 API 返回 422，前端显示错误，不做假成功。
- 会话存在 API 内存里，API 重启后 `/diagnose/[id]` 会 404；M2 接 PostgreSQL。
- 历史记录只展示最近问答文本，不做完整时间线/回放。
- 不用 Tailwind/组件库：M1 只有三个页面，设计令牌 + 语义 class 更少依赖、更好审。