# apps/web

Next.js 15 App Router + TypeScript。只做“一次诊断”的界面，不做课程商城或社区。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。Web 只负责页面、交互与 API 调用；状态机、诊断、答案防护都在 `apps/api`，不在 Next.js Route Handler 里。

## 已实现路由

| 路由 | 用途 |
|---|---|
| `/` | 交题：题目、答案、过程、卡在哪儿、自评 |
| `/diagnose/[sessionId]` | 一次一问的追问；轮次树突、对话线、退出 |
| `/card/[sessionId]` | 独立卡点卡：证据、排除项、置信度、下一练；可打印 |
| `/admin/review` | 内部复核：只读异议队列、逐条判断、导出 CSV |

设计稿中还有 `/practice/[taskId]`、`/verify/[sessionId]`、`/q/[problemId]`，**M1 不建空页面**，等对应后端能力落地再加。鉴权开启时 `/admin/review` 和队列接口都要求登录；判断仍只存在本机浏览器里，不是面向学生的入口。

## 组件边界

```text
apps/web/
├─ app/
│  ├─ layout.tsx              # AppShell + metadata
│  ├─ template.tsx            # 换屏动效（每屏一次）
│  ├─ page.tsx                # 交题页；只负责创建会话与跳转
│  ├─ diagnose/[sessionId]/   # 会话状态机的前端投影
│  ├─ card/[sessionId]/       # 只读卡点卡页
│  ├─ admin/review/           # 内部复核页：只读队列 + 人工判断 + CSV
│  ├─ icon.svg                # 站点图标（突触标记）
│  └─ styles/                 # tokens.css + surface.css
├─ components/
│  ├─ ui/                     # 无业务含义的视觉原语
│  │  ├─ BrandOrb.tsx         # 顶部那颗球：图案 + 外圈阅读进度，悬停展开回首页
│  │  ├─ Dendrite.tsx         # 首页/追问页共用的进度语法
│  │  ├─ Ground.tsx           # 底：白→浅蓝 + 水光 + 三团极慢呼吸的光斑（不跟指针）
│  │  ├─ Plane.tsx            # 一块玻璃板：文字的家
│  │  ├─ PointerField.tsx     # 页面级指针光场
│  │  ├─ Reveal.tsx           # 滚动进入时的一次揭示
│  │  ├─ ScrollRule.tsx       # 写 --read-n（球的进度环）与 --scroll（景深）；开局强制回顶部
│  │  ├─ Surface.tsx          # 琉璃面：唯一的玻璃，冷光 + 柔光 + 1° 倾斜
│  │  └─ Thread.tsx           # 已答轮次连成一条线
│  ├─ layout/
│  │  ├─ AppShell.tsx         # 顶栏 + 页脚
│  │  └─ ScrollMemory.tsx     # 换页时记住/恢复滚动位置
│  ├─ auth/
│  │  ├─ AccountMenu.tsx      # 顶部账号入口：登录、退出、模型设置
│  │  └─ SignInRequired.tsx   # 401 时的统一「请先登录」状态
│  ├─ diagnosis/
│  │  ├─ AgentTracePanel.tsx  # 只读工具轨迹；不包装成诊断
│  │  ├─ CluePreview.tsx      # 首页左栏：手上有几条线索
│  │  ├─ CoachPanel.tsx       # 过程反馈：我错在哪 / 怎么开始
│  │  ├─ DiagnosisCardView.tsx # 卡点卡视图；「我不同意」写回会话
│  │  ├─ GenericReviewView.tsx # 通用复盘 / 决策框 / 代码复现卡
│  │  ├─ IntakeView.tsx       # 通用入口：结构清单 + 一次澄清
│  │  ├─ KnowledgePanel.tsx   # 卡旁的出处知识卡
│  │  ├─ PhysicsStepCheck.tsx # 物理单步检查（量纲 / 数值回代）
│  │  ├─ ProbeCard.tsx        # 单问题 + 选项 + 我还是不懂 + 退出
│  │  ├─ ProblemBrief.tsx     # 题面；追问时也能看到整道题
│  │  ├─ ProblemForm.tsx      # 受控表单，提交交给父级
│  │  ├─ ScaffoldView.tsx     # 空白起步的 1–2 步示例
│  │  ├─ StepCheck.tsx        # 数学单步检查（只查等号）
│  │  ├─ StepVerdictView.tsx  # 单步检查结果的共用视图
│  │  └─ StructureHintView.tsx # NONE 档学科的结构提示
│  └─ review/
│     └─ ReviewBoard.tsx      # 内部复核：取队列、判断、导出
├─ hooks/
│  ├─ useGlass.ts             # 把指针写进 --mx/--my、--lx/--ly、--rx/--ry（rAF 节流）
│  └─ useTilt.ts              # 一组玻璃砖共用的倾斜 / 高光委托
└─ src/lib/
   ├─ api/
   │  ├─ http.ts              # API_BASE、ApiError、鉴权错误判断、登录票据队列、fetch 传输
   │  ├─ auth.ts              # 账号：getMe / register / login / logout
   │  ├─ settings.ts          # 账号自己的模型配置
   │  ├─ sessions.ts          # 会话、追问、退出、异议
   │  ├─ steps.ts             # 单步验证
   │  ├─ agent.ts             # 工具轨迹
   │  ├─ coach.ts             # 过程反馈
   │  ├─ review.ts            # 复核卡与内部队列
   │  ├─ knowledge.ts         # 知识卡检索
   │  ├─ index.ts             # 公共 barrel（不导出 fetch 传输层）
   │  ├─ generated.ts         # openapi-typescript 从 FastAPI 契约生成，勿手改
   │  └─ types.ts             # 对生成类型的窄别名 + 交题输入 DTO
   ├─ physics/physics-step.ts # 物理单步表单 → API data 载荷
   ├─ review/review-sheet.ts  # 复核纯逻辑：判断词表、CSV、本机草稿
   ├─ session-handoff.ts      # 交题页 → 诊断页的一次性会话交接
   └─ research/papers.ts      # 首页引用的公开文献
```

