# app/styles

样式按职责拆成两个文件，在 [`../layout.tsx`](../layout.tsx) 中按顺序导入一次：

1. `tokens.css`：颜色、字阶、间距、圆角、动效曲线与变量别名。
2. `surface.css`：玻璃材质与组件样式。

规则：

- 保持 `layout.tsx` 的显式导入顺序，不在 CSS 文件之间使用 `@import`。
- 新组件的样式写入 `surface.css`，类名统一使用 `sm-` 前缀。
- 每屏只有一块大玻璃；玻璃不能叠在玻璃上。
- `backdrop-filter` 只用于 `.sm-sheet`、`.sm-probe`、`.sm-top`、`.sm-brief`。
- 颜色、间距、字号、圆角、动效全部从 token 取值，不在组件里写裸数值。
- 页面默认 `user-select: none`；输入框在 `surface.css` 中显式恢复 `text`。
- 不引入外部字体，只使用 `tokens.css` 中的系统字体栈。
- 动效只表达状态变化，不添加装饰性位移、扫光或逐字入场。