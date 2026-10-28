# apps/web

Next.js 15 App Router + TypeScript。只做“一次诊断”的界面，不做课程商城、社区、家长端大屏。

选型依据见 [ADR-0001](../../docs/adr/0001-language-and-code-architecture.md)。Web 只负责 RSC/ISR、SSE 外壳与交互；状态机、诊断、AI 编排都在 `apps/api`，不在 Next.js 的 Route Handler 里。

## 路由

| 路由 | 用途 |
|---|---|
| `/` | 交题：粘贴/拍照，填答案与过程 |
| `/diagnose/[sessionId]` | 一次一问的追问界面，SSE 流式 |
| `/card/[sessionId]` | 卡点卡：证据、排除项、置信度、下一练 |
| `/practice/[taskId]` | 3 分钟微干预 + 同构题 |
| `/verify/[sessionId]` | 24h/7d 迁移题 |
| `/q/[problemId]` | 公开题目卡点页（SEO/GEO，不泄露答案） |
| `/admin/review` | 教师复核队列（内网/白名单） |

## 交互硬规则

- 一次只显示一个主问题；选项不超过 4 个。
- “我不知道”永远可点，点了降级，不重复原题。
- “直接看答案”是显式出口；点了退出学习模式，不生成卡点卡。
- 卡点卡上必须有“我不同意”，进入复核队列。
- 移动端优先；拍照上传失败可退回文本。

## 目标命令

```bash
pnpm install
pnpm dev
pnpm build
pnpm lint
```

> 当前目录只有设计说明，尚未提交 `package.json` 与页面代码。