- 页面负责“取数 + 状态更新”，展示组件只收 props；不把 fetch 散落在组件里。
- API 访问走窄模块（`@/src/lib/api/sessions`、`.../auth`、`.../settings` 等）或公共 barrel `@/src/lib/api`；`http.ts` 的传输层只给这些模块用，不直接进组件。
- 所有 API 错误统一为 `ApiError(status, message)`；网络失败会给可操作的提示；`422` 会被翻译成“这一问要从选项里选一个”。
- 卡点卡页不重新请求诊断逻辑，只读取同一会话的 `diagnosis`。
- 契约变更流程：改 `apps/api` 的 Pydantic DTO → `python scripts/contracts/generate.py` → 重新 typecheck；不要手改 `generated.ts`。

## 交互硬规则

- 一次只显示一个主问题；选项不超过 4 个；键盘 `1–4` 直接作答。
- “我还是不懂”永远可点，点了换更具体的问法，不重复原题。
- “直接退出学习模式”是显式出口，需要二次确认；退出后不生成卡点卡。
- 卡点卡上必须有“我不同意”：异议写回会话，同时写入本地复核库；内部复核页读同一队列，判断只存在浏览器里并导出 CSV。
- 内部复核页只读：不提供写接口，不改变会话或卡点卡；判断存 `localStorage`，换机器或清站点数据就会丢。
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
npm test           # Vitest + jsdom：结构提示、交题表单、内部复核的组件回归
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
- 会话默认在 API 内存里；`run.py` 会启用本地 SQLite 快照（`SYNAPSE_SESSION_DB`），API 重启后 `/diagnose/[id]` 仍可恢复。账号、登录票据和加密的模型凭据在 PostgreSQL；诊断快照仍是 SQLite，没有自动 TTL。
- 内部复核页在开启账号鉴权时要求登录（401 显示「请先登录」）；队列只含卡面结论、不含学生原文；CSV 导出按浏览器本地时间命名。
- 历史记录只展示问答原话，不做完整时间线/回放。
- 不用 Tailwind/组件库：设计令牌 + 语义 class 更少依赖、更好审。