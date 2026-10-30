# app/styles

按职责拆成两个文件，在 [`../layout.tsx`](../layout.tsx) 里按顺序导入一次：

1. `tokens.css` — 近白底、琉璃色、玻璃参数、字阶、间距、圆角、动效曲线、旧变量名别名；
2. `surface.css` — 玻璃材质与全部组件样式（底、外壳、字标、液态轨道、索引、引文、树突、表单、追问卡、卡点卡、断点、打印、减少动效）。

规范真源是 [`docs/design/chapters/14-视觉系统.md`](../../../../docs/design/chapters/14-视觉系统.md)；本目录只做实现，不新增方向。

规则：

- 保持 `layout.tsx` 里的显式导入顺序，不要在文件之间用 `@import`。
- 新组件的视觉规则写进 `surface.css`，类名一律 `sm-` 前缀。
- **一屏只有一块大玻璃**（`.sm-sheet` / `.sm-probe`）。小玻璃砖可以有，但不能是"浮在另一块玻璃上的玻璃"。
- `backdrop-filter` 只允许出现在 `.sm-sheet` / `.sm-probe` / `.sm-top` / `.sm-brief`；不要给列表项、选项、按钮、小砖都加。
- 玻璃配方照抄第 14 章 §14.4：淡蓝板子（比页面**更蓝**，不是更白）+ 白边 1px（下缘偏冷）+ 上缘高光 + 下缘折射线 + 两层落影 + `blur(24px) saturate(160%) brightness(1.02)` + 表面柔光 + 5% 颗粒 + `.sm-sheen` 三层慢光。改之前先想清楚为什么要改。
- 指针量（`--mx/--my` 冷光、`--lx/--ly` 柔光、`--rx/--ry` 倾斜）**只能直接写 style 变量**，不许进 React state；统一走 `components/useGlass.ts`，触屏与 reduce-motion 不启用。
- 圆角只有 `--r-1`(10) / `--r-2`(14) / `--r-3`(22) / `--r-pill`；文字块本身不要圆角。
- 颜色只从 token 取。彩色只有蓝一种；**11px 小字必须用 `--azure-ink`**，`--azure` 只给图形。
- 间隙用 `--s1…--s9`，字号用 `--fs-*`；不要在组件里写裸数值。
- 运动只用 `--t-fast`(140) / `--t-base`(200) / `--t-slow`(280) + `--ease-out`；只给状态变化，超过 400ms 的动画一律不要。
- 液体感只出现在**材料**里：淡蓝板子、三层慢光、弯月面、内阴影、颗粒、边框冷光；交互里只允许"键"的 1px 抬升与压回。**禁止**按下水珠、扫光条、文字块悬停位移/缩放、背景视差、逐字入场。
- 版面是**一整条流**：段落只用留白 + `.sm-label` 分隔，**不许**铺色带、画分栏细线、摆卡片阵列（第 3 版就是这么把页面切碎的）。
- 底色不许压深：`--paper` 到 `#DCEAFB` 为止；比 `#EEF5FD` 更白是白板，比 `#D3E4F9` 更深是发闷。
- 整页 `user-select: none`，输入框在 `surface.css` 里显式恢复 `text`；新增可编辑元素时要一起加。
- 不引入外部字体（本机直连外网不通，`next/font/google` 会卡死构建），只用 `tokens.css` 里的系统栈。
- 旧变量名（`--bg`、`--text`、`--accent` 等）在 `tokens.css` 里作为别名保留，避免一次性改爆。
- `paper.css` 已删除：纸与出版那套（衬线、零圆角、零玻璃）在 H4 被明确否决，不要恢复。
- `glass.css` / `GlassCard.tsx` / `Backdrop.tsx` 已删除：它们的能力现在在 `surface.css` 与 `Surface.tsx` / `Ground.tsx` 里，不要恢复旧文件。
- `components/reactbits/` 已删除：Aurora、GradientText、SpotlightCard、StarBorder 属于第 14 章 §14.12 的反模式，不要重新引入。
- 液面（`LiquidVessel`）、旧进度条（`ProgressRail`）、旧记录（`Transcript`）已删除，进度统一由 `Dendrite` 表达——`Dendrite` 现在是「一根玻璃管 + 液面 + 几颗珠」，不再是折线；不许恢复曲线与"卡点短须"。
