# apps/web

Next.js 15 App Router + TypeScript。只做“一次诊断”的界面，不做课程商城、社区、家长端大屏。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。Web 只负责页面、交互与 API 调用；状态机、诊断、答案防护都在 `apps/api`，不在 Next.js Route Handler 里。

## 已实现路由

| 路由 | 用途 |
|---|---|
| `/` | 交题：题目、答案、过程、卡在哪儿、自评 |
| `/diagnose/[sessionId]` | 一次一问的追问；轮次树突、对话线、退出 |
| `/card/[sessionId]` | 独立卡点卡：证据、排除项、置信度、下一练；可打印 |
| `/admin/review` | 教师复核：只读异议队列、逐条判断、导出 CSV |

设计稿中还有 `/practice/[taskId]`、`/verify/[sessionId]`、`/q/[problemId]`，**M1 不建空页面**，等对应后端能力落地再加。`/admin/review` 先不加鉴权，是本机工具，不要对公网暴露。

## 组件边界

```text
apps/web/
├─ app/
│  ├─ layout.tsx              # AppShell + metadata
│  ├─ template.tsx            # 换屏动效（每屏一次）
│  ├─ page.tsx                # 交题页；只负责创建会话与跳转
│  ├─ diagnose/[sessionId]/   # 会话状态机的前端投影
│  ├─ card/[sessionId]/       # 只读卡点卡页
│  ├─ admin/review/           # 教师复核页：只读队列 + 人工判断 + CSV
│  ├─ icon.svg                # 站点图标（突触标记）
│  └─ styles/                 # tokens.css + surface.css
├─ components/
│  ├─ AppShell.tsx            # 顶栏 + 页脚
│  ├─ BrandOrb.tsx            # 顶部那颗球：图案 + 外圈阅读进度，悬停展开回首页
│  ├─ Ground.tsx              # 底：白→浅蓝 + 水光 + 三团极慢呼吸的光斑（不跟指针）
│  ├─ ScrollRule.tsx          # 写 --read-n（球的进度环）与 --scroll（景深）；开局强制回顶部
│  ├─ Surface.tsx             # 琉璃面：唯一的玻璃，冷光 + 柔光 + 1° 倾斜
│  ├─ useGlass.ts             # 把指针写进 --mx/--my、--lx/--ly、--rx/--ry（rAF 节流）
│  ├─ ProblemForm.tsx         # 受控表单，提交交给父级
│  ├─ CluePreview.tsx         # 首页左栏：手上有几条线索
│  ├─ ProblemBrief.tsx        # 题面：追问时也能看到整道题（滚动吸附、可收三行）
│  ├─ Dendrite.tsx            # 首页/追问页共用的进度语法
│  ├─ ProbeCard.tsx           # 单问题 + 选项 + 我还是不懂 + 退出
│  ├─ Thread.tsx              # 已答轮次连成一条线
│  ├─ DiagnosisCardView.tsx   # 卡点卡视图；“我不同意”写回会话
│  ├─ ReviewBoard.tsx         # 教师复核：取队列、判断、导出
│  └─ review-sheet.ts         # 复核纯逻辑：判断词表、CSV、本机草稿
└─ src/lib/api/
   ├─ generated.ts            # openapi-typescript 从 FastAPI 契约生成，勿手改
   ├─ types.ts                # 对生成类型的窄别名 + 交题输入 DTO
   └─ client.ts               # fetch 封装 + ApiError
```

- 页面负责“取数 + 状态更新”，展示组件只收 props；不把 fetch 散落在组件里。
- 所有 API 错误统一为 `ApiError(status, message)`；网络失败会给可操作的提示；`422` 会被翻译成“这一问要从选项里选一个”。
- 卡点卡页不重新请求诊断逻辑，只读取同一会话的 `diagnosis`。
- 契约变更流程：改 `apps/api` 的 Pydantic DTO → `python scripts/contracts/generate.py` → 重新 typecheck；不要手改 `generated.ts`。

## 交互硬规则

- 一次只显示一个主问题；选项不超过 4 个；键盘 `1–4` 直接作答。
- “我还是不懂”永远可点，点了换更具体的问法，不重复原题。
- “直接退出学习模式”是显式出口，需要二次确认；退出后不生成卡点卡。
- 卡点卡上必须有“我不同意”：异议写回会话，同时写入本地复核库；教师复核页读同一队列，判断只存在浏览器里并导出 CSV。
- 教师复核页只读：不提供写接口，不改变会话或卡点卡；判断存 `localStorage`，换机器或清站点数据就会丢。
- 移动端优先；当前是文本输入，拍照上传在 M2。
- 学习模式页面不出现最终答案，也不出现能力分数或等级。

## 视觉约束

视觉规范落在 `app/styles/`。以下五条是评审基线：

- 一池白玻璃：底是白→浅蓝的渐变 + 三团呼吸光斑，**每屏只有一块大玻璃**；小玻璃砖可以有，但不能玻璃叠玻璃。
- 质感来自玻璃配方（白边 + 上缘高光 + 两层落影 + `blur(24px) saturate(165%)`）和跟指针走的冷光，不来自贴图。
- 整页禁止选中文字（`user-select: none`），输入框单独恢复成可选中。
- 动效必须承载信息：节点亮 = 走到这一轮，液面涨 = 把握在变，顶部液面 = 读到哪儿了。液体只出现在有变化的地方，没有回弹凑数。
- 树突的节点数只能来自真实数据（`history.length` / 草稿字段），不许预先画满。

## 命令

```powershell
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run typecheck
npm run lint
npm test           # Vitest + jsdom：结构提示、交题表单、教师复核的组件回归
npm run test:watch
npm run build
npm run generate:api   # 需要先生成 .tmp/openapi.json
```

组件测试与源码同目录（`*.test.tsx`），环境配置在 `vitest.config.mts`，`src/test/setup.ts` 负责 jsdom 的 `matchMedia`/`rAF` 垫片。它们只测纯前端交互，不替代 API 的 `pytest`。

一键启动（含 API）：在仓库根目录 `python scripts/dev/run.py`。

环境变量：

```text
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_DIST_DIR=.next        # 可选：并行跑第二份产物时指向别的目录
```

默认值就是本地 API；部署时改成实际 API 域名。CORS 白名单在 `apps/api` 的 `SYNAPSE_WEB_ORIGINS` 配置。

## 当前边界

- 只支持一道种子题；换题由 API 返回 422，前端显示错误，不做假成功。
- 会话默认在 API 内存里；`run.py` 会启用本地 SQLite 快照（`SYNAPSE_SESSION_DB`），API 重启后 `/diagnose/[id]` 仍可恢复。仍未接 PostgreSQL，也没有清理/TTL。
- 教师复核页没有鉴权，队列只含卡面结论、不含学生原文；CSV 导出按浏览器本地时间命名。
- 历史记录只展示问答原话，不做完整时间线/回放。
- 不用 Tailwind/组件库：设计令牌 + 语义 class 更少依赖、更好审。