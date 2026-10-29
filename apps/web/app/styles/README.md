# app/styles

按职责拆成两个文件，在 [`../layout.tsx`](../layout.tsx) 里按顺序导入一次：

1. `tokens.css` — 冰蓝色板、字体栈、圆角/间距、旧变量名别名；
2. `glass.css` — 琉璃系统本体：五层光学、骨架、字阶、8 个组件、状态、无障碍与断点。

规范真源是 [`docs/design/chapters/14-视觉系统.md`](../../../../docs/design/chapters/14-视觉系统.md)；本目录只做实现，不新增方向。

规则：

- 保持 `layout.tsx` 里的显式导入顺序，不要在文件之间用 `@import`。
- 新组件的视觉规则写进 `glass.css`，类名一律 `sm-` 前缀。
- 一块玻璃的层序写死在 `glass.css`（折射 0 → 高光/光带 1 → 色散 2 → 高光边 3 → 内容 4）。新组件不要再自己叠 z-index，用 `GlassCard`。
- 折射层必须读真实光斑坐标（`GlassCard.tsx` 的 `syncRefraction`），不要用固定渐变假装。
- 字距按光学尺寸分别定，别全站一个 `letter-spacing`。
- 不引入外部字体（本机直连外网不通，`next/font/google` 会卡死构建），只用 `tokens.css` 里的系统栈。
- 旧变量名（`--bg`、`--text`、`--accent` 等）在 `tokens.css` 里作为别名保留，避免一次性改爆。
- `paper.css` 已删除：纸与出版那套（衬线、零圆角、零玻璃）在 H4 被明确否决，不要恢复。
- `components/reactbits/` 已删除：Aurora、GradientText、SpotlightCard、StarBorder 属于第 13 章 §13.12 的反模式，不要重新引入。